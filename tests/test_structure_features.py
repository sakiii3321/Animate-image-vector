"""Low-contrast closed details must survive quantization and both budgets."""
from pathlib import Path
import sys,tempfile,unittest

import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from core import DEFAULTS,validate
from structure_features import detect_structure
from potrace_engine import prepare_regions,trace_regions
from region_simplify import reduce_regions


def fixture():
    image=Image.new('RGBA',(300,140),(190,190,190,255))
    draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,99,139),fill=(180,180,180,255))
    draw.rectangle((200,0,299,139),fill=(200,200,200,255))
    # Seven RGB levels: just over the detector's two Lab unit contrast floor.
    draw.ellipse((139,59,161,81),fill=(183,183,183,255))
    draw.ellipse((239,59,261,81),fill=(215,215,215,255))
    return image


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.params={**DEFAULTS,'potrace_preserve_structure':True,'potrace_palette_colors':2,
                     'potrace_min_region_area':1024,'path_limit':6}

    def test_detect_both_polarities_and_ignore_transparent_rgb(self):
        rgba=np.array(fixture())
        labels=detect_structure(rgba)
        self.assertGreater(labels[70,150],0)
        self.assertGreater(labels[70,250],0)
        self.assertNotEqual(labels[70,150],labels[70,250])
        rgba[50:90,130:170,3]=0
        labels=detect_structure(rgba)
        self.assertFalse(labels[50:90,130:170].any())

    def test_closed_details_survive_two_color_palette_and_area_cleanup_at_both_scales(self):
        for scale in (1,2):
            with self.subTest(scale=scale):
                image=fixture().resize((300*scale,140*scale),Image.Resampling.NEAREST)
                source=self.folder/'input.png';image.save(source)
                labels,records=prepare_regions(source,3,'',lambda *a,**k:None,scale=scale,params=self.params)
                self.assertEqual(len(records),3)
                self.assertNotEqual(labels[70*scale,150*scale],labels[20*scale,150*scale])
                self.assertNotEqual(labels[70*scale,250*scale],labels[20*scale,250*scale])
                self.assertEqual(sum(r['feature_id']>0 for r in records),2)

    def test_second_budget_preserves_features_but_one_path_budget_can_still_finish(self):
        source=self.folder/'input.png';fixture().save(source)
        labels,records=prepare_regions(source,6,'',lambda *a,**k:None,params=self.params)
        trace_regions(labels,records,self.folder/'first.svg',self.params,lambda *a,**k:None)
        reduce_regions(self.folder,self.folder/'three.svg',3,self.params,lambda *a,**k:None)
        reduced=np.fromfile(self.folder/'regions.bin',dtype='<u2').reshape(labels.shape)
        self.assertNotEqual(reduced[70,150],reduced[20,150])
        self.assertNotEqual(reduced[70,250],reduced[20,250])
        report=reduce_regions(self.folder,self.folder/'one.svg',1,self.params,lambda *a,**k:None)
        self.assertEqual(report['merged_regions'],1)

    def test_mode_defaults_off_and_rejects_nonboolean(self):
        self.assertFalse(validate({})['potrace_preserve_structure'])
        self.assertTrue(validate({'potrace_preserve_structure':True})['potrace_preserve_structure'])
        with self.assertRaises(ValueError):validate({'potrace_preserve_structure':1})


if __name__=='__main__':unittest.main(verbosity=2)
