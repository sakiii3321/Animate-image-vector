"""Production illustration conversion based on blind-study protocol v4.

The default route cleans edge mixtures and joins compatible thin regions.
Residual centerlines and validated SVG gradients are explicit optional routes.
The contract is processed-input coordinates in the SVG viewBox. The caller may
set root width/height to the original display size after super-resolution.
"""
from contextlib import contextmanager
from pathlib import Path
import math
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from illustration_shapes import (NS, add_gradients, centerline_paths, clean_texture,
    join_thin_neighbors, region_paths, remove_edge_mixtures, residual_regions,
    ridge_mask, spatial_scale)
from potrace_engine import prepare_regions, trace_regions
from vector_geometry import normalize_svg, simplify_svg, svg_counts

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_VERSION = 4
PROFILES = ('edge_clean', 'flat_layers', 'gradient_layers')
ET.register_namespace('', 'http://www.w3.org/2000/svg')


def _empty_svg(width, height):
    return ET.Element(NS+'svg', {'width':str(width), 'height':str(height),
                                 'viewBox':f'0 0 {width} {height}'})


def _trace(labels, records, work, params, record, timed):
    work.mkdir(parents=True, exist_ok=True)
    if not records:
        return _empty_svg(labels.shape[1], labels.shape[0])
    with timed('trace'):
        trace_regions(labels, records, work/'raw.svg', params, record)
    with timed('normalize'):
        normalize_svg(work/'raw.svg', work/'normalized.svg', labels.shape[1], labels.shape[0])
    result = work/'normalized.svg'
    if params.get('curve_simplify', False):
        with timed('curve_simplify'):
            simplify_svg(result, work/'curves.svg',
                         float(params.get('curve_tolerance', .3))*params.get('_spatial_scale', 1), record)
        result = work/'curves.svg'
    return ET.parse(result).getroot()


