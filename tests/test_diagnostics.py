import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import base64
import threading
import urllib.request
import urllib.error
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import convert, self_test, worker_failure, sanitized_detail
from PIL import Image
from main import AppServer


def sample():
    image = Image.new('RGB', (16, 12), 'red')
    out = io.BytesIO(); image.save(out, 'PNG'); return out.getvalue()


class DiagnosticsTests(unittest.TestCase):
    def test_stale_progress_detail_does_not_mask_worker_error(self):
        def failed_worker(command, **kwargs):
            job = Path(command[-1])
            job.with_suffix('.status.json').write_text(json.dumps({'stage':'sr_inference', 'detail':'previous progress notice'}), encoding='utf-8')
            kwargs['stderr'].write(b'ValueError: actual conversion failure')
            return subprocess.CompletedProcess(command, 1)
        with patch('core.subprocess.run', side_effect=failed_worker):
            with self.assertRaises(ValueError) as raised:
                convert(sample(), 'error.png', {})
        self.assertIn('actual conversion failure', str(raised.exception))
        self.assertNotIn('previous progress notice', str(raised.exception))

    def test_native_exit_empty_log(self):
        with patch('core.subprocess.run', return_value=subprocess.CompletedProcess([], 3221225477)):
            with self.assertRaises(ValueError) as raised:
                convert(sample(), 'a.png', {})
        message = str(raised.exception)
        self.assertIn('0xC0000005', message)
        self.assertIn('worker_not_started', message)
        self.assertIn('没有输出错误文本', message)
        self.assertNotIn('potrace_palette_colors', message)

    def test_missing_svg_success(self):
        with patch('core.subprocess.run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(ValueError, '未生成 SVG'):
                convert(sample(), 'a.png', {})

    def test_timeout(self):
        for config,timeout in [({},2700),({'engine':'potrace'},1200),
                               ({'illustration_profile':'legacy','sr_enabled':True},10800)]:
            with self.subTest(config=config),patch('core.subprocess.run', side_effect=subprocess.TimeoutExpired([], timeout)) as run:
                with self.assertRaisesRegex(ValueError, f'{timeout} 秒'):
                    convert(sample(), 'a.png', config)
                self.assertEqual(run.call_args.kwargs['timeout'],timeout)

    def test_launch_failure(self):
        with patch('core.subprocess.run', side_effect=OSError('blocked')):
            with self.assertRaisesRegex(ValueError, '无法启动'):
                convert(sample(), 'a.png', {})

    def test_import_failure(self):
        message = worker_failure(1, 'ImportError: DLL load failed', {'stage':'error','kind':'ImportError'})
        self.assertIn('依赖加载失败', message)
        self.assertIn('0x00000001', message)

    def test_signed_exit(self):
        self.assertIn('0xC0000005', worker_failure(-1073741819, '', {}))

    def test_redaction(self):
        self.assertNotIn('Alice', sanitized_detail('File "C:\\Users\\Alice\\app.py", line 3'))
        self.assertNotIn(str(Path.home()), sanitized_detail(str(Path.home())+'/secret'))

    def test_selftest(self):
        result = self_test()
        self.assertTrue(result['ok'], result)
        self.assertEqual(len(result['checks']), 4)
        self.assertEqual({check['profile'] for check in result['checks']},
                         {'legacy','edge_clean','flat_layers','gradient_layers'})
        self.assertNotIn('vtracer',result['runtime']['packages'])

    def test_http_diagnostics_and_normalized_preview(self):
        server = AppServer()
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def request(path, body=None, authorized=True):
            headers = {'Origin':server.origin, 'Content-Type':'application/json'}
            if authorized:
                headers['X-App-Token'] = server.token
            req = urllib.request.Request(server.origin+path, data=body, headers=headers)
            return urllib.request.urlopen(req, timeout=30)
        try:
            with self.assertRaises(urllib.error.HTTPError):
                request('/api/self-test', b'{}', authorized=False)
            with request('/api/self-test', b'{}') as response:
                self.assertTrue(json.load(response)['ok'])
            with request('/api/diagnostics') as response:
                self.assertIn('python', json.load(response))
            with tempfile.TemporaryDirectory() as directory:
                payload = json.dumps({'name':'a.png','image':base64.b64encode(sample()).decode(),
                                      'config':{'output_directory':directory}}).encode()
                with request('/api/convert', payload) as response:
                    result = json.load(response)
                    self.assertEqual((result['width'],result['height']), (16,12))
                with request('/api/original') as response:
                    self.assertEqual(response.headers['Content-Type'], 'image/png')
                    self.assertTrue(response.read().startswith(b'\x89PNG'))
                with self.assertRaises(urllib.error.HTTPError):
                    request('/api/original', authorized=False)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_original_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            result = convert(sample(), 'a.png', {'output_directory':directory})
            self.assertEqual((result['width'],result['height']), (16,12))
            with Image.open(io.BytesIO(result['original'])) as original:
                self.assertEqual(original.size, (16,12))

if __name__ == '__main__': unittest.main(verbosity=2)
