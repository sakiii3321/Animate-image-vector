"""Real tracing/regional effects of the exposed Potrace controls."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from core import DEFAULTS, SCHEMA, convert, validate
from potrace_engine import convert_potrace, prepare_regions
from vector_geometry import svg_counts

NS = '{http://www.w3.org/2000/svg}'


def fixture():
    im = Image.new('RGB', (64, 48), '#e8ece5')
    d = ImageDraw.Draw(im)
    d.ellipse((6, 5, 46, 42), fill='#21549b')
    d.ellipse((16, 10, 32, 32), fill='#ffcc22')
    d.rectangle((48, 8, 60, 28), fill='#cc3377')
    return im


class PotraceParameterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def regions(self, im, *, budget=20000, roi='', scale=1, **params):
        im.save(self.folder / 'image.png')
        return prepare_regions(self.folder / 'image.png', budget, roi, lambda *a, **kw: None, scale=scale, params=params)

    def trace(self, mask, *, scale=1, alpha=255, **params):
        regions = np.asarray(mask, dtype='<u2')
        regions.tofile(self.folder / 'regions.bin')
        h, w = regions.shape
        out = self.folder / 'traced.svg'
        job = {'width': w, 'height': h, 'limit': 1, 'scale': scale, 'output': str(out),
               'trace_options': params,
               'regions': [{'id': 1, 'bbox': [0, 0, w, h], 'color': [35, 90, 160, alpha]}]}
        config = self.folder / 'trace.json'
        config.write_text(json.dumps(job), encoding='utf-8')
        subprocess.run([str(ROOT / 'runtime/node/node.exe'), str(ROOT / 'app/potrace_trace.cjs'), str(config)],
                       check=True, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return out.read_bytes(), svg_counts(out)

    def test_validation_defaults_and_potrace_scope(self):
        keys = [k for k in SCHEMA if k.startswith('potrace_')]
        self.assertEqual(len(keys), 12)
        for key in keys:
            self.assertEqual(SCHEMA[key]['engine'], 'potrace')
            self.assertEqual(validate({})[key], DEFAULTS[key])
        self.assertEqual(validate({'potrace_opt_tolerance': .05})['potrace_opt_tolerance'], .05)
        for key, spec in ((k, SCHEMA[k]) for k in keys):
            invalid = [None, 'wrong']
            if 'min' in spec:
                invalid.extend([True, spec['min'] - spec['step'], spec['max'] + spec['step']])
                if spec['step'] == 1:
                    invalid.append(spec['min'] + .5)
            elif spec.get('type') == 'boolean':
                invalid.extend([1, 0])
            for value in invalid:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate({key: value})
        with self.assertRaises(ValueError):
            validate({'potrace_opt_tolerance': .01})

    def test_default_output_is_deterministic(self):
        fixture().save(self.folder / 'source.png')
        outputs = []
        for roi in ('', '5,5,42,38'):
            convert_potrace(self.folder / 'source.png', self.folder / 'out.svg',
                            {'path_limit': 16, 'detail_region': roi}, lambda *a, **kw: None)
            outputs.append((self.folder / 'out.svg').read_bytes())
            counts = svg_counts(self.folder / 'out.svg')
            self.assertLessEqual(counts['fill_paths'], 16)
            self.assertEqual(counts['embedded_images'], 0)
        self.assertEqual(*outputs)

    def test_region_preparation_accepts_omitted_optional_params(self):
        source = self.folder / 'source.png'
        fixture().save(source)
        record = lambda *args, **kwargs: None
        labels, records = prepare_regions(source, 16, '', record)
        explicit_labels, explicit_records = prepare_regions(source, 16, '', record, params={})
        np.testing.assert_array_equal(labels, explicit_labels)
        self.assertEqual(records, explicit_records)
        self.assertGreater(len(records), 0)
        self.assertLessEqual(len(records), 16)

    def test_corner_and_curve_optimization_change_real_geometry(self):
        y, x = np.mgrid[:96, :96]
        theta = np.arctan2(y - 48, x - 48)
        mask = np.hypot(x - 48, y - 48) < 32 + 6 * np.cos(7 * theta) + 2 * np.sin(21 * theta)
        polygon, polygon_stats = self.trace(mask, potrace_alpha_max=0)
        normal, normal_stats = self.trace(mask)
        _, unmerged = self.trace(mask, potrace_opt_curve=False)
        _, loose = self.trace(mask, potrace_opt_tolerance=2)
        self.assertEqual(polygon_stats['curve_segments'], 0)
        self.assertGreater(normal_stats['curve_segments'], 0)
        self.assertNotEqual(polygon, normal)
        self.assertLessEqual(normal_stats['total_segments'], unmerged['total_segments'])
        self.assertLess(loose['total_segments'], unmerged['total_segments'])
        # Tolerance is specified in original-image pixels, then scaled for SR.
        one, _ = self.trace(mask, potrace_opt_tolerance=.4, potrace_stroke_width=0)
        two, _ = self.trace(mask, scale=2, potrace_opt_tolerance=.2, potrace_stroke_width=0)
        self.assertEqual(one, two)

    def test_turn_policy_controls_diagonal_ambiguity(self):
        mask = np.zeros((12, 12), bool)
        mask[2:6, 2:6] = True
        mask[6:10, 6:10] = True
        outputs = [self.trace(mask, potrace_turn_policy=p)[0]
                   for p in SCHEMA['potrace_turn_policy']['choices']]
        self.assertGreater(len(set(outputs)), 1)

    def test_small_contour_removal_and_stroke_scale(self):
        mask = np.zeros((12, 12), bool)
        mask[4:7, 4:7] = True
        kept, stats = self.trace(mask, potrace_turd_size=3, potrace_stroke_width=0, alpha=128)
        self.assertEqual(stats['fill_paths'], 1)
        root = ET.fromstring(kept)
        self.assertEqual(root.find('.//' + NS + 'path').get('stroke'), 'none')
        self.assertAlmostEqual(float(root[0].get('opacity')), 128 / 255, places=4)
        removed, stats = self.trace(mask, scale=2, potrace_turd_size=3)
        self.assertEqual(stats['fill_paths'], 0)
        self.assertFalse(list(ET.fromstring(removed).iter(NS + 'path')))
        stroked, _ = self.trace(mask, scale=2, potrace_stroke_width=1.5)
        self.assertEqual(ET.fromstring(stroked).find('.//' + NS + 'path').get('stroke-width'), '3')

    def test_palette_and_smoothing_change_regions(self):
        gray = np.repeat(np.arange(8, dtype=np.uint8) * 30, 8)[None, :]
        image = Image.fromarray(np.tile(gray, (16, 1))).convert('RGB')
        _, few = self.regions(image, potrace_palette_colors=2, potrace_smoothing=0, potrace_min_region_area=0)
        _, many = self.regions(image, potrace_palette_colors=8, potrace_smoothing=0, potrace_min_region_area=0)
        self.assertEqual(len(few), 2)
        self.assertEqual(len(many), 8)
        noise = np.random.default_rng(5).integers(90, 111, (32, 32), dtype=np.uint8)
        noisy = Image.fromarray(noise).convert('RGB')
        raw, _ = self.regions(noisy, potrace_palette_colors=8, potrace_smoothing=0, potrace_min_region_area=0)
        smooth, _ = self.regions(noisy, potrace_palette_colors=8, potrace_smoothing=3, potrace_min_region_area=0)
        self.assertFalse(np.array_equal(raw, smooth))

    def test_area_threshold_scaling_and_detail_weight(self):
        image = Image.new('RGB', (32, 32), 'white')
        # Only low-contrast speckles are eligible for area-based cleanup.
        ImageDraw.Draw(image).rectangle((10, 10, 12, 12), fill=(240,240,240))
        _, retained = self.regions(image, potrace_smoothing=0, potrace_min_region_area=0)
        _, merged = self.regions(image, potrace_smoothing=0, potrace_min_region_area=16)
        self.assertEqual((len(retained), len(merged)), (2, 1))
        enlarged = image.resize((64, 64), Image.Resampling.NEAREST)
        _, native = self.regions(enlarged, scale=1, potrace_smoothing=0, potrace_min_region_area=16)
        _, scaled = self.regions(enlarged, scale=2, potrace_smoothing=0, potrace_min_region_area=16)
        self.assertEqual((len(native), len(scaled)), (2, 1))
        image = Image.new('RGB', (32, 16), 'blue')
        ImageDraw.Draw(image).rectangle((0, 0, 15, 15), fill='red')
        opts = {'budget': 1, 'roi': '0,0,16,16', 'potrace_palette_colors': 2, 'potrace_smoothing': 0}
        _, neutral = self.regions(image, potrace_detail_weight=1, **opts)
        _, weighted = self.regions(image, potrace_detail_weight=15, **opts)
        self.assertGreater(weighted[0]['color'][0], neutral[0]['color'][0] + 50)

    def test_nondefault_real_conversion_preserves_budget_and_transparency(self):
        im = fixture().convert('RGBA')
        im.putalpha(128)
        stream = io.BytesIO()
        im.save(stream, 'PNG')
        config = {'engine': 'potrace', 'path_limit': 3, 'output_directory': str(self.folder),
                  'potrace_alpha_max': .7, 'potrace_opt_tolerance': .15, 'potrace_opt_curve': False,
                  'potrace_turn_policy': 'black', 'potrace_palette_colors': 8, 'potrace_smoothing': 0,
                  'potrace_min_region_area': 4, 'potrace_detail_weight': 20, 'potrace_stroke_width': 0,
                  'detail_region': '5,5,42,38'}
        result = convert(stream.getvalue(), 'parameters.png', config)
        self.assertLessEqual(result['stats']['paths'], 3)
        root = ET.fromstring(result['svg'])
        self.assertTrue(all(p.get('stroke') == 'none' for p in root.iter(NS + 'path')))
        self.assertTrue(all(abs(float(g.get('opacity')) - 128 / 255) < .0001 for g in root.iter(NS + 'g')))
        self.assertEqual(root.get('viewBox'), '0 0 64 48')


if __name__ == '__main__':
    unittest.main(verbosity=2)
