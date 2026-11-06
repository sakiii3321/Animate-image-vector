"""Real Potrace/render checks for user-drawn local vector replacement."""
from pathlib import Path
import io
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from illustration_engine import render_svg
from local_refine import refine_selection, _selection_mask, NS


def png_bytes(image):
    data = io.BytesIO()
    image.save(data, 'PNG')
    return data.getvalue()


def flat_svg(width, height, color='#eeeeee', scale=1):
    w, h = width*scale, height*scale
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {w} {h}">'
            f'<path id="region-1" fill="{color}" d="M0 0H{w}V{h}H0Z"/></svg>').encode()


class LocalRefineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.width, self.height = 128, 96
        self.polygon = [[32,20],[89,24],[94,74],[29,78]]

    def render(self, svg, name):
        return render_svg(ET.fromstring(svg), self.work/(name+'.png'))

    def refine(self, image, svg, polygon=None, **options):
        result = refine_selection(png_bytes(image), svg, polygon or self.polygon,
                                  options, self.work)
        self.assertFalse(list(self.work.glob('local-refine-*')))
        root = ET.fromstring(result['svg'])
        self.assertFalse(any(el.tag.rsplit('}',1)[-1] == 'image' for el in root.iter()))
        report = result['report']
        self.assertLessEqual(report['added_paths'], report['local_budget'])
        self.assertEqual(report['after_paths'], report['before_paths']+report['added_paths'])
        return result

    def test_low_contrast_details_improve_and_outside_stays_identical(self):
        image = Image.new('RGBA',(self.width,self.height),(238,238,238,255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((53,39,64,50),fill=(215,215,220,255))
        draw.line((40,61,79,32),fill=(220,220,225,255),width=2)
        old = flat_svg(self.width,self.height)
        result = self.refine(image,old,path_limit=100,detail='fine')
        before, after = self.render(old,'before'),self.render(result['svg'],'after')
        mask = _selection_mask(self.polygon,(0,0,self.width,self.height))
        outside = ~ndi.binary_dilation(mask,iterations=3)
        self.assertTrue(np.array_equal(before[outside],after[outside]))
        inside = ndi.binary_erosion(mask,iterations=3)
        source = np.asarray(image).astype(float)
        old_error = np.mean((before[inside,:3]-source[inside,:3])**2)
        new_error = np.mean((after[inside,:3]-source[inside,:3])**2)
        self.assertLess(new_error,old_error*.4)
        self.assertLess(np.max(abs(after[44,58,:3].astype(int)-[215,215,220])),3)

    def test_replacement_clears_transparency_instead_of_overlaying_old_art(self):
        image = Image.new('RGBA',(self.width,self.height),(230,80,50,0))
        draw=ImageDraw.Draw(image)
        draw.rectangle((48,35,72,63),fill=(60,120,180,128))
        old=flat_svg(self.width,self.height,'#e65032')
        result=self.refine(image,old,path_limit=50)
        after=self.render(result['svg'],'alpha')
        self.assertEqual(int(after[28,50,3]),0)
        self.assertLessEqual(abs(int(after[48,60,3])-128),1)
        self.assertEqual(int(after[4,4,3]),255)
        self.assertLess(np.max(abs(after[48,60,:3].astype(int)-[60,120,180])),3)

    def test_empty_selected_source_removes_old_details(self):
        image=Image.new('RGBA',(self.width,self.height),(0,0,0,0))
        result=self.refine(image,flat_svg(self.width,self.height),path_limit=50)
        after=self.render(result['svg'],'empty')
        self.assertEqual(result['report']['added_paths'],0)
        self.assertEqual(int(after[48,60,3]),0)
        self.assertEqual(int(after[4,4,3]),255)

    def test_opaque_selection_does_not_introduce_transparent_seams(self):
        image=Image.new('RGBA',(128,96),(120,120,120,255))
        polygon=[[30.3,21.1],[91.7,24.3],[93.1,77.4],[29.9,75.4]]
        old=flat_svg(128,96,'#787878')
        result=self.refine(image,old,polygon,path_limit=50)
        before=self.render(old,'seam-before');after=self.render(result['svg'],'seam-after')
        self.assertGreaterEqual(int(after[:,:,3].min()),250)
        self.assertLessEqual(int(np.abs(after.astype(int)-before).max()),5)
        self.assertEqual(result['report']['opaque_backing'],'whole_selection')

    def test_opaque_colored_regions_have_no_internal_transparent_seams(self):
        image=Image.new('RGBA',(128,96),(180,180,150,255));draw=ImageDraw.Draw(image)
        draw.polygon([(30,30),(77,25),(93,65),(52,72)],fill=(45,120,150,255))
        draw.polygon([(45,30),(64,68),(80,30)],fill=(180,80,75,255))
        draw.ellipse((57,40,62,45),fill=(250,250,240,255))
        result=self.refine(image,flat_svg(128,96,'#b4b496'),path_limit=100,detail='fine')
        after=self.render(result['svg'],'opaque-regions')
        selected=ndi.binary_erosion(_selection_mask(self.polygon,(0,0,128,96)),iterations=3)
        self.assertEqual(int(after[:,:,3][selected].min()),255)
        self.assertLess(np.max(abs(after[42,59,:3].astype(int)-[250,250,240])),4)

    def test_transparent_hole_uses_strict_replacement_even_with_opaque_boundary(self):
        image=Image.new('RGBA',(128,96),(180,180,150,255));draw=ImageDraw.Draw(image)
        draw.ellipse((48,34,74,60),fill=(0,0,0,0))
        result=self.refine(image,flat_svg(128,96,'red'),path_limit=50)
        after=self.render(result['svg'],'transparent-hole')
        self.assertEqual(result['report']['opaque_backing'],'none')
        self.assertEqual(int(after[47,61,3]),0)
        self.assertEqual(int(after[28,60,3]),255)

    def test_transparent_replacement_touching_canvas_edge(self):
        image=Image.new('RGBA',(128,96),(60,120,180,128));draw=ImageDraw.Draw(image)
        draw.rectangle((0,14,7,78),fill=(0,0,0,0))
        polygon=[[0,20],[62,20],[62,72],[0,72]]
        old=flat_svg(128,96,'#c83232')
        result=self.refine(image,old,polygon,path_limit=50)
        before=self.render(old,'canvas-alpha-before');after=self.render(result['svg'],'canvas-alpha-after')
        self.assertEqual(result['report']['opaque_backing'],'none')
        self.assertEqual(int(after[45,0,3]),0)
        self.assertLessEqual(abs(int(after[45,31,3])-128),1)
        selected=_selection_mask(polygon,(0,0,128,96))
        outside=~ndi.binary_dilation(selected,iterations=3)
        self.assertTrue(np.array_equal(before[outside],after[outside]))

    def test_gradient_and_scaled_viewbox_survive_two_refinements_with_unique_ids(self):
        old=(f'<svg xmlns="http://www.w3.org/2000/svg" width="128" height="96" viewBox="10 20 256 192">'
             '<defs><linearGradient id="region-1" gradientUnits="userSpaceOnUse" x1="10" y1="20" x2="266" y2="20">'
             '<stop offset="0" stop-color="#204060"/><stop offset="1" stop-color="#e0d0c0"/></linearGradient></defs>'
             '<path id="base" fill="url(#region-1)" d="M10 20H266V212H10Z"/></svg>').encode()
        source=Image.fromarray(self.render(old,'gradient-original'))
        draw=ImageDraw.Draw(source);draw.ellipse((51,36,63,48),fill=(40,25,20,255))
        first=self.refine(source,old,path_limit=80)
        second_polygon=[[75,35],[105,35],[105,65],[75,65]]
        draw.rectangle((85,43,94,53),fill=(240,240,230,255))
        second=self.refine(source,first['svg'],second_polygon,path_limit=80,detail='fine')
        root=ET.fromstring(second['svg']);ids=[e.get('id') for e in root.iter() if e.get('id')]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(root.get('viewBox'),'10 20 256 192')
        self.assertIsNotNone(root.find('.//'+NS+'linearGradient'))
        before=self.render(old,'gradient-before');after=self.render(second['svg'],'gradient-after')
        selected=_selection_mask(self.polygon,(0,0,128,96))|_selection_mask(second_polygon,(0,0,128,96))
        outside=~ndi.binary_dilation(selected,iterations=3)
        self.assertTrue(np.array_equal(before[outside],after[outside]))
        self.assertLess(np.max(abs(after[42,57,:3].astype(int)-[40,25,20])),5)
        self.assertLess(np.max(abs(after[48,89,:3].astype(int)-[240,240,230])),5)

    def test_self_intersection_has_even_odd_selection(self):
        polygon=[[30,20],[90,75],[30,75],[90,20]]
        image=Image.new('RGB',(128,96),'red')
        result=self.refine(image,flat_svg(128,96),polygon,path_limit=50)
        before=self.render(flat_svg(128,96),'evenodd-before')
        after=self.render(result['svg'],'evenodd-after')
        mask=_selection_mask(polygon,(0,0,128,96))
        self.assertTrue(np.array_equal(before[~ndi.binary_dilation(mask,iterations=3)],after[~ndi.binary_dilation(mask,iterations=3)]))
        self.assertLess(np.max(abs(after[30,60,:3].astype(int)-[255,0,0])),3)
        self.assertEqual(result['report']['selection_rule'],'evenodd')

    def test_invalid_and_tiny_polygons_are_rejected_before_tracing(self):
        image=png_bytes(Image.new('RGB',(128,96),'white'));svg=flat_svg(128,96)
        invalid=[[],[[1,1],[2,2]],[[1,1],[1,1],[1,1]],[[1,1],[2,2],[3,3]],
                 [[2,2],[2.1,2],[2,2.1]],[[0,0],[130,0],[0,10]],
                 [[0,0],[10,float('nan')],[0,10]],[[0,0],[True,10],[0,10]]]
        for polygon in invalid:
            with self.subTest(polygon=polygon), self.assertRaises(ValueError):
                refine_selection(image,svg,polygon,work_dir=self.work)
        self.assertFalse(list(self.work.glob('local-refine-*')))

    def test_large_region_and_invalid_options_are_rejected(self):
        image=png_bytes(Image.new('RGB',(2400,1400),'white'))
        with self.assertRaisesRegex(ValueError,'缩小圈选'):
            refine_selection(image,flat_svg(2400,1400),[[0,0],[2400,0],[2400,1400],[0,1400]],work_dir=self.work)
        image=png_bytes(Image.new('RGB',(128,96),'white'))
        for options in ({'path_limit':49},{'path_limit':1501},{'path_limit':True},{'detail':'magic'},{'palette_colors':256}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                refine_selection(image,flat_svg(128,96),self.polygon,options,self.work)


if __name__ == '__main__':
    unittest.main(verbosity=2)
