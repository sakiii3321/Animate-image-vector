"""Reconstruct one user-selected region from normalized original pixels.

The result is a complete, pure-vector SVG candidate. Adoption and undo belong
to the caller. Existing artwork is retained outside the even-odd selection.
Opaque selections retain old colors beneath new paths to back antialiased
seams; selections containing transparency replace the old region completely.
No semantic detector, generated image, filename rule or full-image rerun is used.
"""
from pathlib import Path
import io
import math
import re
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

from potrace_engine import prepare_regions, trace_regions
from vector_geometry import normalize_svg, simplify_svg

NS = '{http://www.w3.org/2000/svg}'
ET.register_namespace('', 'http://www.w3.org/2000/svg')
MAX_CROP_PIXELS = 1_500_000
MAX_CROP_SIDE = 2048
CONTEXT_MARGIN = 12
_NON_DRAWING = {'defs', 'clipPath', 'mask', 'metadata', 'title', 'desc'}


def _tag(element):
    return element.tag.rsplit('}', 1)[-1]


def _path_count(root):
    def count(element):
        if _tag(element) in _NON_DRAWING:
            return 0
        return int(_tag(element) == 'path') + sum(count(child) for child in element)
    return count(root)


def _settings(options):
    options = {} if options is None else options
    if not isinstance(options, dict):
        raise ValueError('局部精修选项必须是 JSON 对象。')
    unknown = set(options)-{'path_limit', 'detail'}
    if unknown:
        raise ValueError('未知局部精修选项：'+', '.join(sorted(unknown)))
    limit = options.get('path_limit', 300)
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit) or int(limit) != limit or not 50 <= limit <= 1500:
        raise ValueError('局部路径预算必须是 50–1500 的整数。')
    detail = options.get('detail', 'standard')
    if detail not in ('standard', 'fine'):
        raise ValueError('局部细节级别必须是 standard 或 fine。')
    fine = detail == 'fine'
    return {'path_limit':int(limit), 'detail':detail}, {
        'engine':'potrace', 'illustration_profile':'legacy',
        'path_limit':int(limit), 'potrace_palette_colors':256 if fine else 160,
        'potrace_smoothing':0, 'potrace_min_region_area':0,
        'potrace_turd_size':0, 'potrace_stroke_width':0,
        'potrace_opt_curve':True, 'potrace_opt_tolerance':.1 if fine else .2,
        'potrace_alpha_max':1., 'potrace_turn_policy':'black',
        'potrace_preserve_structure':False, 'potrace_trace_threads':0,
        'potrace_detail_weight':1, 'detail_region':'',
        'curve_simplify':True, 'curve_tolerance':.08 if fine else .15,
        '_merge_area_exponent':.5, '_spatial_scale':1.,
    }


def _polygon(points, width, height):
    if not isinstance(points, (list, tuple)) or not 3 <= len(points) <= 4096:
        raise ValueError('圈选需要 3–4096 个画布坐标点。')
    output = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError('圈选坐标必须为 [x, y]。')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point):
            raise ValueError('圈选坐标必须为有限数值。')
        x, y = map(float, point)
        if not (0 <= x <= width and 0 <= y <= height):
            raise ValueError('圈选坐标超出原图画布范围。')
        if not output or (x, y) != output[-1]:
            output.append((x, y))
    if len(output) > 1 and output[0] == output[-1]:
        output.pop()
    if len(set(output)) < 3:
        raise ValueError('圈选区域需要至少三个不同的坐标点。')
    x0 = max(0, math.floor(min(p[0] for p in output))-CONTEXT_MARGIN)
    y0 = max(0, math.floor(min(p[1] for p in output))-CONTEXT_MARGIN)
    x1 = min(width, math.ceil(max(p[0] for p in output))+CONTEXT_MARGIN)
    y1 = min(height, math.ceil(max(p[1] for p in output))+CONTEXT_MARGIN)
    if (x1-x0)*(y1-y0) > MAX_CROP_PIXELS or max(x1-x0, y1-y0) > MAX_CROP_SIDE:
        raise ValueError('局部处理范围过大（含 12 像素上下文，最多 150 万像素、长边 2048）；请缩小圈选范围。')
    selected = _selection_mask(output, (x0, y0, x1, y1))
    if np.count_nonzero(selected) < 4:
        raise ValueError('圈选区域过小或没有有效内部，请至少圈住 4 个原图像素。')
    return output, (x0, y0, x1, y1), selected


