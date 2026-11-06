import base64
import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import convert, validate
from task_control import TaskControl, ConversionCancelled, run_managed
from main import AppServer
from PIL import Image, ImageDraw


def stripes(disconnected=False):
    image = Image.new('RGBA', (120, 60), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for i, color in enumerate(['red', 'orange', 'yellow', 'green', 'blue', 'purple']):
        draw.rectangle((i*20, 0, i*20+(14 if disconnected else 19), 59), fill=color)
    stream = io.BytesIO(); image.save(stream, 'PNG'); return stream.getvalue()


class SimplifyTests(unittest.TestCase):
    def test_count_reduction_and_zero_and_skip(self):
        for target in (0, 3, 10):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                config = {'engine':'potrace', 'path_limit':12, 'potrace_palette_colors':6,
                    'potrace_smoothing':0, 'potrace_min_region_area':0,
                    'curve_simplify':True, 'simplify_target_paths':target, 'output_directory':directory}
                result = convert(stripes(), 'stripes.png', config)
                stages = result['pipeline']['stages']
                self.assertEqual(stages[0]['counts']['fill_paths'], 6)
                self.assertEqual(result['stats']['paths'], 3 if target == 3 else 6)
                self.assertNotIn(b'<image', result['svg'])
                if target:
                    report = next(s['report'] for s in stages if s['stage']=='region_simplify')
                    self.assertEqual(report['skipped'], target==10)

    def test_disconnected_islands_cannot_be_packed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, '透明背景隔开的区域'):
                convert(stripes(True), 'islands.png', {'engine':'potrace', 'path_limit':12,
                    'potrace_palette_colors':6, 'potrace_smoothing':0, 'potrace_min_region_area':0,
                    'curve_simplify':True, 'simplify_target_paths':3, 'output_directory':directory})
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_validation(self):
        for value in (-1, 20001, 1.5, True):
            with self.assertRaises(ValueError): validate({'simplify_target_paths':value})

    @unittest.skipUnless(os.environ.get('IMAGEVECTOR_RUN_ENHANCEMENT_TESTS')=='1', 'Real SR/DiffVG integration')
    def test_target_with_sr_and_diffvg(self):
        with tempfile.TemporaryDirectory() as directory:
            result=convert(stripes(), 'enhanced.png', {'engine':'potrace','path_limit':12,
                'potrace_palette_colors':6,'potrace_smoothing':0,'potrace_min_region_area':0,
                'curve_simplify':True,'simplify_target_paths':3,'sr_enabled':True,'sr_scale':2,
                'diffvg_optimize':True,'diffvg_iterations':1,'highres_refine':True,'output_directory':directory},
                control=TaskControl())
            self.assertEqual(result['stats']['paths'],3)
            self.assertEqual(result['pipeline']['target_size'],[240,120])
            self.assertEqual([s['stage'] for s in result['pipeline']['stages']],
                ['super_resolution','vectorize','region_simplify','curve_simplify','optimization'])


class CancelTests(unittest.TestCase):
    def test_save_boundary(self):
        control=TaskControl();control.cancel()
        with self.assertRaises(ConversionCancelled):control.begin_save()
        control=TaskControl();control.begin_save();self.assertFalse(control.cancel())

    @unittest.skipUnless(os.name=='nt', 'Windows process-tree containment')
    def test_actual_child_tree_cancel_and_timeout(self):
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];api.OpenProcess.restype=ctypes.c_void_p
        api.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        api.CloseHandle.argtypes=[ctypes.c_void_p]
        for cancel in (True, False):
            with self.subTest(cancel=cancel), tempfile.TemporaryDirectory() as directory:
                directory=Path(directory);gate=directory/'start';pidfile=directory/'pid'
                script=directory/'helper.py'
                script.write_text('import subprocess,sys,time\nfrom pathlib import Path\n'
                    'while not Path(sys.argv[1]).exists(): time.sleep(.02)\n'
                    'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(300)"])\n'
                    'Path(sys.argv[2]).write_text(str(child.pid))\n'
                    'time.sleep(300)\n')
                control=TaskControl();errors=[]
                with (directory/'log').open('wb') as log:
                    def run():
                        try:run_managed([sys.executable,str(script),str(gate),str(pidfile)],log,10 if cancel else 1,control,gate)
                        except Exception as error:errors.append(error)
                    thread=threading.Thread(target=run);thread.start()
                    deadline=time.monotonic()+5
                    while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.02)
                    self.assertTrue(pidfile.exists())
                    handle=api.OpenProcess(0x00100000,False,int(pidfile.read_text()))
                    self.assertTrue(handle)
                    try:
                        if cancel:self.assertTrue(control.cancel())
                        thread.join(10);self.assertFalse(thread.is_alive())
                        self.assertEqual(api.WaitForSingleObject(handle,5000),0,'grandchild survived cancellation')
                        self.assertIsInstance(errors[0],ConversionCancelled if cancel else subprocess.TimeoutExpired)
                    finally:api.CloseHandle(handle)

    def test_http_cancel_and_restart(self):
        server=AppServer();thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path, data=None):
            headers={'X-App-Token':server.token,'Origin':server.origin,'Content-Type':'application/json'}
            with urllib.request.urlopen(urllib.request.Request(server.origin+path,data=data,headers=headers),timeout=40) as response:
                return json.load(response)
        try:
            with tempfile.TemporaryDirectory() as directory:
                config={'engine':'potrace','path_limit':12,'diffvg_optimize':True,'diffvg_iterations':100,'output_directory':directory}
                body=json.dumps({'name':'cancel.png','image':base64.b64encode(stripes()).decode(),'config':config}).encode()
                results=[];errors=[]
                def run():
                    try:results.append(request('/api/convert',body))
                    except Exception as error:errors.append(error)
                worker=threading.Thread(target=run);worker.start()
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    state=request('/api/progress')
                    if state['running']:break
                    time.sleep(.02)
                self.assertTrue(request('/api/cancel',b'')['accepted'])
                worker.join(15);self.assertFalse(worker.is_alive());self.assertFalse(errors,errors)
                self.assertEqual(results,[{'cancelled':True}])
                self.assertEqual(request('/api/progress'),{'running':False,'stage':'cancelled'})
                self.assertEqual(list(Path(directory).iterdir()),[])
                self.assertFalse(request('/api/cancel',b'')['accepted'])
                body=json.dumps({'name':'restart.png','image':base64.b64encode(stripes()).decode(),'config':{'output_directory':directory}}).encode()
                result=request('/api/convert',body);self.assertTrue(Path(result['path']).is_file())
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main(verbosity=2)
