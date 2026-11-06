"""Feature dependency, conversion integration, and source-coordinate checks."""
import io,json,os,sys,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from core import validate,convert
from PIL import Image,ImageDraw

def sample(alpha=False):
    image=Image.new('RGBA',(48,32),(240,244,235,0 if alpha else 255))
    d=ImageDraw.Draw(image);d.rectangle((7,7,35,25),fill=(35,90,155,255));d.ellipse((15,10,28,23),fill=(240,190,40,255))
    out=io.BytesIO();image.save(out,'PNG');return out.getvalue()

class PipelineConfigTests(unittest.TestCase):
    def test_sr_default_and_explicit_override(self):
        self.assertFalse(validate({})['highres_refine'])
        self.assertTrue(validate({'sr_enabled':True})['highres_refine'])
        self.assertFalse(validate({'sr_enabled':True,'highres_refine':False})['highres_refine'])
        self.assertTrue(validate({'diffvg_optimize':True})['diffvg_optimize'])
        self.assertFalse(validate({'diffvg_optimize':True})['sr_enabled'])
        with self.assertRaisesRegex(ValueError,'需要先启用'):
            validate({'highres_refine':True})
    def test_bad_enhancement_types(self):
        for conf in [{'sr_enabled':1},{'curve_simplify':'false'},{'diffvg_optimize':None},{'highres_refine':1},{'sr_scale':3},{'curve_tolerance':0},{'diffvg_iterations':1.5}]:
            with self.subTest(conf=conf),self.assertRaises(ValueError):validate(conf)
    def test_curve_only_without_torch_backend(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d,patch('enhancement_runtime.run_backend',side_effect=AssertionError('Curve-only must not invoke torch')):
            result=convert(sample(),'curve.png',{'curve_simplify':True,'output_directory':d})
            self.assertFalse(result['processed_available'])
            self.assertIsNotNone(result['pipeline'])
            self.assertTrue(Path(result['path']).with_suffix('.pipeline.json').exists())
            stages=result['pipeline']['stages'];before=stages[0]['counts'];after=result['pipeline']['final_counts']
            self.assertEqual(before['fill_paths'],after['fill_paths'])
            self.assertEqual(before['contours'],after['contours'])
            self.assertLessEqual(after['total_segments'],before['total_segments'])

@unittest.skipUnless(os.environ.get('IMAGEVECTOR_RUN_ENHANCEMENT_TESTS')=='1','Set IMAGEVECTOR_RUN_ENHANCEMENT_TESTS=1 for real SR/DiffVG integration')
class RealEnhancementIntegration(unittest.TestCase):
    def test_actual_sr_preprocess_preserves_source_canvas_and_alpha(self):
        with tempfile.TemporaryDirectory() as d:
            result=convert(sample(True),'alpha.png',{'engine':'potrace','path_limit':16,'sr_enabled':True,'sr_scale':2,'highres_refine':False,'output_directory':d})
            self.assertTrue(result['processed_available'])
            self.assertEqual((result['width'],result['height']),(48,32))
            target=Image.open(io.BytesIO(result['processed']));self.assertEqual(target.size,(96,64))
            self.assertEqual(target.getpixel((0,0))[3],0)
            root=ET.fromstring(result['svg']);self.assertEqual(root.get('viewBox'),'0 0 48 32')
            self.assertLessEqual(result['stats']['paths'],16)
            self.assertFalse(list(root.iter('{http://www.w3.org/2000/svg}image')))
    def test_actual_full_pipeline_and_highres_without_fullframe(self):
        with tempfile.TemporaryDirectory() as d:
            for global_opt in (False,True):
                events=[]
                config={'engine':'potrace','path_limit':12,'sr_enabled':True,'sr_scale':2,'curve_simplify':True,'diffvg_optimize':global_opt,'diffvg_iterations':1,'highres_refine':True,'output_directory':d}
                result=convert(sample(),'pipeline.png',config,progress=lambda stage,**kw:events.append((stage,kw)))
                initial=next(s['counts'] for s in result['pipeline']['stages'] if s['stage']=='vectorize')
                self.assertEqual(result['stats']['paths'],initial['fill_paths'])
                self.assertEqual(result['stats']['contours'],initial['contours'])
                self.assertTrue(any(s['stage']=='optimization' for s in result['pipeline']['stages']))
                self.assertTrue(events);self.assertEqual(events[-1][0],'complete')
                self.assertEqual(result['config']['diffvg_optimize'],global_opt)
    def test_actual_diffvg_without_sr(self):
        with tempfile.TemporaryDirectory() as d:
            result=convert(sample(),'global.png',{'engine':'potrace','path_limit':8,'diffvg_optimize':True,'diffvg_iterations':1,'output_directory':d})
            self.assertFalse(result['processed_available'])
            self.assertFalse(result['config']['highres_refine'])
            self.assertEqual(result['pipeline']['target_size'],[48,32])
    def test_actual_potrace_polygon_sr4_and_optimization(self):
        with tempfile.TemporaryDirectory() as d:
            result=convert(sample(),'polygon.png',{'engine':'potrace','illustration_profile':'legacy',
                'potrace_alpha_max':0,'path_limit':12,'sr_enabled':True,'sr_scale':4,
                'curve_simplify':True,'diffvg_optimize':True,'diffvg_iterations':1,
                'highres_refine':False,'output_directory':d})
            self.assertEqual(result['pipeline']['target_size'],[192,128])
            self.assertEqual(ET.fromstring(result['svg']).get('viewBox'),'0 0 48 32')
            initial=next(s['counts'] for s in result['pipeline']['stages'] if s['stage']=='vectorize')
            final=result['pipeline']['final_counts']
            self.assertEqual(initial['curve_segments'],0)
            self.assertEqual(initial['fill_paths'],final['fill_paths'])
            self.assertEqual(initial['contours'],final['contours'])
            self.assertLessEqual(final['total_segments'],initial['total_segments'])
    def test_custom_potrace_settings_with_sr_and_postprocessing(self):
        with tempfile.TemporaryDirectory() as directory:
            config={'engine':'potrace','path_limit':12,'potrace_palette_colors':8,
                    'potrace_alpha_max':0,'potrace_opt_curve':False,'potrace_opt_tolerance':0.15,
                    'potrace_turn_policy':'majority','potrace_smoothing':0,'potrace_min_region_area':0,
                    'potrace_detail_weight':3,'detail_region':'8,8,24,16','potrace_stroke_width':0,
                    'sr_enabled':True,'sr_scale':2,'curve_simplify':True,'diffvg_optimize':True,
                    'diffvg_iterations':1,'highres_refine':True,'output_directory':directory}
            result=convert(sample(True),'custom.png',config)
            initial=next(s['counts'] for s in result['pipeline']['stages'] if s['stage']=='vectorize')
            self.assertEqual(initial['curve_segments'],0)
            self.assertGreater(initial['fill_paths'],0)
            self.assertLessEqual(result['stats']['paths'],12)
            self.assertEqual(result['stats']['paths'],initial['fill_paths'])
            self.assertEqual(result['config']['potrace_opt_tolerance'],0.15)
            self.assertFalse(result['config']['potrace_opt_curve'])
            self.assertTrue(result['processed_available'])
            self.assertEqual(result['pipeline']['target_size'],[96,64])
if __name__=='__main__':unittest.main(verbosity=2)
