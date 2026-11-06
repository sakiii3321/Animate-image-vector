"""Small real-SR integration check for the production illustration profiles.

Uses the configured enhancement runtime and shipped model weights. This is an
integration check, not a GPU benchmark or an artificial backend fallback test.
"""
from pathlib import Path
import io
import json
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app'))
from core import convert
from illustration_engine import render_svg


def main():
    work = ROOT/'outputs/software-optimization-study/sr-integration'
    work.mkdir(parents=True, exist_ok=True)
    temp_root = work/'temporary'
    temp_root.mkdir(exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(temp_root)
    tempfile.tempdir = str(temp_root)
    rgba = np.zeros((64, 96, 4), np.uint8)
    yy, xx = np.mgrid[8:56, 36:88]
    rgba[8:56, 36:88, 0] = 70+(xx-36)*2
    rgba[8:56, 36:88, 1] = 130+(yy-8)
    rgba[8:56, 36:88, 2] = 200-(xx-36)
    rgba[8:56, 36:88, 3] = 255
    image = Image.fromarray(rgba)
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 27, 51), fill=(180, 80, 60, 128))
    draw.line((42, 45, 79, 18), fill=(25, 35, 65, 255), width=2)
    source = work/'source.png'
    image.save(source)
    summary = {'source_size':[96, 64], 'requested_scale':2, 'profiles':{},
               'purpose':'Actual SR-to-illustration integration, no forced GPU failures'}
    for profile in ('edge_clean', 'gradient_layers'):
        events = []
        def progress(stage, **details):
            events.append({'stage':stage, **details})
            if not details.get('current') or details.get('current') == details.get('total'):
                print(profile, stage, details, flush=True)
        start = time.perf_counter()
        result = convert(source.read_bytes(), profile+'.png', {
            'engine':'potrace', 'illustration_profile':profile,
            'sr_enabled':True, 'sr_scale':2, 'highres_refine':False,
            'diffvg_optimize':False, 'path_limit':64,
            'potrace_palette_colors':16, 'potrace_smoothing':0,
            'potrace_preserve_structure':False, 'potrace_turn_policy':'black',
            'curve_simplify':True, 'curve_tolerance':.3,
            'output_directory':str(work)}, progress)
        original_destination = Path(result['path'])
        final_svg = work/(profile+'.svg')
        original_destination.replace(final_svg)
        original_destination.with_suffix('.pipeline.json').replace(work/(profile+'.pipeline.json'))
        processed = Image.open(io.BytesIO(result['processed'])).convert('RGBA')
        processed.save(work/(profile+'-sr.png'))
        expected_alpha = image.getchannel('A').resize((192,128), Image.Resampling.LANCZOS)
        assert processed.size == (192,128)
        assert processed.getchannel('A').tobytes() == expected_alpha.tobytes()
        svg_root = ET.fromstring(result['svg'])
        rendered = render_svg(svg_root, work/(profile+'-render.png'))
        (work/(profile+'-render.svg')).unlink()
        assert rendered.shape == (64,96,4), rendered.shape
        assert int(rendered[0,0,3]) == 0
        assert 96 <= int(rendered[32,20,3]) <= 160
        assert int(rendered[32,70,3]) >= 250
        report = result['pipeline']
        assert report['source_size'] == [96,64]
        assert report['target_size'] == [192,128]
        assert result['stats']['drawing_paths'] <= 64
        assert result['stats']['embedded_images'] == 0
        sr = next(stage['report'] for stage in report['stages'] if stage['stage'] == 'super_resolution')
        vector = next(stage for stage in report['stages'] if stage['stage'] == 'vectorize')
        assert vector['report']['processing_scale'] == 2
        assert vector['report']['budget']['total'] == 64
        assert not any(stage['stage'] == 'optimization' for stage in report['stages'])
        assert not list(temp_root.iterdir()), list(temp_root.iterdir())
        if profile == 'gradient_layers':
            assert result['stats']['gradient_count'] > 0
        summary['profiles'][profile] = {
            'elapsed_seconds':time.perf_counter()-start, 'backend_report':sr,
            'display_size':[int(svg_root.get('width')),int(svg_root.get('height'))],
            'viewBox':svg_root.get('viewBox'), 'rendered_size':[rendered.shape[1],rendered.shape[0]],
            'stats':result['stats'], 'alpha_samples':{
                'transparent_corner':int(rendered[0,0,3]),
                'translucent_patch':int(rendered[32,20,3]),
                'opaque_gradient':int(rendered[32,70,3])},
            'sr_alpha_matches_lanczos':True, 'temporary_jobs_removed':True,
            'pipeline_report':profile+'.pipeline.json', 'progress_events':events,
        }
        print(json.dumps({'profile':profile,'stats':result['stats'],'sr':sr},ensure_ascii=False),flush=True)
        (work/'report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    temp_root.rmdir()
    print('SR integration passed:', work/'report.json', flush=True)


if __name__ == '__main__':
    main()
