import os,sys,tempfile,json,unittest,subprocess
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'app'))
from vector_geometry import normalize_svg,simplify_svg,svg_counts,parse_d,NS


class VectorGeometryTests(unittest.TestCase):
    def test_transforms_opacity_and_holes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);source=folder/'in.svg';out=folder/'out.svg'
            source.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="96"><g opacity="0.5" transform="translate(8,12)"><path fill="#ff0000" stroke="#ff0000" stroke-width="2" stroke-linejoin="round" fill-rule="evenodd" d="M0 0H80V60H0Z M20 20H40V40H20Z"/></g></svg>')
            normalize_svg(source,out,64,48);root=ET.parse(out).getroot();p=root.find('.//'+NS+'path')
            self.assertEqual(root.get('viewBox'),'0 0 64 48');self.assertEqual(root[0].get('opacity'),'0.5')
            self.assertEqual(p.get('stroke-width'),'1');self.assertEqual(p.get('fill-opacity'),'1')
            self.assertEqual(p.get('fill-rule'),'evenodd');self.assertEqual(svg_counts(out)['contours'],2)
            np.testing.assert_allclose(parse_d(p.get('d'))[0].segments[0][0],[4,6])

    def test_simplification_reduces_redundancy_keeps_hole_and_corner(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'in.svg';out=Path(directory)/'out.svg'
            source.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><g opacity="0.4"><path fill="red" fill-rule="evenodd" d="M0 0L20 0L40 0L60 0L100 0L100 100L0 100Z M20 20L20 40L40 40L40 20Z"/></g></svg>')
            events=[];result=simplify_svg(source,out,.3,lambda *a,**k:events.append((a,k)))
            self.assertLess(result['after']['total_segments'],result['before']['total_segments'])
            self.assertEqual(result['after']['contours'],2)
            root=ET.parse(out).getroot();self.assertEqual(root[0].get('opacity'),'0.4')
            corners=[c.segments[0][0] for c in parse_d(root[0][0].get('d'))]
            points=[s[0] for s in parse_d(root[0][0].get('d'))[0].segments]
            self.assertTrue(any(np.allclose(p,[100,0]) for p in points));self.assertTrue(events)

    def test_empty_and_unsupported(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'in.svg';out=Path(directory)/'out.svg'
            source.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="3"/>')
            normalize_svg(source,out,4,3);result=simplify_svg(out,out,.3)
            self.assertEqual(result['after']['fill_paths'],0)
            source.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="3"><image href="x"/></svg>')
            with self.assertRaisesRegex(ValueError,'不支持'):normalize_svg(source,out,4,3)
            source.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="3"><g opacity="0.5"><path d="M0 0H3V2Z"/><path d="M1 0H4V2Z"/></g></svg>')
            with self.assertRaisesRegex(ValueError,'多条路径'):normalize_svg(source,out,4,3)

    def test_coincident_open_stroke_is_simplified_without_new_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'in.svg';out=Path(directory)/'out.svg'
            source.write_text('<svg xmlns="http://www.w3.org/2000/svg"><g><path fill="red" stroke="red" stroke-linejoin="round" d="M0 0L20 0L40 0L60 0L100 0L100 100L0 100L0 0"/></g></svg>')
            result=simplify_svg(source,out,.3)
            self.assertLess(result['after']['total_segments'],result['before']['total_segments'])
            contour=parse_d(ET.parse(out).getroot()[0][0].get('d'))[0]
            self.assertFalse(contour.closed)
            np.testing.assert_array_equal(contour.segments[0][0],contour.segments[-1][-1])

    def test_canonical_curve_polygon_and_pixel_paths_normalize(self):
        fixtures=[
            ('curve','M2 2C8 0 20 0 24 4S28 16 24 20Q16 24 8 20T2 2Z',1,True),
            ('polygon','M2 2l26 4-16 16z M10 8h5v5h-5z',2,False),
            ('pixel','M2 2H8V4H14V6H20V8H28V12H20V16H14V20H6V16H2Z',1,False),
        ]
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            for name,path_data,contours,curves in fixtures:
                with self.subTest(path_type=name):
                    (folder/'raw.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="24"><path fill="blue" fill-rule="evenodd" d="'+path_data+'"/></svg>')
                    result=normalize_svg(folder/'raw.svg',folder/'normalized.svg',64,48)
                    self.assertEqual(result['fill_paths'],1)
                    self.assertEqual(result['contours'],contours)
                    self.assertEqual(result['curve_segments']>0,curves)
                    path=ET.parse(folder/'normalized.svg').getroot().find('.//'+NS+'path')
                    np.testing.assert_allclose(parse_d(path.get('d'))[0].segments[0][0],[4,4])
                    simplified=simplify_svg(folder/'normalized.svg',folder/'simple.svg',.3)
                    for key in ('fill_paths','contours'):
                        self.assertEqual(simplified['before'][key],simplified['after'][key])


@unittest.skipUnless(os.environ.get('IMAGEVECTOR_RUN_ENHANCEMENT_TESTS')=='1','requires configured enhancement runtime')
class RealDiffvgTests(unittest.TestCase):
    def test_actual_potrace_repeated_endpoints_stay_tied(self):
        from enhancement_runtime import run_backend
        from potrace_engine import convert_potrace
        from core import validate
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);target=folder/'target.png';raw=folder/'raw.svg';source=folder/'source.svg';out=folder/'out.svg'
            image=Image.new('RGB',(48,32),(240,244,235));draw=ImageDraw.Draw(image)
            draw.rectangle((7,7,35,25),fill=(35,90,155));draw.ellipse((15,10,28,23),fill=(240,190,40));image.save(target)
            config=validate({'engine':'potrace','path_limit':8,'diffvg_optimize':True,'diffvg_iterations':1})
            convert_potrace(str(target),str(raw),config,lambda *a,**kw:None)
            normalize_svg(raw,source,48,32)
            metadata=run_backend('optimize',{'input':str(source),'output':str(out),'target':str(target),'width':48,'height':32,'config':config},folder,lambda *a,**kw:None)
            self.assertEqual(metadata['before'],metadata['after'])
            self.assertEqual(metadata['global_size'],[48,32])
            for path in ET.parse(out).getroot().iter(NS+'path'):
                for contour in parse_d(path.get('d')):
                    np.testing.assert_array_equal(contour.segments[0][0],contour.segments[-1][-1])

    def test_rgba_hole_full_frame_and_native_tiles(self):
        from enhancement_runtime import run_backend
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);raw=folder/'raw.svg';source=folder/'source.svg';target=folder/'target.png';out=folder/'out.svg'
            raw.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="40"><g opacity="0.5"><path fill="#f0203080" fill-rule="evenodd" d="M10 5H280V35H10Z M40 12H100V28H40Z"/></g><path fill="#2568bb" d="M350 4H590V36H350Z"/></svg>')
            normalize_svg(raw,source,600,40)
            im=Image.new('RGBA',(1200,80));draw=ImageDraw.Draw(im);draw.rectangle((20,10,560,70),fill=(240,32,48,64));draw.rectangle((80,24,200,56),fill=(0,0,0,0));draw.rectangle((700,8,1180,72),fill=(37,104,187,255));im.save(target)
            events=[];metadata=run_backend('optimize',{'input':str(source),'output':str(out),'target':str(target),'width':600,'height':40,
                'config':{'diffvg_optimize':True,'diffvg_iterations':2,'highres_refine':True,'sr_enabled':True}},folder,lambda *a,**kw:events.append((a,kw)))
            self.assertEqual(metadata['global_steps'],2);self.assertEqual(metadata['highres_tiles'],2)
            self.assertEqual(metadata['covered_target_pixels'],1200*80);self.assertEqual(metadata['touched_paths'],2)
            self.assertEqual(svg_counts(out),svg_counts(source));root=ET.parse(out).getroot()
            self.assertEqual(root[0].get('opacity'),'0.5');self.assertAlmostEqual(float(root[0][0].get('fill-opacity')),128/255,7)
            self.assertEqual(root[0][0].get('fill-rule'),'evenodd')
            # Independent SVG rendering: verify the compound hole remains clear and
            # group opacity times intrinsic fill alpha is applied exactly once.
            node=ROOT/'runtime/node/node.exe';sharp=str(ROOT/'runtime/potrace/node_modules/sharp')
            script=folder/'render.cjs';script.write_text('const fs=require("fs"),sharp=require('+json.dumps(sharp)+');sharp(fs.readFileSync(process.argv[2])).png().toFile(process.argv[3]);')
            subprocess.run([str(node),str(script),str(out),str(folder/'out.png')],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            image=Image.open(folder/'out.png').convert('RGBA')
            self.assertEqual(image.getpixel((70,20))[3],0);self.assertLessEqual(abs(image.getpixel((150,20))[3]-64),1)
            self.assertEqual(image.getpixel((400,20))[3],255);self.assertTrue(events)

    def test_empty_and_unsupported_transparent_union(self):
        from enhancement_runtime import run_backend
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);source=folder/'source.svg';out=folder/'out.svg';target=folder/'target.png';Image.new('RGBA',(8,8)).save(target)
            cfg={'diffvg_optimize':False,'highres_refine':True,'sr_enabled':True}
            source.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4" viewBox="0 0 4 4"/>')
            payload={'input':str(source),'output':str(out),'target':str(target),'width':4,'height':4,'config':cfg}
            result=run_backend('optimize',payload,folder,lambda *a,**kw:None);self.assertEqual(result['skipped'],'empty_or_invisible_svg')
            source.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4" viewBox="0 0 4 4"><g opacity="0.5"><path fill="red" stroke="red" stroke-linejoin="round" d="M0 0H3V3H0Z"/></g></svg>')
            with self.assertRaisesRegex(Exception,'半透明'):run_backend('optimize',payload,folder,lambda *a,**kw:None)

if __name__=='__main__':unittest.main(verbosity=2)
