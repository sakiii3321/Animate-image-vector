"""Reproduce actual Windows destination locks during progress publication."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from status_io import write_json_atomic


@unittest.skipUnless(os.name == 'nt', 'Windows file-sharing regression')
class StatusSharingTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.folder = Path(self.work.name)
        self.status = self.folder / 'job.status.json'
        write_json_atomic(self.status, {'stage': 'previous'})

    def test_locked_progress_is_optional_but_results_are_required(self):
        with self.status.open('rb'):
            # Demonstrate the original failing operation with a real file lock.
            pending = self.folder / 'old.status.tmp'
            pending.write_text('{}')
            with self.assertRaises(PermissionError):
                pending.replace(self.status)
            self.assertFalse(write_json_atomic(self.status, {'stage': 'next'}, optional=True))
            self.assertEqual(json.loads(self.status.read_text()), {'stage': 'previous'})
            with self.assertRaises(PermissionError):
                write_json_atomic(self.status, {'required': 'result'})
        self.assertTrue(write_json_atomic(self.status, {'stage': 'complete'}, optional=True))
        self.assertEqual(json.loads(self.status.read_text()), {'stage': 'complete'})

    def test_retry_recovers_after_reader_releases_handle(self):
        handle = self.status.open('rb')
        timer = threading.Timer(.04, handle.close)
        timer.start()
        try:
            self.assertTrue(write_json_atomic(self.status, {'stage': 'next'}))
        finally:
            timer.join()
            handle.close()
        self.assertEqual(json.loads(self.status.read_text()), {'stage': 'next'})

    def run_conversion_worker(self, config):
        source = self.folder / 'input.png'
        Image.new('RGB', (24, 16), '#367bc1').save(source)
        output = self.folder / 'out.svg'
        job = self.folder / 'job.json'
        job.write_text(json.dumps({'input': str(source), 'output': str(output), 'config': config}))
        with self.status.open('rb'):
            process = subprocess.run([sys.executable, '-u', str(ROOT / 'app/main.py'), '--worker', str(job)],
                                     capture_output=True, encoding='utf-8', errors='replace', timeout=30,
                                     env={**os.environ, 'PYTHONUTF8': '1'}, creationflags=subprocess.CREATE_NO_WINDOW)
        return process, output

    def test_real_conversion_completes_with_locked_progress(self):
        process, output = self.run_conversion_worker({})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn('<svg', output.read_text())

    def test_locked_progress_does_not_mask_original_failure(self):
        process, output = self.run_conversion_worker({'not_a_parameter': 1})
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('not_a_parameter', process.stderr)
        self.assertNotIn('PermissionError', process.stderr)
        self.assertFalse(output.exists())

    def test_enhancement_worker_completes_with_locked_progress(self):
        from enhancement_runtime import runtime_settings, _environment
        source = self.folder / 'empty.svg'
        source.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>')
        target = self.folder / 'target.png'
        Image.new('RGBA', (8, 8)).save(target)
        output = self.folder / 'enhanced.svg'
        result = self.folder / 'result.json'
        job = self.folder / 'enhance.json'
        job.write_text(json.dumps({'action': 'optimize', 'input': str(source), 'target': str(target),
                                   'output': str(output), 'status': str(self.status), 'result': str(result),
                                   'width': 8, 'height': 8, 'config': {'diffvg_optimize': True, 'diffvg_iterations': 1}}))
        with self.status.open('rb'):
            process = subprocess.run([runtime_settings()['python'], '-u', str(ROOT / 'app/enhance_worker.py'), str(job)],
                                     capture_output=True, encoding='utf-8', errors='replace', timeout=60,
                                     env=_environment(), creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(output.exists())
        self.assertEqual(json.loads(result.read_text())['skipped'], 'empty_or_invisible_svg')


if __name__ == '__main__':
    unittest.main(verbosity=2)
