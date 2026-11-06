"""Process bridge to the optional, configured Python 3.12 enhancement runtime."""
import copy
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'runtime' / 'enhancement'
CONFIG = RUNTIME / 'config.json'
MAX_SR_PIXELS = 160_000_000
_cache = None
_cache_key = None
_cache_time = 0.0
_cache_lock = threading.Lock()


def runtime_settings():
    try:
        config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise RuntimeError('增强运行时配置不可读，请检查 runtime/enhancement/config.json。') from error
    python = os.environ.get('IMAGEVECTOR_ENHANCEMENT_PYTHON') or config.get('python', '')
    if not isinstance(python, str) or not python:
        raise RuntimeError('未配置增强功能使用的 Python 3.12 解释器。')
    python = Path(python)
    if not python.is_absolute():
        python = ROOT / python
    if not python.is_file():
        raise RuntimeError('增强功能的 Python 解释器不存在。请配置 runtime/enhancement/config.json 或 IMAGEVECTOR_ENHANCEMENT_PYTHON。')
    return {'python': str(python.resolve()), 'runtime': str(RUNTIME),
            'portable': bool(config.get('portable', False)), 'config': str(CONFIG)}


def _environment():
    env = os.environ.copy()
    env['PYTHONNOUSERSITE'] = '1'
    env['PYTHONUTF8'] = '1'
    env['OMP_NUM_THREADS'] = '4'
    env['OPENBLAS_NUM_THREADS'] = '4'
    return env


def runtime_capabilities(refresh=False):
    """Probe real imports/model loading, caching for a short UI polling interval."""
    global _cache, _cache_key, _cache_time
    key = (os.environ.get('IMAGEVECTOR_ENHANCEMENT_PYTHON'),
           CONFIG.stat().st_mtime_ns if CONFIG.exists() else None)
    with _cache_lock:
        if not refresh and _cache is not None and key == _cache_key and time.monotonic() - _cache_time < 120:
            return copy.deepcopy(_cache)
        try:
            settings = runtime_settings()
            result = subprocess.run([settings['python'], '-u', str(Path(__file__).with_name('enhance_worker.py')), '--probe'],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    timeout=60, env=_environment(), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode:
                raise RuntimeError('增强运行时检查失败：' + (result.stderr.strip() or f'退出码 {result.returncode}')[-1200:])
            data = json.loads(result.stdout.strip().splitlines()[-1])
            data.update(settings)
        except Exception as error:
            reason = str(error)
            data = {'sr': {'available': False, 'reason': reason},
                    'diffvg': {'available': False, 'reason': reason},
                    'portable': False, 'config': str(CONFIG)}
        data['max_sr_pixels'] = MAX_SR_PIXELS
        _cache, _cache_key, _cache_time = data, key, time.monotonic()
        return copy.deepcopy(data)


def run_backend(action, payload, work, record):
    """Run an enhancement in a child process and forward its atomic progress."""
    if action not in ('super_resolution', 'optimize'):
        raise ValueError('未知增强处理步骤。')
    settings = runtime_settings()
    work = Path(work);work.mkdir(parents=True, exist_ok=True)
    stem = work / ('enhance-' + uuid.uuid4().hex)
    job_path = stem.with_suffix('.json')
    status_path = stem.with_suffix('.status.json')
    result_path = stem.with_suffix('.result.json')
    log_path = stem.with_suffix('.log')
    job = dict(payload)
    job.update(action=action, status=str(status_path), result=str(result_path))
    job_path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
    command = [settings['python'], '-u', '-X', 'faulthandler', str(Path(__file__).with_name('enhance_worker.py')), str(job_path)]
    deadline = time.monotonic() + (3600 if action == 'super_resolution' else 7200)
    record('sr_start' if action == 'super_resolution' else 'optimization_start')
    last_status = None
    process = None
    with log_path.open('wb') as log:
        try:
            process = subprocess.Popen(command, stdout=log, stderr=log, env=_environment(),
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            while process.poll() is None:
                if time.monotonic() > deadline:
                    process.kill();process.wait()
                    raise RuntimeError('增强处理超过最长等待时间，已终止增强子进程。')
                if status_path.exists():
                    try:
                        state = json.loads(status_path.read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        pass
                    else:
                        if state != last_status:
                            last_status = state
                            record(state.get('stage', action), **{k:v for k,v in state.items() if k != 'stage'})
                time.sleep(.2)
        except BaseException:
            if process is not None and process.poll() is None:
                process.kill();process.wait()
            raise
    if status_path.exists():
        try:
            state = json.loads(status_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        else:
            if state != last_status:
                record(state.get('stage', action), **{k:v for k,v in state.items() if k != 'stage'})
            last_status = state
    if process.returncode != 0 or not result_path.exists():
        reason = (last_status or {}).get('detail') if (last_status or {}).get('stage') == 'enhancement_error' else None
        if not reason:
            reason = log_path.read_text(encoding='utf-8', errors='replace').strip()[-1800:] or '增强子进程没有错误输出。'
        raise RuntimeError(f'增强处理失败（退出码 {process.returncode}）：{reason}')
    result = json.loads(result_path.read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise RuntimeError('增强后端未返回有效处理结果。')
    if not Path(job['output']).is_file():
        raise RuntimeError('增强后端未生成约定的输出文件。')
    return result
