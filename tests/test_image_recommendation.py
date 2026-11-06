"""Behavioral checks for general, non-semantic image recommendations."""
from pathlib import Path
import json, sys, tempfile, unittest
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from image_recommendation import analyze_image, MAX_SIDE


def line_art(size=(1024,1024)):
    image=Image.new('RGB',size,'white');draw=ImageDraw.Draw(image)
    for offset in range(100,900,120):
        draw.arc((offset//3,offset//3,900-offset//4,900-offset//4),0,310,fill=(25,25,25),width=4)
    draw.line([(150,850),(400,220),(650,850)],fill='black',width=5)
    return image


class RecommendationTests(unittest.TestCase):
    def test_empty_transparent_and_hidden_rgb_are_ignored(self):
        rng=np.random.default_rng(42)
        array=rng.integers(0,256,(240,320,4),dtype=np.uint8);array[:,:,3]=0
        result=analyze_image(Image.fromarray(array))
        self.assertEqual(result['type'],'empty')
        self.assertEqual(result['features']['color_entropy_bits'],0)
        self.assertEqual(result['composition']['layout'],'uniform')
        self.assertEqual(result['clarity']['level'],'undetermined')

    def test_constant_color_is_not_called_blurry_or_gradient(self):
        result=analyze_image(Image.new('RGB',(1600,900),(70,130,180)))
        self.assertEqual(result['type'],'solid')
        self.assertEqual(result['clarity']['level'],'undetermined')
        self.assertEqual(result['recommended_profile'],'edge_clean')
        self.assertEqual(result['composition']['orientation'],'landscape')
        self.assertNotIn('sr_enabled',result['suggested_params'])

    def test_line_art_recommends_edge_preservation(self):
        result=analyze_image(line_art())
        self.assertEqual(result['type'],'line_art')
        self.assertEqual(result['recommended_profile'],'edge_clean')

    def test_smooth_color_gradient_is_distinct_from_noise(self):
        x=np.linspace(0,1,512,dtype=np.float32)
        row=np.stack((40+160*x,60+90*x,220-80*x),axis=1).astype(np.uint8)
        gradient=Image.fromarray(np.repeat(row[None,:,:],384,axis=0))
        smooth=analyze_image(gradient)
        noisy=analyze_image(Image.fromarray(np.random.default_rng(42).integers(0,256,(384,512,3),dtype=np.uint8)))
        self.assertEqual(smooth['type'],'smooth_shading')
        self.assertEqual(smooth['recommended_profile'],'gradient_layers')
        self.assertEqual(noisy['type'],'textured')
        self.assertEqual(noisy['recommended_profile'],'edge_clean')
        self.assertGreater(smooth['features']['smooth_shading_fraction'],.9)
        self.assertLess(noisy['features']['smooth_shading_fraction'],.05)

    def test_small_images_produce_finite_serializable_result(self):
        for size in [(1,1),(1,13),(13,1),(2,3),(5,5)]:
            with self.subTest(size=size):
                result=analyze_image(Image.new('RGBA',size,(40,70,140,128)))
                self.assertEqual(result['source_size'],list(size))
                json.dumps(result,allow_nan=False)

    def test_pale_monochrome_gradient_is_not_mistaken_for_line_art(self):
        row=np.linspace(230,255,1024).astype(np.uint8)
        image=Image.fromarray(np.repeat(row[None,:],512,axis=0)).convert('RGB')
        result=analyze_image(image)
        self.assertNotEqual(result['type'],'line_art')
        self.assertEqual(result['clarity']['level'],'undetermined')

    def test_palette_and_rgb_encoding_have_identical_diagnostics(self):
        palette=line_art().quantize(colors=16)
        a=analyze_image(palette);b=analyze_image(palette.convert('RGB'))
        a.pop('elapsed_ms');b.pop('elapsed_ms')
        self.assertEqual(a,b)

    def test_lower_resolution_does_not_enable_super_resolution(self):
        result=analyze_image(line_art((500,500)))
        self.assertEqual(result['clarity']['level'],'limited_resolution')
        self.assertNotIn('sr_enabled',result['suggested_params'])
        self.assertIn('不自动开启超分辨率',''.join(result['reasons']))

    def test_analysis_is_bounded_and_does_not_mutate_input(self):
        image=line_art((1500,1000));before=image.tobytes()
        result=analyze_image(image)
        self.assertLessEqual(max(result['analysis_size']),MAX_SIDE)
        self.assertEqual(result['source_size'],[1500,1000])
        self.assertEqual(before,image.tobytes())

    def test_filename_does_not_affect_recommendation(self):
        root=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=root) as folder:
            first=Path(folder)/'line_art.png';second=Path(folder)/'complex_portrait.png'
            line_art().save(first);second.write_bytes(first.read_bytes())
            a=analyze_image(first);b=analyze_image(second)
            a.pop('elapsed_ms');b.pop('elapsed_ms')
            self.assertEqual(a,b)

    def test_alpha_layout_can_detect_shift_without_semantic_claim(self):
        image=Image.new('RGBA',(500,500),(255,0,0,0));draw=ImageDraw.Draw(image)
        draw.rectangle((20,120,140,380),fill=(40,80,140,255))
        result=analyze_image(image)
        self.assertEqual(result['composition']['layout'],'offset')
        self.assertEqual(result['composition']['basis'],'透明度范围')
        self.assertLess(result['composition']['centroid'][0],.3)


if __name__=='__main__':unittest.main(verbosity=2)