def _selection_mask(points, box):
    """Pixel-center scan conversion with the same even-odd rule as SVG clips."""
    x0, y0, x1, y1 = box
    mask = np.zeros((y1-y0, x1-x0), bool)
    vertices = np.asarray(points, float)
    following = np.roll(vertices, -1, axis=0)
    for row in range(mask.shape[0]):
        y = y0+row+.5
        crossing = (vertices[:, 1] > y) != (following[:, 1] > y)
        a, b = vertices[crossing], following[crossing]
        if not len(a):
            continue
        intersections = np.sort(a[:, 0]+(y-a[:, 1])*(b[:, 0]-a[:, 0])/(b[:, 1]-a[:, 1]))
        for left, right in zip(intersections[::2], intersections[1::2]):
            start = max(0, math.ceil(left-x0-.5))
            stop = min(mask.shape[1], math.ceil(right-x0-.5))
            if stop > start:
                mask[row, start:stop] = True
    return mask


def _svg_coordinates(root, width, height):
    if _tag(root) != 'svg':
        raise ValueError('当前结果不是 SVG。')
    if any(_tag(element) in ('image', 'foreignObject') for element in root.iter()):
        raise ValueError('局部精修只接受不含嵌入位图的矢量结果。')
    try:
        canvas = [float(root.get(key, str(value)).removesuffix('px'))
                  for key, value in [('width', width), ('height', height)]]
        viewbox = [float(v) for v in re.split(r'[\s,]+', root.get('viewBox', f'0 0 {width} {height}').strip())]
    except (ValueError, TypeError):
        raise ValueError('当前 SVG 的画布或 viewBox 无效。') from None
    if (len(viewbox) != 4 or not all(math.isfinite(v) for v in viewbox)
            or min(viewbox[2:]) <= 0 or canvas != [width, height]):
        raise ValueError('当前 SVG 尺寸与原图画布不一致。')
    # Application outputs always cover the complete original canvas. Reject a
    # different aspect ratio instead of guessing letterbox or crop coordinates.
    if not math.isclose(viewbox[2]/viewbox[3], width/height, rel_tol=1e-7):
        raise ValueError('当前 SVG 的 viewBox 比例与原图不一致。')
    root.set('width', str(width))
    root.set('height', str(height))
    return viewbox


def _namespace_ids(root, prefix):
    mapping = {el.get('id'):prefix+el.get('id') for el in root.iter() if el.get('id')}
    for element in root.iter():
        for key, value in list(element.attrib.items()):
            if key == 'id':
                element.set(key, mapping[value])
            elif key.rsplit('}', 1)[-1] == 'href' and value.startswith('#') and value[1:] in mapping:
                element.set(key, '#'+mapping[value[1:]])
            elif 'url(' in value:
                element.set(key, re.sub(r'url\(\s*[\'"]?#([^\s)\'\"]+)[\'"]?\s*\)',
                    lambda match:'url(#'+mapping.get(match[1], match[1])+')', value))


def _coordinates(points):
    return ' '.join(f'{x:.8g},{y:.8g}' for x, y in points)


def _replace_selection(root, patch, points, crop_box, viewbox, opaque_selection=False):
    """Keep original children/paint servers and replace only the selected area."""
    vx, vy, vw, vh = viewbox
    width, height = float(root.get('width').removesuffix('px')), float(root.get('height').removesuffix('px'))
    sx, sy = vw/width, vh/height
    mapped = [(vx+x*sx, vy+y*sy) for x, y in points]
    existing = {el.get('id') for el in root.iter() if el.get('id')}
    prefix = 'local-'+uuid.uuid4().hex+'-'
    while any(ident.startswith(prefix) for ident in existing):
        prefix = 'local-'+uuid.uuid4().hex+'-'
    _namespace_ids(patch, prefix)
    defs = ET.Element(NS+'defs')
    outside_id, inside_id = prefix+'outside', prefix+'inside'
    if not opaque_selection:
        # A doubled bridge joins the canvas ring and selection ring without
        # adding area. Even-odd clips also define self-intersections.
        canvas = [(vx, vy), (vx+vw, vy), (vx+vw, vy+vh), (vx, vy+vh), (vx, vy)]
        inverse = canvas+mapped+[mapped[0], canvas[0]]
        outside = ET.SubElement(defs, NS+'clipPath', {'id':outside_id, 'clipPathUnits':'userSpaceOnUse'})
        ET.SubElement(outside, NS+'polygon', {'points':_coordinates(inverse), 'clip-rule':'evenodd', 'fill-rule':'evenodd'})
    inside = ET.SubElement(defs, NS+'clipPath', {'id':inside_id, 'clipPathUnits':'userSpaceOnUse'})
    ET.SubElement(inside, NS+'polygon', {'points':_coordinates(mapped), 'clip-rule':'evenodd', 'fill-rule':'evenodd'})
    if not opaque_selection:
        base = ET.Element(NS+'g', {'clip-path':f'url(#{outside_id})', 'data-local-refine':'previous'})
        # Transparent source pixels must remove prior artwork, not expose it
        # through the patch. Definitions remain in the original document scope.
        for child in list(root):
            if _tag(child) not in ('defs', 'metadata', 'title', 'desc'):
                root.remove(child)
                base.append(child)
        root.append(base)
    # Fully opaque selections keep prior drawing children in their exact
    # order. Existing colors provide backing in subpixel seams between newly
    # traced adjacent regions, without widening highlights with extra strokes.
    # No whole-canvas mask is introduced, so remote pixels are not recomposited.
    root.append(defs)
    replacement = ET.SubElement(root, NS+'g', {'clip-path':f'url(#{inside_id})', 'data-local-refine':'replacement'})
    x0, y0, _, _ = crop_box
    local = ET.SubElement(replacement, NS+'g', {
        'transform':f'matrix({sx:.12g} 0 0 {sy:.12g} {vx+x0*sx:.12g} {vy+y0*sy:.12g})'})
    for child in list(patch):
        local.append(child)
    return root