def render_svg(root, destination):
    """Render exactly once per requested validation using the portable Sharp runtime."""
    destination = Path(destination)
    source = destination.with_suffix('.svg')
    ET.ElementTree(root).write(source, encoding='utf-8', xml_declaration=True)
    node = ROOT/'runtime/node/node.exe'
    if not node.is_file():
        found = shutil.which('node')
        if not found:
            raise RuntimeError('分层插画路线缺少 Node.js 运行时。')
        node = Path(found)
    if not (ROOT/'runtime/potrace/node_modules/sharp/package.json').is_file():
        raise RuntimeError('分层插画路线缺少随程序安装的 Sharp 渲染器；可以使用边界清理路线。')
    try:
        result = subprocess.run([str(node), str(Path(__file__).with_name('illustration_render.cjs')),
                                 str(source), str(destination)], capture_output=True,
                                timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('插画分层预览渲染超时。') from exc
    if result.returncode:
        raise RuntimeError('插画分层预览渲染失败：'+result.stderr.decode('utf-8', errors='replace')[-1600:])
    with Image.open(destination) as image:
        return np.asarray(image.convert('RGBA')).copy()


def convert_illustration(source_path, output_path, params, record):
    """Convert an illustration and return settings, diagnostics and stage timings.

    ``path_limit`` bounds all drawing paths, including optional open strokes.
    User settings are copied, never mutated. ``_spatial_scale`` is the actual
    super-resolution multiplier; area/color costs use original-pixel units.
    All disposable images, masks and subprocess jobs live under output.parent
    and are cleaned after success or failure. No renderer is used by edge_clean.
    """
    from core import DEFAULTS
    config = {**DEFAULTS, **params}
    profile = config.get('illustration_profile', 'edge_clean')
    if profile not in PROFILES:
        raise ValueError('未知插画重构方案：'+str(profile))
    limit = int(config['path_limit'])
    if not 1 <= limit <= 20000:
        raise ValueError('插画路径上限必须在 1 到 20000 之间。')
    scale = float(config.get('_spatial_scale', 1))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('插画处理缩放比例必须为正有限数值。')
    config['_spatial_scale'] = scale
    config['_merge_area_exponent'] = .75
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    timings = {}
    stages = {}

    @contextmanager
    def timed(name):
        start = time.perf_counter()
        try:
            yield
        finally:
            timings[name] = timings.get(name, 0) + time.perf_counter()-start

    with timed('load'):
        with Image.open(source_path) as image:
            source = np.asarray(image.convert('RGBA')).copy()
    height, width = source.shape[:2]
    threshold_scale = spatial_scale(source.shape, scale)
    layered = profile != 'edge_clean'
    base_budget = max(1, math.floor(limit*.6)) if layered else limit
    line_budget = math.floor(limit*.35) if layered else 0
    if layered and np.any(source[:, :, 3] == 0) and np.any(source[:, :, 3]):
        # A base path cannot absorb an island across transparent space. Reserve
        # the minimum topology budget before allocating optional stroke paths.
        with timed('alpha_topology'):
            islands = cv2.connectedComponents((source[:, :, 3] > 0).astype(np.uint8), connectivity=4)[0]-1
        base_budget = min(limit, max(base_budget, islands))
    with tempfile.TemporaryDirectory(prefix='illustration-', dir=output_path.parent) as temp:
        work = Path(temp)
        if not np.any(source[:, :, 3]):
            root = _empty_svg(width, height)
            stages['base_regions'] = 0
        else:
            record('illustration_texture', profile=profile)
            with timed('texture_filter'):
                filtered = clean_texture(source, scale)
                base_path = work/'base-input.png'
                Image.fromarray(filtered).save(base_path)
            # The v4 filter replaces prepare_regions' usual bilateral pass.
            # Keep the user's explicit strength meaningful: zero disables the
            # extra pass; the application preset uses zero for this route.
            record('illustration_regions', limit=base_budget)
            with timed('regions'):
                labels, records = prepare_regions(base_path, base_budget,
                    config.get('detail_region', ''), record, scale=scale,
                    params={**config, 'path_limit':base_budget})
            with timed('edge_cleanup'):
                labels, records, removed = remove_edge_mixtures(labels, records, threshold_scale)
                labels, records, joined = join_thin_neighbors(labels, records, threshold_scale)
                stages.update(edge_mixtures_absorbed=len(removed), thin_regions_joined=joined)
            records.sort(key=lambda r:(-r['area'], r['id']))
            root = _trace(labels, records, work/'base-trace', config, record, timed)
            paths = region_paths(root)
            for region in records:
                if region['id'] in paths and region['area'] < 24*threshold_scale**2:
                    paths[region['id']].set('stroke', 'none')
            stages['base_regions'] = len(paths)
            stages['tracer_removed_regions'] = len(records)-len(paths)
            if profile == 'gradient_layers':
                record('illustration_gradients')
                with timed('gradients'):
                    fits = add_gradients(root, labels, records, filtered)
                    stages['gradients'] = len(fits)
                    stages['gradient_validation'] = fits
            if layered and len(paths) < limit:
                record('illustration_lines')
                with timed('ridge_detection'):
                    ridges = ridge_mask(filtered, scale)
                with timed('render'):
                    current = render_svg(root, work/'base-render.png')
                with timed('centerlines'):
                    available = limit-sum(1 for _ in root.iter(NS+'path'))
                    group, guard, details = centerline_paths(filtered, current, ridges,
                                                             min(available, line_budget), scale)
                if len(group):
                    before = current
                    root.append(group)
                    with timed('render'):
                        current = render_svg(root, work/'lines-render.png')
                    mse_before = float(np.mean((filtered[:, :, :3][guard].astype(float)-before[:, :, :3][guard])**2))
                    mse_after = float(np.mean((filtered[:, :, :3][guard].astype(float)-current[:, :, :3][guard])**2))
                    details.update(rendered_band_mse_before=mse_before, rendered_band_mse_after=mse_after)
                    if mse_after > mse_before:
                        root.remove(group)
                        current = before
                        guard[:] = False
                        details['rejected_after_render'] = True
                stages['lines'] = details
                available = limit-sum(1 for _ in root.iter(NS+'path'))
                record('illustration_residuals', limit=available)
                with timed('residual_regions'):
                    error = np.mean(np.abs(filtered[:, :, :3].astype(float)-current[:, :, :3]), axis=2)
                    eligible = (source[:, :, 3] > 250) & ~guard
                    mask = ndi.binary_propagation((error > 16)&eligible, mask=(error > 7)&eligible)
                    overlay, items, details = residual_regions(filtered, current, mask, available,
                                                               processing_scale=scale)
                if items:
                    layer = _trace(overlay, items, work/'residual-trace',
                                   {**config, 'path_limit':len(items), 'potrace_stroke_width':0}, record, timed)
                    insertion = list(root).index(group) if group in list(root) else len(root)
                    # Region IDs are local to a trace pass; make document IDs unique.
                    for element in layer.iter():
                        if element.get('id'):
                            element.set('id', 'residual-'+element.get('id'))
                    for offset, element in enumerate(list(layer)):
                        root.insert(insertion+offset, element)
                stages['residuals'] = details
                # The final residual has no subsequent comparison pass. Do not
                # rasterize a third time just to discard the resulting bitmap.
        with timed('write'):
            ET.ElementTree(root).write(output_path, encoding='utf-8', xml_declaration=True)
        with timed('counts'):
            counts = svg_counts(output_path)
            counts['drawing_paths'] = sum(1 for _ in root.iter(NS+'path'))
            counts['stroke_paths'] = sum(p.get('fill') == 'none' for p in root.iter(NS+'path'))
        if counts['drawing_paths'] > limit or counts['embedded_images']:
            raise RuntimeError('插画输出未满足纯矢量路径预算。')
    timings['total'] = time.perf_counter()-started
    return {'profile':profile, 'protocol_version':PROTOCOL_VERSION, 'counts':counts,
            'stages':stages, 'timings':timings, 'source_size':[width, height],
            'processing_scale':scale, 'threshold_scale':threshold_scale,
            'params':{key:value for key,value in config.items() if not key.startswith('_')},
            'budget':{'total':limit, 'base':base_budget, 'centerline_limit':line_budget},
            'merge_area_exponent':.75}
