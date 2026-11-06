"""Visible small marks and thin-line continuity under a tight region budget."""
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import DEFAULTS
from potrace_engine import prepare_regions, trace_regions
from region_simplify import reduce_regions
from merge_cost import MergeCosts


class DetailPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def regions(self, image, budget=20, **settings):
        source = self.folder / 'source.png'
        image.save(source)
        config = {**DEFAULTS, 'potrace_smoothing':0, **settings}
        return prepare_regions(source, budget, '', lambda *a, **k: None, params=config)

    def test_small_high_contrast_mark_survives_cleanup(self):
        for scale in (1, 2):
            image = Image.new('RGB', (32, 32), 'white')
            ImageDraw.Draw(image).rectangle((10, 10, 12, 12), fill='red')
            image = image.resize((32*scale, 32*scale), Image.Resampling.NEAREST)
            labels, records = self.regions(image, potrace_min_region_area=16*scale*scale)
            self.assertEqual(len(records), 2)
            self.assertNotEqual(labels[11*scale, 11*scale], labels[0, 0])

    def test_low_contrast_speckle_still_cleans(self):
        image = Image.new('RGB', (32, 32), 'white')
        ImageDraw.Draw(image).rectangle((10, 10, 12, 12), fill=(245,245,245))
        _, records = self.regions(image, potrace_min_region_area=16)
        self.assertEqual(len(records), 1)

    def test_budget_merges_background_before_continuous_dark_line(self):
        image = Image.new('RGB', (120, 640))
        draw = ImageDraw.Draw(image)
        for i, gray in enumerate((170, 190, 210)):
            draw.rectangle((i*40, 0, i*40+39, 639), fill=(gray,)*3)
        for x in range(8, 112):
            gray = 30 if (x//8)%2 else 50
            draw.point((x, 320), fill=(gray,)*3)
        labels, records = self.regions(image, budget=2, potrace_min_region_area=0)
        colors = np.array([[0,0,0,0]] + [r['color'] for r in records])
        rendered = colors[labels][:,:,:3]
        self.assertTrue((rendered[320,8:112].mean(axis=1) < 80).all())
        self.assertTrue((rendered[0].mean(axis=1) > 150).all())

    def test_second_merge_uses_same_color_priority(self):
        labels = np.ones((64, 96), dtype='uint16')
        labels[:,48:] = 2
        labels[20:23,20:23] = 3
        records = [
            {'id':1,'color':[170,170,170,255],'bbox':[0,0,48,64]},
            {'id':2,'color':[210,210,210,255],'bbox':[48,0,96,64]},
            {'id':3,'color':[255,0,0,255],'bbox':[20,20,23,23]},
        ]
        trace_regions(labels, records, self.folder/'initial.svg', DEFAULTS, lambda *a,**k:None)
        reduce_regions(self.folder, self.folder/'reduced.svg', 2, DEFAULTS, lambda *a,**k:None)
        reduced = np.fromfile(self.folder/'regions.bin', dtype='<u2').reshape(labels.shape)
        self.assertNotEqual(reduced[21,21], reduced[0,0])
        self.assertEqual(reduced[0,0], reduced[0,95])

    def test_large_background_stroke_is_painted_before_thin_detail(self):
        labels = np.full((40,40), 2, dtype='uint16')
        labels[20,3:37] = 1
        records = [
            {'id':1, 'area':34, 'bbox':[3,20,37,21], 'color':[0,0,0,255]},
            {'id':2, 'area':1566, 'bbox':[0,0,40,40], 'color':[255,255,255,255]},
        ]
        output = self.folder/'stroke.svg'
        trace_regions(labels, records, output, DEFAULTS, lambda *a,**k:None)
        paths = list(ET.parse(output).getroot().iter('{http://www.w3.org/2000/svg}path'))
        self.assertEqual([p.get('fill') for p in paths], ['#ffffff','#000000'])

    def test_cached_edge_priorities_match_full_recomputation(self):
        pixels = np.full((96,96,3), 220, dtype='uint8')
        rng = np.random.default_rng(7)
        pixels[::3,::3] = rng.integers(100,230,(32,32,3),dtype='uint8')
        image = Image.fromarray(pixels)
        cached = self.regions(image, budget=12)
        update = MergeCosts.update
        def always_recompute(costs, *args):
            update(costs, *args)
            return True
        with patch.object(MergeCosts, 'update', always_recompute):
            eager = self.regions(image, budget=12)
        np.testing.assert_array_equal(cached[0], eager[0])
        self.assertEqual(cached[1], eager[1])