def refine_selection(original_png_bytes, current_svg_bytes, polygon, options=None,
                     work_dir=None, record=None):
    """Return ``{'svg': bytes, 'report': dict}``; never adopt/save over the result.

    ``polygon`` uses final-canvas original-pixel coordinates. Options contain
    only ``path_limit`` (50–1500, default 300) and ``detail`` (standard/fine).
    ``work_dir`` is the isolated caller's job folder; disposable crop/tracing
    files are removed on success or failure. The caller controls cancellation.
    """
    started = time.perf_counter()
    record = record or (lambda *args, **kwargs:None)
    chosen, params = _settings(options)
    record('local_refine_prepare')
    with Image.open(io.BytesIO(original_png_bytes)) as source:
        width, height = source.size
        points, box, selected = _polygon(polygon, width, height)
        crop = source.crop(box).convert('RGBA')
    opaque_selection = bool(np.all(np.asarray(crop)[:, :, 3][selected] == 255))
    try:
        root = ET.fromstring(current_svg_bytes)
    except ET.ParseError:
        raise ValueError('当前 SVG 无法解析。') from None
    viewbox = _svg_coordinates(root, width, height)
    before = _path_count(root)
    if work_dir is not None:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
    timings = {}
    with tempfile.TemporaryDirectory(prefix='local-refine-', dir=work_dir) as temporary:
        work = Path(temporary)
        crop_path = work/'original-crop.png'
        crop.save(crop_path)
        phase = time.perf_counter()
        record('local_refine_regions', limit=chosen['path_limit'])
        labels, records = prepare_regions(crop_path, chosen['path_limit'], '', record, params=params)
        timings['regions'] = time.perf_counter()-phase
        # Regions wholly in the context margin need no output geometry. Their
        # pixels still informed quantization and the traced shared boundaries.
        intersecting = set(map(int, np.unique(labels[selected])))
        records = [r for r in records if r['id'] in intersecting]
        phase = time.perf_counter()
        if records:
            record('local_refine_trace', regions=len(records), limit=chosen['path_limit'])
            trace_regions(labels, records, work/'raw.svg', params, record)
            normalize_svg(work/'raw.svg', work/'normalized.svg', crop.width, crop.height)
            simplify_svg(work/'normalized.svg', work/'simplified.svg', params['curve_tolerance'], record)
            patch = ET.parse(work/'simplified.svg').getroot()
        else:
            # Empty source pixels intentionally erase the old selected artwork.
            patch = ET.Element(NS+'svg', {'width':str(crop.width), 'height':str(crop.height)})
        timings['trace_and_simplify'] = time.perf_counter()-phase
        added = _path_count(patch)
        if added > chosen['path_limit']:
            raise ValueError('局部精修输出超过局部路径预算。')
        phase = time.perf_counter()
        root = _replace_selection(root, patch, points, box, viewbox, opaque_selection)
        svg = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        after = _path_count(root)
        timings['compose'] = time.perf_counter()-phase
    timings['total'] = time.perf_counter()-started
    report = {'operation':'local_refine', 'version':1, 'source_size':[width, height],
        'polygon':[list(point) for point in points], 'selection_rule':'evenodd',
        'selection_pixels':int(np.count_nonzero(selected)), 'crop_box':list(box),
        'context_margin':CONTEXT_MARGIN, 'options':chosen,
        'parameters':{key:value for key,value in params.items() if not key.startswith('_')},
        'before_paths':before, 'added_paths':added, 'after_paths':after,
        'local_budget':chosen['path_limit'], 'total_drawing_paths':after,
        'embedded_images':0, 'viewBox':viewbox, 'timings':timings,
        'opaque_backing':'whole_selection' if opaque_selection else 'none',
        'counting':'Retained old paths, including clipped portions, plus new local paths; clip polygons are not drawing paths.',
        'scope':'Original pixels only; outside the selected boundary antialias band, prior vector artwork is unchanged.'}
    record('local_refine_complete', added_paths=added, total_paths=after)
    return {'svg':svg, 'report':report}
