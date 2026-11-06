import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from core import DEFAULTS, SCHEMA, validate, convert, normalize_image
from main import AppServer
from PIL import Image, ImageDraw

def sample():
    im = Image.new('RGB', (96, 64), 'white')
    draw = ImageDraw.Draw(im)
    draw.rectangle((5, 5, 40, 55), fill='#e84a38')
    draw.ellipse((42, 10, 90, 58), fill='#316abb')
    draw.line((0, 0, 95, 63), fill='black', width=2)
    data=io.BytesIO();im.save(data,format='PNG');return data.getvalue()

class TestApp(unittest.TestCase):
    def test_defaults(self):
        self.assertTrue({'sr_enabled','sr_scale','curve_simplify','diffvg_optimize','highres_refine'}.issubset(DEFAULTS))
        self.assertEqual(validate({}),DEFAULTS)
        self.assertEqual(DEFAULTS['engine'],'potrace')
    def test_schema_defaults_and_supported_engine(self):
        self.assertEqual(SCHEMA['engine']['choices'],['potrace'])
        self.assertEqual(set(DEFAULTS),set(SCHEMA))
        for key,spec in SCHEMA.items():
            self.assertEqual(DEFAULTS[key],spec['default'],key)
            if 'engine' in spec:self.assertEqual(spec['engine'],'potrace',key)
    def test_validation(self):
        for config in ({'nope':1},{'path_limit':0},{'potrace_palette_colors':True},
                       {'potrace_min_region_area':1.1},{'potrace_turn_policy':'invalid'},
                       {'potrace_opt_tolerance':.01},{'potrace_smoothing':float('nan')}):
            with self.subTest(config=config),self.assertRaises(ValueError):validate(config)
        for key,s in SCHEMA.items():
            if 'min' in s:
                validate({key:s['min']});validate({key:s['max']})
    def test_real_potrace_profiles_export_distinct_files(self):
        with tempfile.TemporaryDirectory() as directory:
            paths=[]
            for profile in ('legacy','edge_clean','flat_layers','gradient_layers'):
                with self.subTest(profile=profile):
                    result=convert(sample(),'测试.png',{'engine':'potrace','illustration_profile':profile,'output_directory':directory})
                    self.assertTrue(ET.fromstring(result['svg']).tag.endswith('svg'))
                    self.assertEqual(Path(result['path']).read_bytes(),result['svg'])
                    paths.append(result['path'])
            self.assertEqual(len(set(paths)),4)
    def test_palette_boundaries_are_used_without_parameter_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            for colors in (2,256):
                with self.subTest(colors=colors):
                    result=convert(sample(),'sample.png',{'engine':'potrace',
                        'potrace_palette_colors':colors,'output_directory':directory})
                    self.assertEqual(result['config']['potrace_palette_colors'],colors)
                    self.assertTrue(Path(result['path']).exists())
    def test_images(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Exception):normalize_image(b'not a picture',Path(d)/'x.png')
            image=Image.new('RGBA',(3,3),(255,0,0,0));stream=io.BytesIO();image.save(stream,format='PNG')
            normalize_image(stream.getvalue(),Path(d)/'x.png')
            with Image.open(Path(d)/'x.png') as result:self.assertEqual(result.getpixel((0,0)),(255,0,0,0))
    def test_http_security_and_conversion(self):
        server=AppServer();thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,body=None,headers=None):
            r=urllib.request.Request(server.origin+path,data=body,headers=headers or {})
            return urllib.request.urlopen(r,timeout=30)
        try:
            with request('/?token='+server.token) as r:self.assertEqual(r.status,200)
            for path in ('/','/api/schema','/../../etc/passwd'):
                with self.assertRaises(urllib.error.HTTPError):request(path)
            with self.assertRaises(urllib.error.HTTPError):request('/api/schema',headers={'Host':'evil.example','X-App-Token':server.token})
            with self.assertRaises(urllib.error.HTTPError):request('/api/convert',b'{}',{'Origin':'https://evil.example','X-App-Token':server.token,'Content-Type':'application/json'})
            with tempfile.TemporaryDirectory() as d:
                payload=json.dumps({'name':'sample.png','image':base64.b64encode(sample()).decode(),'config':{'output_directory':d}}).encode()
                with request('/api/convert',payload,{'Origin':server.origin,'X-App-Token':server.token,'Content-Type':'application/json'}) as r:
                    self.assertTrue(Path(json.load(r)['path']).exists())
                with request('/api/svg',headers={'X-App-Token':server.token}) as r:self.assertIn(b'<svg',r.read())
        finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main(verbosity=2)
