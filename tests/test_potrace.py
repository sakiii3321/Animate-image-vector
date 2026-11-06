import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import convert, validate
from PIL import Image, ImageDraw


def png(image):
    stream = io.BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


class PotraceTests(unittest.TestCase):
    def test_validation_and_legacy(self):
        self.assertEqual(validate({'engine':'potrace'})['illustration_profile'], 'legacy')
        for config in [{'engine':'bad'}, {'path_limit':0}, {'path_limit':20001},
                       {'path_limit':1.5}, {'path_limit':True}, {'detail_region':1},
                       {'detail_region':'1,2,0,4'}, {'detail_region':'-1,2,3,4'}]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate(config)

    def test_real_budgeted_color_curves(self):
        image = Image.new('RGB', (96, 80), '#e8ece5')
        draw = ImageDraw.Draw(image)
        draw.ellipse((8, 8, 70, 65), fill='#21549b')
        draw.ellipse((25, 16, 49, 55), fill='#ffcc22')
        draw.rectangle((70, 10, 90, 40), fill='#cc3377')
        counts = []
        with tempfile.TemporaryDirectory() as directory:
            for budget in (1, 3, 20):
                with self.subTest(budget=budget):
                    result = convert(png(image), '色块.png', {'engine':'potrace', 'path_limit':budget,
                                     'detail_region':'8,8,62,57', 'output_directory':directory})
                    root = ET.fromstring(result['svg'])
                    paths = list(root.iter('{http://www.w3.org/2000/svg}path'))
                    self.assertGreater(len(paths), 0)
                    self.assertLessEqual(len(paths), budget)
                    self.assertEqual(result['stats']['paths'], len(paths))
                    self.assertFalse(list(root.iter('{http://www.w3.org/2000/svg}image')))
                    self.assertEqual(root.get('viewBox'), '0 0 96 80')
                    self.assertEqual(Path(result['path']).read_bytes(), result['svg'])
                    if budget > 1:
                        self.assertIn('C', ''.join(p.get('d', '') for p in paths))
                    counts.append(len(paths))
            self.assertGreater(counts[-1], counts[0])

    def test_transparency_and_impossible_islands(self):
        image = Image.new('RGBA', (40, 20), (0, 0, 0, 0))
        d = ImageDraw.Draw(image)
        d.rectangle((2, 2, 9, 12), fill=(255, 0, 0, 128))
        d.rectangle((25, 2, 32, 12), fill=(0, 0, 255, 255))
        with tempfile.TemporaryDirectory() as directory:
            cfg = {'engine':'potrace', 'path_limit':2, 'output_directory':directory}
            result = convert(png(image), 'alpha.png', cfg)
            self.assertEqual(result['stats']['paths'], 2)
            root = ET.fromstring(result['svg'])
            opacity = [float(g.get('opacity')) for g in root.iter('{http://www.w3.org/2000/svg}g')]
            self.assertTrue(any(abs(a-128/255) < 0.0001 for a in opacity))
            with self.assertRaisesRegex(ValueError, '透明背景分开'):
                convert(png(image), 'islands.png', {**cfg, 'path_limit':1})
            empty = convert(png(Image.new('RGBA', (8, 8))), 'empty.png', cfg)
            self.assertEqual(empty['stats']['paths'], 0)

    def test_outside_detail_region(self):
        with self.assertRaisesRegex(ValueError, '超出规范化后图片范围'):
            convert(png(Image.new('RGB', (8, 8))), 'small.png',
                    {'engine':'potrace', 'detail_region':'4,4,8,8'})

    def test_reject_actual_over_budget_output_before_saving(self):
        def fake_worker(command, **kwargs):
            job = json.loads(Path(command[-1]).read_text(encoding='utf-8'))
            Path(job['output']).write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0Z"/><path d="M1 1Z"/></svg>')
            return subprocess.CompletedProcess(command, 0)
        with tempfile.TemporaryDirectory() as directory, patch('core.subprocess.run', side_effect=fake_worker):
            with self.assertRaisesRegex(ValueError, '超过填充路径数量上限'):
                convert(png(Image.new('RGB', (8, 8))), 'bad.png',
                        {'engine':'potrace', 'path_limit':1, 'output_directory':directory})
            self.assertFalse(list(Path(directory).glob('*.svg')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
