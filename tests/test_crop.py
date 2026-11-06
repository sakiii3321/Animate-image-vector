import io
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import convert, crop_box, cropped_detail_region, normalize_image, validate, parse_crop_rect


class CropTests(unittest.TestCase):
    def test_exact_ratios_and_edges(self):
        for ratio, expected in [('16:9', (96, 54)), ('9:16', (36,64)), ('4:3',(84,63)), ('3:4', (48, 64)),
                                ('1:1', (64, 64)), ('2.35：1', (94, 40))]:
            with self.subTest(ratio=ratio):
                box = crop_box((96, 64), validate({'crop_ratio':ratio, 'crop_x':100, 'crop_y':0}))
                self.assertEqual(box, (96-expected[0], 0, 96, expected[1]))
        self.assertIsNone(crop_box((96, 64), validate({})))
        for ratio in ['0:1', '16:0', '-1:4', '1:2:3', None, 1]:
            with self.subTest(ratio=ratio), self.assertRaises(ValueError):
                validate({'crop_ratio':ratio})
        with self.assertRaisesRegex(ValueError, '整数像素'):
            crop_box((8, 8), validate({'crop_ratio':'16:9'}))

    def test_exact_rectangle_precedes_legacy_ratio_and_position(self):
        config=validate({'crop_rect':' 7, 11, 31, 23 ', 'crop_ratio':'16:9', 'crop_x':100, 'crop_y':100})
        self.assertEqual(crop_box((96,64),config),(7,11,38,34))
        self.assertIsNone(parse_crop_rect(''))
        self.assertIsNone(parse_crop_rect('  '))
        self.assertEqual(crop_box((96,64),validate({'crop_rect':'0,0,96,64'})),(0,0,96,64))
        self.assertEqual(crop_box((96,64),validate({'crop_rect':'','crop_ratio':'1:1'})),(16,0,80,64))

    def test_exact_rectangle_rejects_invalid_format_and_bounds(self):
        for value in (None,False,3,[],{},'1,2,3','1,2,3,4,5','-1,0,2,2','1.5,0,2,2','0,0,0,2','0,0,2,0','0,0,40000001,2'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate({'crop_rect':value})
        for rect in ('90,0,7,64','0,60,20,5','96,0,1,1'):
            with self.subTest(rect=rect),self.assertRaisesRegex(ValueError,'超出'):
                crop_box((96,64),validate({'crop_rect':rect}))

    def test_exact_rectangle_uses_exif_normalized_coordinates(self):
        image=Image.new('RGBA',(6,4))
        image.putdata([(x*40,y*60,100,(x+y)*25) for y in range(4) for x in range(6)])
        exif=Image.Exif();exif[274]=6
        encoded=io.BytesIO();image.save(encoded,'PNG',exif=exif)
        expected=image.transpose(Image.Transpose.ROTATE_270).crop((1,2,4,4))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input.png'
            size,box=normalize_image(encoded.getvalue(),path,validate({'crop_rect':'1,2,3,2'}))
            self.assertEqual((size,box),((4,6),(1,2,4,4)))
            with Image.open(path) as actual:self.assertEqual(actual.tobytes(),expected.tobytes())

    def test_exact_rectangle_real_conversion_reports_same_canvas(self):
        image=Image.new('RGBA',(96,64),(25,65,105,255));image.paste((230,180,90,255),(18,10,44,42))
        encoded=io.BytesIO();image.save(encoded,'PNG')
        with tempfile.TemporaryDirectory() as folder:
            result=convert(encoded.getvalue(),'exact-crop.png',{
                'illustration_profile':'edge_clean','crop_rect':'11,7,41,35',
                'crop_ratio':'9:16','output_directory':folder,'path_limit':40})
            root=ET.fromstring(result['svg'])
            self.assertEqual((float(root.get('width')),float(root.get('height'))),(41,35))
            self.assertEqual(tuple(result['pipeline']['crop_box']),(11,7,52,42))
            self.assertEqual(result['pipeline']['config']['crop_rect'],'11,7,41,35')
            with Image.open(io.BytesIO(result['original'])) as actual:
                self.assertEqual(actual.tobytes(),image.crop((11,7,52,42)).tobytes())

    def test_crop_after_exif_rotation_preserves_pixels_and_alpha(self):
        image = Image.new('RGBA', (6, 4))
        image.putdata([(x*40, y*60, 100, (x+y)*25) for y in range(4) for x in range(6)])
        exif = Image.Exif()
        exif[274] = 6
        encoded = io.BytesIO()
        image.save(encoded, 'PNG', exif=exif)
        expected = image.transpose(Image.Transpose.ROTATE_270).crop((0, 2, 4, 6))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.png'
            size, box = normalize_image(encoded.getvalue(), path, validate({'crop_ratio':'1:1', 'crop_y':100}))
            self.assertEqual((size, box), ((4, 6), (0, 2, 4, 6)))
            with Image.open(path) as actual:
                self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_original_roi_and_export_canvas(self):
        box = (32, 0, 96, 64)
        self.assertEqual(cropped_detail_region('28,10,10,12', (96, 64), box), '0,10,6,12')
        with self.assertRaisesRegex(ValueError, '裁剪框外'):
            cropped_detail_region('2,2,10,10', (96, 64), box)
        image = Image.new('RGB', (96, 64), '#227799')
        image.paste('#f0a140', (68, 8, 88, 48))
        data = io.BytesIO()
        image.save(data, 'PNG')
        with tempfile.TemporaryDirectory() as folder:
            for profile in ('legacy', 'edge_clean'):
                with self.subTest(profile=profile):
                    config = {'engine':'potrace', 'illustration_profile':profile,
                              'crop_ratio':'1:1', 'crop_x':100, 'output_directory':folder,
                              'detail_region':'28,10,10,12', 'curve_simplify':True}
                    result = convert(data.getvalue(), 'test.png', config)
                    svg = ET.fromstring(Path(result['path']).read_bytes())
                    self.assertEqual((float(svg.get('width')), float(svg.get('height'))), (64, 64))
                    with Image.open(io.BytesIO(result['original'])) as preview:
                        self.assertEqual(preview.tobytes(), image.convert('RGBA').crop(box).tobytes())
                    self.assertEqual(tuple(result['pipeline']['crop_box']), box)
                    self.assertEqual(result['pipeline']['config']['detail_region'], config['detail_region'])
