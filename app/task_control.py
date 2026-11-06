"""Cancellation for a conversion and all of its native helper processes."""
import os
import signal
import subprocess
import threading
import time


class ConversionCancelled(Exception):
    pass


class TaskControl:
    def __init__(self):
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.accepting = True

    def check(self):
        if self.cancelled.is_set():
            raise ConversionCancelled('已停止当前任务，可以修改参数后重新生成。')

    def cancel(self):
        with self.lock:
            if not self.accepting:
                return False
            self.cancelled.set()
            return True

    def begin_save(self):
        with self.lock:
            self.check()
            self.accepting = False


class WindowsJob:
    def __init__(self):
        import ctypes
        from ctypes import wintypes as w
        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_longlong) for name in ('user','kernel','period_user','period_kernel')] + [
                (name, w.DWORD) for name in ('faults','total','active','terminated')]
        self.accounting_type = Accounting
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('CreateJobObjectW', [w.LPVOID, w.LPCWSTR], w.HANDLE),
            ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
            ('TerminateJobObject', [w.HANDLE, w.UINT], w.BOOL),
            ('QueryInformationJobObject', [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID], w.BOOL),
            ('OpenProcess', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            ('WaitForSingleObject', [w.HANDLE, w.DWORD], w.DWORD),
            ('CloseHandle', [w.HANDLE], w.BOOL),
        ):
            fn = getattr(self.api, name); fn.argtypes = args; fn.restype = result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process):
        import ctypes
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        import ctypes
        from ctypes import wintypes as w
        handles = []
        try:
            capacity = 16
            while True:
                class ProcessList(ctypes.Structure):
                    _fields_ = [('assigned', w.DWORD), ('count', w.DWORD), ('pids', ctypes.c_size_t * capacity)]
                members = ProcessList()
                if self.api.QueryInformationJobObject(self.handle, 3, ctypes.byref(members), ctypes.sizeof(members), None):
                    break
                error = ctypes.get_last_error()
                if error != 234:  # ERROR_MORE_DATA
                    raise ctypes.WinError(error)
                capacity = max(capacity * 2, members.assigned)
            for pid in members.pids[:members.count]:
                handle = self.api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
                if handle:
                    handles.append(handle)
            if not self.api.TerminateJobObject(self.handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            # TerminateJobObject is asynchronous. The root can exit before a
            # Torch/Node descendant releases its log file and model handles.
            deadline = time.monotonic() + 30
            while True:
                state = self.accounting_type()
                if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(state), ctypes.sizeof(state), None):
                    raise ctypes.WinError(ctypes.get_last_error())
                if state.active == 0:
                    break
                if time.monotonic() >= deadline:
                    raise OSError('停止计算进程超时，请关闭程序后重新启动。')
                time.sleep(.02)
            # Job accounting reaches zero before Windows finishes process
            # teardown. Wait on each process handle before removing files.
            for handle in handles:
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                if self.api.WaitForSingleObject(handle, remaining) != 0:
                    raise OSError('等待计算进程释放文件超时，请关闭程序后重新启动。')
        finally:
            for handle in handles:
                self.api.CloseHandle(handle)
            self.api.CloseHandle(self.handle)


def run_managed(command, log, timeout, control, gate):
    control.check()
    job = WindowsJob() if os.name == 'nt' else None
    process = None
    try:
        process = subprocess.Popen(command, stdout=log, stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            start_new_session=os.name != 'nt')
        # Worker waits at this gate until its descendants are contained.
        if job:
            job.assign(process)
        control.check()
        gate.touch()
        deadline = time.monotonic() + timeout
        while True:
            control.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                code = process.wait(timeout=min(.1, remaining))
                control.check()
                return subprocess.CompletedProcess(command, code)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if job:
            job.close()
        if process:
            if os.name != 'nt':
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            if process.poll() is None:
                process.kill()
            process.wait()
