"""Failed saves must not leave a partial new result or erase an older file."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import convert, save_svg_result
from test_app import sample


class ResultFilesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.svg = self.folder / 'result.svg'
        self.report = self.svg.with_suffix('.pipeline.json')

    def test_existing_svg_is_never_overwritten_or_removed(self):
        self.svg.write_bytes(b'old svg')
        self.report.write_bytes(b'old report')
        with self.assertRaises(FileExistsError):
            save_svg_result(self.svg, b'new svg', {'stage': 'new'})
        self.assertEqual(self.svg.read_bytes(), b'old svg')
        self.assertEqual(self.report.read_bytes(), b'old report')

    def test_existing_report_kept_and_new_svg_rolled_back(self):
        self.report.write_bytes(b'old report')
        with self.assertRaises(FileExistsError):
            save_svg_result(self.svg, b'new svg', {'stage': 'new'})
        self.assertFalse(self.svg.exists())
        self.assertEqual(self.report.read_bytes(), b'old report')

    def test_partial_report_failure_removes_both_new_files(self):
        with self.assertRaises(TypeError):
            save_svg_result(self.svg, b'new svg', {'valid': 1, 'invalid': object()})
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_conversion_report_failure_leaves_no_saved_svg(self):
        def traced(command, **kwargs):
            job = json.loads(Path(command[-1]).read_text(encoding='utf-8'))
            output = Path(job['output'])
            output.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="96" height="64">'
                              '<path d="M0 0L96 0L96 64Z" fill="#fff"/></svg>', encoding='utf-8')
            (output.parent / 'pipeline_report.json').write_text(
                json.dumps({'config': job['config'], 'stages': []}), encoding='utf-8')
            return subprocess.CompletedProcess(command, 0)

        real_open = Path.open
        def fail_report(path, *args, **kwargs):
            if path.parent == self.folder and path.name.endswith('.pipeline.json'):
                raise OSError('report save failed')
            return real_open(path, *args, **kwargs)

        with patch('core.subprocess.run', side_effect=traced), patch.object(Path, 'open', fail_report):
            with self.assertRaisesRegex(OSError, 'report save failed'):
                convert(sample(), 'test.png', {'output_directory': str(self.folder)})
        self.assertEqual(list(self.folder.iterdir()), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
