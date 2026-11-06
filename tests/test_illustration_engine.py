import sys,unittest
from pathlib import Path
import numpy as np
import tempfile
import math
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from illustration_shapes import fit_gradient,remove_edge_mixtures,records_for,ridge_mask,residual_regions,join_thin_neighbors,centerline_paths
from illustration_shapes import spatial_scale
from illustration_engine import convert_illustration,render_svg
from merge_cost import MergeCosts
from core import DEFAULTS


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work=Path(self.tmp.name)

    def convert(self,image,profile='edge_clean',**kwargs):
        path=self.work/'source.png';image.save(path)
        config={**DEFAULTS,'illustration_profile':profile,'path_limit':30,
                'potrace_palette_colors':16,'potrace_smoothing':0,
                'potrace_preserve_structure':False,'potrace_trace_threads':1,
                'curve_simplify':True,'curve_tolerance':.3,**kwargs}
        original=config.copy()
        report=convert_illustration(path,self.work/'out.svg',config,lambda *a,**k:None)
        self.assertEqual(config,original)
        self.assertLessEqual(report['counts']['drawing_paths'],config['path_limit'])
        self.assertEqual(report['counts']['embedded_images'],0)
        self.assertFalse(list(self.work.glob('illustration-*')))
        return report,ET.parse(self.work/'out.svg').getroot()

    def test_transparent_and_solid_images_with_one_path_budget(self):
        for profile in ('edge_clean','flat_layers','gradient_layers'):
            for color,expected in [((12,20,30,0),0),((12,20,30,255),1)]:
                with self.subTest(profile=profile,color=color):
                    report,root=self.convert(Image.new('RGBA',(48,48),color),profile,path_limit=1)
                    self.assertEqual(report['counts']['drawing_paths'],expected)

    def test_layers_share_small_total_budget(self):
        image=Image.new('RGB',(96,96),'white');draw=ImageDraw.Draw(image)
        draw.rectangle((10,10,86,86),fill='orange');draw.line((12,70,85,16),fill='navy',width=3)
        for profile in ('flat_layers','gradient_layers'):
            for limit in (2,4,8):
                with self.subTest(profile=profile,limit=limit):
                    report,_=self.convert(image,profile,path_limit=limit)
                    self.assertLessEqual(report['counts']['fill_paths']+report['counts']['stroke_paths'],limit)

    def test_alpha_survives_real_render(self):
        image=Image.new('RGBA',(64,64),(60,80,100,0))
        ImageDraw.Draw(image).rectangle((16,16,48,48),fill=(60,80,100,128))
        _,root=self.convert(image,'edge_clean')
        rendered=render_svg(root,self.work/'render.png')
        self.assertEqual(int(rendered[0,0,3]),0)
        self.assertLessEqual(abs(int(rendered[32,32,3])-128),1)

    def test_transparent_islands_get_priority_over_optional_layers(self):
        image=Image.new('RGBA',(64,64),(0,0,0,0));draw=ImageDraw.Draw(image)
        draw.rectangle((8,8,20,20),fill=(100,80,60,255))
        draw.rectangle((40,40,52,52),fill=(60,80,100,255))
        for profile in ('flat_layers','gradient_layers'):
            report,root=self.convert(image,profile,path_limit=2)
            self.assertEqual(report['budget']['base'],2)
            self.assertEqual(report['counts']['drawing_paths'],2)

    def test_gradient_survives_original_display_size(self):
        yy,xx=np.mgrid[:64,:96]
        rgba=np.zeros((64,96,4),np.uint8);rgba[:,:,0]=40+xx;rgba[:,:,1]=70+xx//2;rgba[:,:,2]=180-xx//2;rgba[:,:,3]=255
        report,root=self.convert(Image.fromarray(rgba),'gradient_layers',path_limit=1,_spatial_scale=2)
        self.assertGreater(report['stages']['gradients'],0)
        root.set('width','48');root.set('height','32')
        rendered=render_svg(root,self.work/'render.png')
        self.assertEqual(rendered.shape[:2],(32,48))
        target=np.asarray(Image.fromarray(rgba).resize((48,32),Image.Resampling.LANCZOS))
        self.assertLess(np.abs(rendered[3:-3,3:-3,:3].astype(float)-target[3:-3,3:-3,:3]).mean(),3)

    def test_user_turd_removal_keeps_region_correspondence(self):
        image=Image.new('RGB',(64,64),'white');draw=ImageDraw.Draw(image)
        draw.rectangle((12,12,13,13),fill='red');draw.rectangle((30,30,42,42),fill='blue')
        report,_=self.convert(image,'gradient_layers',potrace_turd_size=10)
        self.assertGreaterEqual(report['stages']['tracer_removed_regions'],1)

    def test_super_resolution_scale_applied_once(self):
        self.assertEqual(spatial_scale((1000,2000)),1)
        self.assertEqual(spatial_scale((2000,4000),2),2)
        self.assertEqual(spatial_scale((400,400),4),3)

    def test_merge_exponent_is_local_to_instance(self):
        mass=np.array([0,16,64.]);areas=mass.copy();sums=np.array([[0]*4,[160]*4,[1280]*4],float)
        original=MergeCosts(mass,sums,areas)
        before=original.cost(1,2)
        specialized=MergeCosts(mass,sums,areas,area_exponent=.75)
        self.assertNotEqual(before,specialized.cost(1,2))
        self.assertEqual(before,original.cost(1,2))
        self.assertEqual(before,MergeCosts(mass,sums,areas).cost(1,2))

