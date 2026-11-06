import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import enhancement_runtime as runtime
from PIL import Image, ImageDraw, ImageChops


class EnhancementRuntimeTests(unittest.TestCase):
    def test_real_probe_and_sr_2x_4x_preserve_alpha(self):
        capability = runtime.runtime_capabilities(refresh=True)
        if not capability['sr']['available']:
            self.skipTest('Optional enhancement environment not configured: ' + capability['sr']['reason'])
        self.assertTrue(capability['diffvg']['available'], capability['diffvg'])
        self.assertEqual(capability['diffvg']['device'], 'CPU')
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source = Image.new('RGBA', (24, 20), (30, 90, 180, 0))
            draw = ImageDraw.Draw(source)
            draw.rectangle((6, 0, 13, 19), fill=(215, 110, 40, 128))
            draw.ellipse((11, 2, 23, 18), fill=(15, 170, 90, 255))
            source.save(work / 'input.png')
            for scale in (2, 4):
                with self.subTest(scale=scale):
                    output = work / f'output{scale}.png'
                    events = []
                    result = runtime.run_backend('super_resolution',
                        {'input': str(work/'input.png'), 'output': str(output), 'config': {'sr_scale': scale}},
                        work, lambda stage, **kw: events.append((stage, kw)))
                    image = Image.open(output)
                    self.assertEqual(image.size, (24*scale, 20*scale))
                    self.assertEqual(image.mode, 'RGBA')
                    expected = source.getchannel('A').resize(image.size, Image.Resampling.LANCZOS)
                    self.assertIsNone(ImageChops.difference(image.getchannel('A'), expected).getbbox())
                    self.assertIsNotNone(ImageChops.difference(image.convert('RGB'), source.convert('RGB').resize(image.size, Image.Resampling.BICUBIC)).getbbox())
                    self.assertEqual(result['model'], 'Real-ESRGAN AnimeVideo-v3')
                    self.assertEqual(result['scale'], scale)
                    self.assertTrue(any(stage == 'sr_start' for stage, _ in events))
                    self.assertEqual(events[-1][0], 'enhancement_complete')
                    print('REAL_SR', json.dumps(result, ensure_ascii=False))

    def test_missing_runtime_reports_unavailable(self):
        with patch.dict(os.environ, {'IMAGEVECTOR_ENHANCEMENT_PYTHON': str(ROOT/'runtime/no-such-enhancement-python.exe')}):
            capability = runtime.runtime_capabilities(refresh=True)
            self.assertFalse(capability['sr']['available'])
            self.assertFalse(capability['diffvg']['available'])
            self.assertIn('解释器不存在', capability['sr']['reason'])

    def test_corrupt_configuration_reports_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)/'config.json';config.write_text('broken', encoding='utf-8')
            with patch.object(runtime, 'CONFIG', config):
                capability = runtime.runtime_capabilities(refresh=True)
                self.assertFalse(capability['sr']['available'])
                self.assertIn('配置不可读', capability['sr']['reason'])

    def test_unknown_action_does_not_start_process(self):
        with patch.object(runtime.subprocess, 'Popen') as start:
            with self.assertRaises(ValueError):
                runtime.run_backend('unknown', {}, ROOT, lambda *a, **kw: None)
            start.assert_not_called()

    def test_worker_failure_is_not_silently_replaced(self):
        capability = runtime.runtime_capabilities()
        if not capability['sr']['available']:
            self.skipTest('Optional enhancement environment not configured')
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory);source = work/'input.png';output = work/'bad.png'
            Image.new('RGB', (4, 4), 'red').save(source)
            with self.assertRaisesRegex(RuntimeError, '倍数必须为 2 或 4'):
                runtime.run_backend('super_resolution', {'input':str(source), 'output':str(output),
                    'config':{'sr_scale':3}}, work, lambda *a, **kw:None)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
