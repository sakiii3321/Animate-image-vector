"""Profile migration, HTTP recommendations, and production pipeline contracts."""
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from PIL import Image, ImageDraw
from core import DEFAULTS, LEGACY_DEFAULTS, validate, convert
from illustration_profiles import PROFILE_PRESETS, resize_illustration_canvas
from main import AppServer

def sample():
    image=Image.new('RGB',(120,80),'white')
    d=ImageDraw.Draw(image);d.rectangle((15,10,100,70),fill='#ed9b83')
    d.line((20,60,90,20), fill='#401e40', width=3)
    data=io.BytesIO();image.save(data,'PNG');return data.getvalue()

class ProfileIntegrationTests(unittest.TestCase):
    def test_default_and_legacy_configs_remain_distinct(self):
        self.assertEqual(validate({}),DEFAULTS)
        self.assertEqual(DEFAULTS['engine'],'potrace')
        self.assertEqual(DEFAULTS['illustration_profile'],'edge_clean')
        self.assertTrue(DEFAULTS['curve_simplify'])
        for old in ({'engine':'potrace'},{'path_limit':3000}):
            cfg=validate(old)
            self.assertEqual(cfg['illustration_profile'],'legacy')
            for k in ('curve_simplify','potrace_smoothing','potrace_palette_colors','potrace_min_region_area','potrace_turn_policy'):
                self.assertEqual(cfg[k],LEGACY_DEFAULTS[k])
        self.assertEqual(validate({'path_limit':3000})['engine'],'potrace')
        self.assertEqual(validate(DEFAULTS),DEFAULTS)
        for profile,preset in PROFILE_PRESETS.items():
            config=validate({'illustration_profile':profile})
            for key,value in preset.items():self.assertEqual(config[key],value,(profile,key))
        self.assertEqual(validate({'illustration_profile':'gradient_layers','potrace_palette_colors':80})['potrace_palette_colors'],80)

    def test_layered_sr_dependency_is_explicit(self):
        cfg=validate({'illustration_profile':'gradient_layers','sr_enabled':True})
        self.assertFalse(cfg['highres_refine'])
        self.assertTrue(cfg['sr_enabled'])
        for key in ('diffvg_optimize','highres_refine'):
            with self.assertRaisesRegex(ValueError,'分层'):
                validate({'illustration_profile':'gradient_layers','sr_enabled':True,key:True})

    def test_viewbox_keeps_gradient_and_stroke_scale(self):
        svg='<svg xmlns="http://www.w3.org/2000/svg" width="200" height="120" viewBox="0 0 200 120"><defs><linearGradient id="g" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="200" y2="120"><stop offset="0" stop-color="red"/><stop offset="1" stop-color="blue"/></linearGradient></defs><path d="M0 0L200 0L200 120Z" fill="url(#g)"/><path d="M10 10L190 100" fill="none" stroke="black" stroke-width="4"/></svg>'
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/'in.svg',Path(temp)/'out.svg';a.write_text(svg,encoding='utf-8')
            resize_illustration_canvas(a,b,100,60)
            root=ET.parse(b).getroot()
            self.assertEqual((root.get('width'),root.get('height'),root.get('viewBox')),('100','60','0 0 200 120'))
            self.assertEqual(root.find('.//{*}linearGradient').get('x2'),'200')
            self.assertEqual(root.findall('{*}path')[1].get('stroke-width'),'4')

    def test_new_routes_actual_conversion_and_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            for profile in ('edge_clean','flat_layers','gradient_layers'):
                with self.subTest(profile=profile):
                    cfg={**PROFILE_PRESETS[profile], 'path_limit':32,'simplify_target_paths':16,'output_directory':temp}
                    result=convert(sample(),'sample.png',cfg)
                    root=ET.fromstring(result['svg']);paths=list(root.iter('{http://www.w3.org/2000/svg}path'))
                    self.assertLessEqual(len(paths),16)
                    self.assertEqual(result['stats']['drawing_paths'],len(paths))
                    report=result['pipeline']['stages'][0]['report']
                    self.assertEqual(report['profile'],profile)
                    self.assertEqual(report['budget']['total'],16)
                    self.assertFalse(any(s['stage']=='region_simplify' for s in result['pipeline']['stages']))
                    self.assertTrue(Path(result['path']).with_suffix('.pipeline.json').exists())

    def test_http_analyzes_crop_without_changing_config_or_result(self):
        server=AppServer();thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        headers={'Origin':server.origin,'X-App-Token':server.token,'Content-Type':'application/json'}
        payload={'image':base64.b64encode(sample()).decode(),'config':{'crop_ratio':'1:1','crop_x':100}}
        def send(value,extra=None):
            request=urllib.request.Request(server.origin+'/api/analyze',data=json.dumps(value).encode(),headers={**headers,**(extra or {})})
            return urllib.request.urlopen(request,timeout=30)
        try:
            with send(payload) as response:r=json.load(response)
            with server.lock:
                with send(payload) as response:self.assertEqual(response.status,200)
            self.assertEqual(r['source_size'],[80,80]);self.assertEqual(r['uncropped_size'],[120,80])
            self.assertEqual(r['crop_box'],[40,0,120,80]);self.assertIn(r['recommended_profile'],PROFILE_PRESETS)
            self.assertIsNone(server.result);self.assertEqual(payload['config'],{'crop_ratio':'1:1','crop_x':100})
            with self.assertRaises(urllib.error.HTTPError) as error:send(payload,{'Origin':'https://example.com'})
            self.assertEqual(error.exception.code,403)
            error.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as error:send({'image':'not base64'})
            self.assertEqual(error.exception.code,400)
            error.exception.close()
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main(verbosity=2)
