"""Connected-region budget + open-source Potrace, at the input resolution.

The budget is enforced before tracing and checked again on the emitted SVG.
Adjacent color-distance merges preserve region connectivity; disconnected islands are
never packed together merely to lower the reported path count.
"""
import heapq
import json
import os
from pathlib import Path
import shutil
import subprocess
import queue
import threading
import time

# Limit numerical-library threads in the isolated worker.
os.environ.setdefault('OMP_NUM_THREADS', '4')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '4')


def prepare_regions(input_path, budget, detail_region, record, scale=1, params=None):
    import cv2
    import numpy as np
    from PIL import Image
    from scipy import ndimage as ndi
    from sklearn.cluster import MiniBatchKMeans
    from skimage.measure import label
    from core import DEFAULTS, parse_detail_region

    settings = {**DEFAULTS, **(params or {})}
    palette_colors = settings['potrace_palette_colors']
    smoothing = settings['potrace_smoothing']
    min_area = settings['potrace_min_region_area']

    rgba = np.asarray(Image.open(input_path).convert('RGBA'))
    rgb = np.ascontiguousarray(rgba[:, :, :3])
    h, w = rgb.shape[:2]
    roi = parse_detail_region(detail_region)
    weight = np.ones((h, w), np.float32)
    if roi:
        x, y, rw, rh = roi
        if x + rw > w or y + rh > h:
            raise ValueError('细节优先区域超出规范化后图片范围，请检查 x,y,宽,高。')
        weight[y:y + rh, x:x + rw] = settings['potrace_detail_weight']
    visible = rgba[:, :, 3] > 0
    if not visible.any():
        return np.zeros((h, w), np.uint16), []
    # Never bridge transparent gaps to force disconnected islands into one fill.
    if not visible.all():
        _, islands = ndi.label(visible)
        if islands > budget:
            raise ValueError(f'图片包含 {islands} 个被透明背景分开的区域，无法在保持分离的同时限制为 {budget} 条填充路径。请提高上限。')

    cv2.setNumThreads(4)
    feature_map = None
    if settings.get('potrace_preserve_structure', False):
        from structure_features import detect_structure
        record('potrace_structure', current=0, total=3)
        # Use the normalized original when SR is enabled; synthesized detail
        # should not decide which source shapes deserve protection.
        source = settings.get('_structure_source')
        if source:
            with Image.open(source) as image:
                reference = np.asarray(image.convert('RGBA'))
        elif scale > 1:
            reference = np.asarray(Image.fromarray(rgba).resize(
                (max(1, round(w/scale)), max(1, round(h/scale))), Image.Resampling.BOX))
        else:
            reference = rgba
        feature_map = detect_structure(reference, min(256, max(8, budget//8)), record)
        if feature_map.shape != (h, w):
            feature_map = cv2.resize(feature_map, (w, h), interpolation=cv2.INTER_NEAREST)
        feature_map[~visible] = 0
        if not feature_map.any():
            feature_map = None
    record('potrace_palette')
    if smoothing:
        radius = max(1, round(2 * scale * smoothing))
        smooth = cv2.bilateralFilter(rgb, 2 * radius + 1, 18 * smoothing, 2 * scale * smoothing)
    else:
        smooth = rgb
    lab = cv2.cvtColor(smooth, cv2.COLOR_RGB2LAB)
    samples = lab[visible]
    rng = np.random.default_rng(42)
    samples = samples[rng.choice(len(samples), min(len(samples), 100000), replace=False)]

    def fit(values, count):
        count = min(count, len(np.unique(values, axis=0)))
        # A rare color can belong to an eye highlight or a thin contour.
        # Keep its initialized center instead of reseeding it into the majority.
        return MiniBatchKMeans(n_clusters=count, random_state=42, batch_size=4096,
                              n_init=3, max_iter=100,
                              reassignment_ratio=0).fit(values.astype('float32'))

    # Reserve about one third of the palette for the optional detail region.
    # The default 48 remains the original 32 global + 16 local centers.
    detail_colors = max(1, round(palette_colors / 3)) if roi else 0
    model = fit(samples, palette_colors - detail_colors)
    if roi:
        eye = lab[y:y + rh, x:x + rw][visible[y:y + rh, x:x + rw]]
        if len(eye):
            focus = fit(eye, detail_colors)
            model.cluster_centers_ = np.concatenate([model.cluster_centers_, focus.cluster_centers_])
            model.n_clusters = len(model.cluster_centers_)
    flat = lab.reshape(-1, 3)
    q = np.empty(h * w, np.uint16)
    for start in range(0, len(flat), 250000):
        q[start:start + 250000] = model.predict(flat[start:start + 250000].astype('float32'))
    # Alpha bins keep semitransparent and opaque regions distinct initially.
    keys = (q.reshape(h, w) + 1) * 17 + rgba[:, :, 3].astype('uint16') // 16
    if feature_map is not None:
        keys = keys.astype('int32') * (int(feature_map.max())+1) + feature_map
    keys[~visible] = 0
    comp = label(keys, background=0, connectivity=1).astype('int32')
    n = int(comp.max()) + 1
    areas = np.bincount(comp.ravel(), minlength=n).astype('int64')
    mass = np.bincount(comp.ravel(), weights=weight.ravel(), minlength=n)
    features = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype('float32')
    # With opaque images this adds a constant zero-cost alpha dimension.
    features = np.concatenate([features, rgba[:, :, 3:4].astype('float32')], axis=2)
    sums = np.stack([np.bincount(comp.ravel(), weights=(features[:, :, i] * weight).ravel(), minlength=n) for i in range(4)], axis=1)
    colorsums = np.stack([np.bincount(comp.ravel(), weights=(rgba[:, :, i] * weight).ravel(), minlength=n) for i in range(4)], axis=1)
    a = np.concatenate([comp[:, :-1].ravel(), comp[:-1, :].ravel()])
    b = np.concatenate([comp[:, 1:].ravel(), comp[1:, :].ravel()])
    different = (a != b) & (a > 0) & (b > 0)
    a, b = a[different], b[different]
    pairs = np.unique(np.minimum(a, b).astype('int64') * n + np.maximum(a, b))
    del a, b, different, features, lab, flat, q, keys, smooth, samples
    neighbors = [set() for _ in range(n)]
    for p in pairs:
        a, b = int(p // n), int(p % n)
        neighbors[a].add(b)
        neighbors[b].add(a)
    focus_ids = set(map(int, np.unique(comp[y:y + rh, x:x + rw]))) if roi else set()
    parent = np.arange(n)
    active = areas > 0
    active[0] = False
    revisions = np.zeros(n, np.int32)
    heap = []
    from merge_cost import MergeCosts
    feature_ids = ndi.maximum(feature_map, comp, index=np.arange(n)) if feature_map is not None else None
    costs = MergeCosts(mass, sums, areas, focus_ids, min_area, scale, feature_ids=feature_ids,
                       area_exponent=settings.get('_merge_area_exponent'))
    del feature_map

    def push(a, b):
        if a > b:
            a, b = b, a
        cost = costs.cost(a, b)
        small = costs.clean_small(a, b)
        heapq.heappush(heap, (0 if small else 1, cost, a, b, int(revisions[a]), int(revisions[b])))

    for p in pairs:
        push(int(p // n), int(p % n))
    count = int(active.sum())
    record('potrace_merge', regions=count, limit=budget)
    while heap and (count > budget or heap[0][0] == 0):
        _, _, a, b, va, vb = heapq.heappop(heap)
        if not (active[a] and active[b]) or revisions[a] != va or revisions[b] != vb or b not in neighbors[a]:
            continue
        if len(neighbors[a]) < len(neighbors[b]):
            a, b = b, a
        absorbed_neighbors = neighbors[b].copy()
        for c in neighbors[b]:
            neighbors[c].discard(b)
            if c != a: neighbors[c].add(a)
        neighbors[a].update(neighbors[b])
        neighbors[a].discard(a)
        neighbors[a].discard(b)
        union = neighbors[a]
        neighbors[b].clear()
        parent[b] = a
        active[b] = False
        areas[a] += areas[b]
        mass[a] += mass[b]
        sums[a] += sums[b]
        colorsums[a] += colorsums[b]
        revisions[b] += 1
        changed = costs.update(a, b, mass[a], sums[a], areas[a])
        if changed:
            revisions[a] += 1
        else:
            # Existing a-edges still have exactly the same priority. Only
            # former b-edges need new endpoints, avoiding quadratic churn
            # around a background with thousands of contrasting neighbors.
            union = absorbed_neighbors - {a, b}
        count -= 1
        for c in union:
            push(a, c)
        if count % 1000 == 0:
            # Retire invalid edges before they dominate memory and heap work.
            if len(heap) > max(10000, count * 12):
                heap[:] = [e for e in heap if active[e[2]] and active[e[3]] and revisions[e[2]] == e[4] and revisions[e[3]] == e[5]]
                heapq.heapify(heap)
            record('potrace_merge', regions=count, limit=budget)
    if count > budget:
        raise ValueError(f'仍有 {count} 个分离区域，不能满足 {budget} 条路径上限。')
    roots = parent.copy()
    while np.any(roots != roots[roots]):
        roots = roots[roots]
    ids = np.flatnonzero(active)
    lut = np.zeros(n, np.uint16)
    lut[ids] = np.arange(1, len(ids) + 1)
    regions = lut[roots[comp]]
    records = []
    for i, (root, sl) in enumerate(zip(ids, ndi.find_objects(regions)), 1):
        sy, sx = sl
        color = np.round(colorsums[root] / mass[root]).clip(0, 255).astype('uint8')
        records.append({'id':i, 'area':int(areas[root]), 'feature_id':costs.feature_id(root),
                        'bbox':[sx.start, sy.start, sx.stop, sy.stop], 'color':color.tolist()})
    return regions, records


def convert_potrace(input_path, output_path, params, record):
    scale=params.get('_spatial_scale',1)
    regions, records = prepare_regions(input_path, params['path_limit'], params['detail_region'], record, scale=scale, params=params)
    trace_regions(regions, records, output_path, params, record)


def trace_regions(regions, records, output_path, params, record):
    root = Path(__file__).resolve().parents[1]
    node = root / 'runtime' / 'node' / 'node.exe'
    if os.name != 'nt' or not node.is_file():
        executable = shutil.which('node')
        if not executable:
            raise ImportError('缺少 Potrace 所需的 Node.js 运行时。请完整解压程序。')
        node = Path(executable)
    if not (root / 'runtime/potrace/node_modules/potrace/package.json').is_file():
        raise ImportError('缺少 Potrace 依赖。请完整解压程序。')
    scale=params.get('_spatial_scale',1)
    work = Path(output_path).parent
    regions.astype('<u2').tofile(work / 'regions.bin')
    job = {'width':regions.shape[1], 'height':regions.shape[0], 'regions':records,
           'trace_threads':params.get('potrace_trace_threads',0),
           'limit':params['path_limit'], 'output':str(output_path), 'scale':scale,
           'trace_options':{key:params[key] for key in ('potrace_alpha_max','potrace_opt_tolerance',
               'potrace_opt_curve','potrace_turn_policy','potrace_turd_size','potrace_stroke_width') if key in params}}
    job_path = work / 'potrace.json'
    job_path.write_text(json.dumps(job), encoding='utf-8')
    record('potrace_trace', regions=len(records), limit=params['path_limit'])
    command = [str(node), str(Path(__file__).with_name('potrace_trace.cjs')), str(job_path)]
    updates = queue.Queue()
    deadline = time.monotonic() + (600 if scale>1 else 120)
    with (work / 'potrace-trace.log').open('wb') as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log, text=True,
                                   encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        def read_updates():
            for line in process.stdout:
                try: updates.put(json.loads(line))
                except ValueError: continue
        reader = threading.Thread(target=read_updates, daemon=True); reader.start()
        def forward():
            latest = None
            while True:
                try: latest = updates.get_nowait()
                except queue.Empty: break
            if latest and latest.get('stage') == 'potrace_trace':
                record('potrace_trace', **{k:latest[k] for k in ('current','total','threads')})
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise ValueError('Potrace 曲线描摹超时。请缩小图片后重试。')
                forward();time.sleep(.1)
            reader.join();forward()
        finally:
            if process.poll() is None: process.kill()
            process.wait();reader.join();process.stdout.close()
    if process.returncode:
        detail = (work / 'potrace-trace.log').read_text(encoding='utf-8', errors='replace')
        raise ValueError('Potrace 曲线描摹失败：' + detail[-1200:])
