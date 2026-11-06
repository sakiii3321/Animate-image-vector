"""Serial production-port regression against the frozen round-two v4 SVGs.

This is not a new blind review. Preserve final SVGs, small previews and metrics;
native rasterizations and decoded inputs are removed by TemporaryDirectory.
Use --prepare-only to verify inputs/settings without starting conversions.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import traceback
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app'))
from core import DEFAULTS
from illustration_engine import convert_illustration
from illustration_profiles import PROFILE_PRESETS
from status_io import write_json_atomic

FROZEN = ROOT/'outputs/illustration-round2-study'
OUT = ROOT/'outputs/software-optimization-study/regression'
NS = '{http://www.w3.org/2000/svg}'
GRADIENT_CASES = {'test04', 'test03', 'test06', '134791391_p0'}
PARAMETER_KEYS = ('engine', 'path_limit', 'curve_simplify', 'curve_tolerance',
    'potrace_palette_colors', 'potrace_smoothing', 'potrace_min_region_area',
    'potrace_stroke_width', 'potrace_turn_policy', 'potrace_turd_size',
    'potrace_preserve_structure', 'potrace_alpha_max', 'potrace_opt_curve',
    'potrace_opt_tolerance', 'detail_region')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    write_json_atomic(path, value)


def drawing_counts(path):
    root = ET.parse(path).getroot()
    paths = list(root.iter(NS+'path'))
    return {'drawing_paths': len(paths),
            'stroke_paths': sum(p.get('fill') == 'none' for p in paths),
            'gradients': len(list(root.iter(NS+'linearGradient'))),
            'embedded_images': len(list(root.iter(NS+'image'))),
            'viewBox': root.get('viewBox'), 'width': root.get('width'),
            'height': root.get('height')}


def render(source, destination):
    subprocess.run([str(ROOT/'runtime/node/node.exe'),
                    str(ROOT/'app/illustration_render.cjs'),
                    str(source), str(destination)], check=True, capture_output=True,
                   timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def white_rgb(image):
    image = image.convert('RGBA')
    white = Image.new('RGBA', image.size, 'white')
    white.alpha_composite(image)
    return np.asarray(white.convert('RGB'))


def difference(left, right):
    """Native-size RGB metrics, with row chunks to bound temporary memory."""
    assert left.shape == right.shape, (left.shape, right.shape)
    absolute = 0
    squared = 0
    changed = 0
    maximum = 0
    for start in range(0, left.shape[0], 256):
        delta = left[start:start+256].astype(np.int16)-right[start:start+256].astype(np.int16)
        absolute += int(np.abs(delta).sum(dtype=np.int64))
        squared += int((delta.astype(np.int32)**2).sum(dtype=np.int64))
        changed += int(np.count_nonzero(np.any(delta != 0, axis=2)))
        maximum = max(maximum, int(np.abs(delta).max(initial=0)))
    return {'mae': absolute/left.size, 'rmse': (squared/left.size)**.5,
            'max_channel_delta': maximum, 'changed_pixels': changed,
            'changed_pixel_fraction': changed/(left.shape[0]*left.shape[1]),
            'pixel_identical': changed == 0}


def build_plan(profiles, only):
    inventory = json.loads((FROZEN/'inventory.json').read_text(encoding='utf-8'))
    plan = []
    for profile in profiles:
        for item in inventory:
            stem = Path(item['name']).stem
            if profile == 'gradient_layers' and stem not in GRADIENT_CASES:
                continue
            if only and stem not in only:
                continue
            source = ROOT/'test_pic'/item['name']
            assert digest(source) == item['sha256'], ('Input differs from frozen study', source)
            frozen = FROZEN/'cases'/stem/profile
            previous = json.loads((frozen/'result.json').read_text(encoding='utf-8'))
            report = json.loads((frozen/'method-report.json').read_text(encoding='utf-8'))
            assert previous['protocol']['version'] == 4, (stem, profile)
            assert previous['input_sha256'] == item['sha256'], (stem, profile)
            params = {**DEFAULTS, **PROFILE_PRESETS[profile], 'detail_region': '',
                      'sr_enabled': False, 'crop_ratio': '', '_spatial_scale': 1.}
            for key in PARAMETER_KEYS:
                assert params[key] == report['params'][key], (stem, profile, key,
                                                            params[key], report['params'][key])
            plan.append({'image': item['name'], 'stem': stem, 'profile': profile,
                         'source_sha256': item['sha256'], 'params': params,
                         'frozen_svg_sha256': digest(frozen/'output.svg'),
                         'frozen_seconds_historical': previous['seconds']})
    return plan


def run_case(case, fingerprint):
    stem, profile = case['stem'], case['profile']
    work = OUT/stem/profile
    work.mkdir(parents=True, exist_ok=True)
    metrics_path = work/'metrics.json'
    if metrics_path.exists():
        existing = json.loads(metrics_path.read_text(encoding='utf-8'))
        if (existing.get('code_fingerprint') == fingerprint and existing.get('case') == case
                and (work/'output.svg').exists() and (work/'preview.png').exists()
                and digest(work/'output.svg') == existing['output_sha256']):
            return existing
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='native-', dir=work) as temporary:
        temporary = Path(temporary)
        source = ROOT/'test_pic'/case['image']
        with Image.open(source) as image:
            oriented = ImageOps.exif_transpose(image).convert('RGBA')
            oriented.save(temporary/'input.png')
            original = white_rgb(oriented)

        def record(stage, **details):
            write_json_atomic(OUT/'status.json', {'image': case['image'], 'profile': profile,
                              'stage': stage, **details}, optional=True)

        conversion_started = time.perf_counter()
        production = convert_illustration(temporary/'input.png', work/'output.svg',
                                          case['params'], record)
        conversion_seconds = time.perf_counter()-conversion_started
        counts = drawing_counts(work/'output.svg')
        assert counts['drawing_paths'] <= 2000 and counts['embedded_images'] == 0, counts
        frozen = FROZEN/'cases'/stem/profile/'output.svg'
        render(work/'output.svg', temporary/'current.png')
        render(frozen, temporary/'frozen.png')
        with Image.open(temporary/'current.png') as image:
            current = white_rgb(image)
            preview = image.convert('RGBA')
            preview.thumbnail((720, 720), Image.Resampling.LANCZOS)
            preview.save(work/'preview.png', optimize=True)
        with Image.open(temporary/'frozen.png') as image:
            previous = white_rgb(image)
        native_parity = difference(current, previous)
        to_original = difference(current, original)
        previous_to_original = difference(previous, original)
        production['stages'].pop('gradient_validation', None)
        metrics = {'case': case, 'code_fingerprint': fingerprint,
            'conversion_seconds': conversion_seconds,
            'validation_seconds': time.perf_counter()-started-conversion_seconds,
            'counts': counts, 'frozen_counts': drawing_counts(frozen),
            'vs_frozen_v4': native_parity, 'vs_original': to_original,
            'frozen_vs_original': previous_to_original,
            'svg_bytes': (work/'output.svg').stat().st_size,
            'output_sha256': digest(work/'output.svg'), 'production': production}
        write_json(metrics_path, metrics)
    print(json.dumps({'image': case['image'], 'profile': profile,
          'seconds': round(conversion_seconds, 3), **counts,
          'mae_original': to_original['mae'], 'mae_frozen': native_parity['mae'],
          'pixel_identical_to_v4': native_parity['pixel_identical']}), flush=True)
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--profiles', nargs='+', choices=['edge_clean', 'gradient_layers'],
                        default=['edge_clean', 'gradient_layers'])
    parser.add_argument('--only', nargs='*', help='Optional source filename stems')
    args = parser.parse_args()
    plan = build_plan(args.profiles, args.only)
    code_paths = [ROOT/'app'/name for name in ('core.py', 'potrace_engine.py',
        'merge_cost.py', 'structure_features.py', 'illustration_engine.py',
        'illustration_shapes.py', 'illustration_profiles.py', 'vector_geometry.py',
        'illustration_render.cjs', 'potrace_trace.cjs')]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in code_paths}
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {'expected_cases': len(plan), 'code_hashes': hashes,
        'code_fingerprint': fingerprint, 'cases': plan,
        'method': 'Serial native-size production conversion, no crop/SR/ROI; same parameters and portable Sharp renderer as frozen v4. RGB metrics use a white background. Historical times are contextual, not controlled speedup measurements. Pixel MAE is a regression metric, not a perceptual-quality rating.'}
    write_json(OUT/'manifest.json', manifest)
    if args.prepare_only:
        print(json.dumps({'prepared_cases': len(plan), 'output': str(OUT)}, ensure_ascii=False))
        return
    results = []
    for case in plan:
        try:
            results.append(run_case(case, fingerprint))
            write_json(OUT/'summary.json', {'manifest': manifest, 'completed': len(results),
                'exact_v4_matches': sum(r['vs_frozen_v4']['pixel_identical'] for r in results),
                'results': results})
        except Exception:
            write_json(OUT/'status.json', {'image': case['image'], 'profile': case['profile'],
                       'stage': 'error', 'traceback': traceback.format_exc()})
            raise
    write_json(OUT/'status.json', {'stage': 'complete', 'completed': len(results)})


if __name__ == '__main__':
    main()