class MethodsTests(unittest.TestCase):
    def test_linear_gradient_improves_held_out_pixels(self):
        yy,xx=np.mgrid[:80,:120];points=np.column_stack((xx.ravel(),yy.ravel()))
        values=np.column_stack((40+xx.ravel(),80+.5*xx.ravel(),180-.5*xx.ravel()))
        fit=fit_gradient(points,values,values.mean(axis=0))
        self.assertIsNotNone(fit);self.assertLess(fit['validation_mse_after'],1)
        self.assertGreater(fit['validation_mse_before'],100)

    def test_random_texture_does_not_become_a_gradient(self):
        yy,xx=np.mgrid[:80,:120];points=np.column_stack((xx.ravel(),yy.ravel()))
        values=np.random.default_rng(42).integers(80,160,(len(points),3))
        self.assertIsNone(fit_gradient(points,values,values.mean(axis=0)))

    def test_edge_mix_absorbed_but_real_dot_preserved(self):
        labels=np.ones((40,80),np.uint16);labels[8:32,20:50]=2
        labels[10:18,50]=3;labels[5:7,65:67]=4
        colors=np.array([[0,0,0,0],[255,255,255,255],[100,0,0,255],[177,127,127,255],[0,0,0,255]],np.uint8)
        labels,records=records_for(labels,colors[labels])
        cleaned,items,removed=remove_edge_mixtures(labels,records)
        self.assertEqual(len(removed),1)
        self.assertEqual(cleaned[12,50],cleaned[12,49])
        self.assertNotEqual(cleaned[5,65],cleaned[0,0])
        self.assertEqual(len(items),3)

    def test_continuous_dark_stroke_produces_long_residual(self):
        rgba=np.full((100,160,4),255,np.uint8);rgba[48:52,10:150,:3]=40
        ridge=ridge_mask(rgba)
        self.assertGreater(ridge[49:51,12:148].mean(),.95)
        rendered=np.full_like(rgba,255)
        labels,records,_=residual_regions(rgba,rendered,ridge,20,line_pass=True)
        self.assertTrue(records)
        self.assertGreater((labels[49:51,12:148]>0).mean(),.95)
        self.assertLessEqual(len(records),2)

    def test_diagonal_ink_fragments_join_without_absorbing_background(self):
        labels=np.ones((40,40),np.uint16)
        for i in range(8,30):labels[i,i]=i-6
        colors=np.full((int(labels.max())+1,4),255,np.uint8);colors[2:,:3]=[40,8,22]
        labels,records=records_for(labels,colors[labels])
        joined,records,count=join_thin_neighbors(labels,records)
        self.assertEqual(len(records),2);self.assertGreater(count,15)
        self.assertNotEqual(joined[10,10],joined[10,11])
        self.assertEqual(joined[8,8],joined[29,29])

    def test_centerline_is_not_split_by_small_color_variations(self):
        source=np.full((100,160,4),255,np.uint8)
        for x in range(10,150):source[48:52,x,:3]=40+(x%3)*4
        current=np.full_like(source,255);mask=ridge_mask(source)
        group,guard,report=centerline_paths(source,current,mask,20)
        self.assertEqual(len(group),1)
        self.assertGreater(guard[49,14:146].mean(),.99)
        self.assertEqual(group[0].get('fill'),'none')

if __name__=='__main__':unittest.main(verbosity=2)
