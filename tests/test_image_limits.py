"""Large ordinary inputs and pre-decode limits for the SR pipeline."""
import io
import struct
import sys
import tempfile
import unittest
import warnings
import zlib
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import convert, normalize_image


def png_header(width, height):
    # Pillow can inspect these real PNG dimensions without decoding the body.
    # An over-budget image must be rejected before reaching the absent pixels.
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', b'') + chunk(b'IEND', b'')


class ImageLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Image.new('RGB', (4320, 4320), '#356789') as image:
            data = io.BytesIO()
            image.save(data, 'PNG')
            cls.source = data.getvalue()

    def test_reported_18662400_pixels_preserved_and_converted(self):
        with tempfile.TemporaryDirectory() as directory:
            result = convert(self.source, 'large.png', {'output_directory': directory})
            self.assertEqual((result['width'], result['height']), (4320, 4320))
            self.assertGreater(result['stats']['paths'], 0)
            self.assertTrue(Path(result['path']).exists())

    def test_warning_is_not_misreported_as_an_attack(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Image, 'MAX_IMAGE_PIXELS', 16_000_000):
            with warnings.catch_warnings(record=True) as emitted:
                warnings.simplefilter('always')
                normalize_image(self.source, Path(directory) / 'image.png')
            self.assertFalse(any(isinstance(w.message, Image.DecompressionBombWarning) for w in emitted))
            self.assertEqual(Image.MAX_IMAGE_PIXELS, 16_000_000)

    def test_input_budget_and_pillow_hard_limit_report_in_chinese(self):
        with tempfile.TemporaryDirectory() as directory:
            for dimensions in ((6400, 6251), (100000, 100000)):
                with self.subTest(dimensions=dimensions), self.assertRaisesRegex(ValueError, '4000 万输入像素'):
                    normalize_image(png_header(*dimensions), Path(directory) / 'oversize.png')
            self.assertFalse((Path(directory) / 'oversize.png').exists())

    def test_sr4_rejects_output_budget_before_starting_worker(self):
        with patch('core.subprocess.run') as worker, self.assertRaisesRegex(ValueError, '超分辨率输出超过 1.6 亿像素'):
            convert(self.source, 'large.png', {'sr_enabled': True, 'sr_scale': 4})
        worker.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
