"""Independent local budgeted Potrace illustration conversion."""
import io
import json
import math
import platform
import re
from importlib.metadata import version, PackageNotFoundError
from fractions import Fraction
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
import warnings
import xml.etree.ElementTree as ET
from status_io import forward_progress

MAX_INPUT = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_PROCESSED_PIXELS = 160_000_000
RETIRED_ENGINE_FIELDS = frozenset(('colormode','hierarchical','mode','filter_speckle',
    'color_precision','layer_difference','corner_threshold','length_threshold',
    'max_iterations','splice_threshold','path_precision'))
SCHEMA = {
    'engine': {'default':'potrace', 'choices':['potrace'], 'label':'转换算法'},
    'crop_ratio': {'default':'', 'section':'crop', 'label':'裁剪宽高比'},
    'crop_x': {'default':50, 'min':0, 'max':100, 'step':1, 'section':'crop', 'label':'水平位置'},
    'crop_y': {'default':50, 'min':0, 'max':100, 'step':1, 'section':'crop', 'label':'垂直位置'},
    'crop_rect': {'default':'', 'section':'crop', 'label':'精确裁剪区域'},
    'sr_enabled': {'default':False, 'type':'boolean', 'section':'preprocess', 'label':'超分辨率预处理'},
    'sr_scale': {'default':2, 'choices':[2,4], 'section':'preprocess', 'label':'超分辨率倍数'},
    'curve_simplify': {'default':False, 'type':'boolean', 'section':'postprocess', 'label':'曲线简化'},
    'curve_tolerance': {'default':0.3, 'min':0.1, 'max':2.0, 'step':0.1, 'section':'postprocess', 'label':'简化容差（原图像素）'},
    'simplify_target_paths': {'default':0, 'min':0, 'max':20000, 'step':1, 'section':'postprocess', 'engine':'potrace', 'label':'目标色块数量（0 保持不变）'},
    'diffvg_optimize': {'default':False, 'type':'boolean', 'section':'postprocess', 'label':'DiffVG 全图优化'},
    'diffvg_iterations': {'default':30, 'min':1, 'max':100, 'step':1, 'section':'postprocess', 'label':'全图优化轮数'},
    'highres_refine': {'default':False, 'type':'boolean', 'section':'postprocess', 'label':'高分辨率补充优化'},
    'path_limit': {'default':2500, 'min':1, 'max':20000, 'step':1, 'label':'填充路径数量上限', 'engine':'potrace'},
    'detail_region': {'default':'', 'label':'细节优先区域（可选）', 'engine':'potrace'},
    'potrace_trace_threads': {'default':0, 'min':0, 'max':16, 'step':1, 'label':'描摹线程数（0 自动）', 'engine':'potrace', 'group':'potrace_trace'},
    'potrace_alpha_max': {'default':1.0, 'min':0.0, 'max':1.5, 'step':0.1, 'label':'角点阈值', 'engine':'potrace', 'group':'potrace_trace'},
    'potrace_opt_curve': {'default':True, 'type':'boolean', 'label':'内部曲线合并', 'engine':'potrace', 'group':'potrace_trace'},
    'potrace_opt_tolerance': {'default':0.4, 'min':0.0, 'max':2.0, 'step':0.05, 'label':'曲线合并容差（像素）', 'engine':'potrace', 'group':'potrace_trace'},
    'potrace_turn_policy': {'default':'minority', 'choices':['minority','majority','black','white','left','right'], 'label':'边界连接策略', 'engine':'potrace', 'group':'potrace_trace'},
    'potrace_turd_size': {'default':0, 'min':0, 'max':100, 'step':1, 'label':'小轮廓删除阈值（像素面积）', 'engine':'potrace', 'group':'potrace_trace'},
    'potrace_palette_colors': {'default':48, 'min':2, 'max':256, 'step':1, 'label':'初始分色数量', 'engine':'potrace', 'group':'potrace_regions'},
    'potrace_preserve_structure': {'default':False, 'type':'boolean', 'label':'插画结构保护（实验）', 'engine':'potrace', 'group':'potrace_regions'},
    'potrace_smoothing': {'default':1.0, 'min':0.0, 'max':3.0, 'step':0.1, 'label':'预平滑强度', 'engine':'potrace', 'group':'potrace_regions'},
    'potrace_min_region_area': {'default':16, 'min':0, 'max':1024, 'step':1, 'label':'近色小块清理（像素面积）', 'engine':'potrace', 'group':'potrace_regions'},
    'potrace_detail_weight': {'default':15, 'min':1, 'max':50, 'step':1, 'label':'细节区域权重', 'engine':'potrace', 'group':'potrace_regions'},
    'potrace_stroke_width': {'default':1.0, 'min':0.0, 'max':3.0, 'step':0.1, 'label':'边界描边宽度（像素）', 'engine':'potrace', 'group':'potrace_regions'},
    'output_directory': {'default':'', 'label':'输出目录'},
}
LEGACY_DEFAULTS = {k:v['default'] for k,v in SCHEMA.items()}
LEGACY_DEFAULTS['illustration_profile'] = 'legacy'
from illustration_profiles import PROFILE_LABELS, PROFILE_PRESETS, is_illustration
SCHEMA['illustration_profile'] = {'default':'edge_clean', 'choices':list(PROFILE_LABELS),
                                'label':'插画重构方案', 'engine':'potrace'}
for _key, _value in PROFILE_PRESETS['edge_clean'].items():
    SCHEMA[_key]['default'] = _value
SCHEMA['path_limit']['label'] = '绘制路径总上限（含补线）'
SCHEMA['simplify_target_paths']['label'] = '目标绘制路径数（0 保持不变）'
DEFAULTS = {k:v['default'] for k,v in SCHEMA.items()}

def config_base(config):
    # Pre-profile configurations must not silently acquire a different engine,
    # palette or curve simplification policy when opened in the new version.
    legacy_fields = {k for k,s in SCHEMA.items() if s.get('engine')}
    old = 'illustration_profile' not in config and ('engine' in config or bool(legacy_fields & config.keys()))
    result = dict(LEGACY_DEFAULTS if old else DEFAULTS)
    if not old and isinstance(config.get('illustration_profile'),str):
        result.update(PROFILE_PRESETS.get(config['illustration_profile'],{}))
    return result

def validate(config):
    if not isinstance(config, dict):
        raise ValueError('配置必须是 JSON 对象。')
    retired = RETIRED_ENGINE_FIELDS.intersection(config)
    if config.get('engine') == 'vtracer' or (retired and config.get('engine') != 'potrace' and 'illustration_profile' not in config):
        raise ValueError('VTracer 支持已移除，请选择 Potrace 重构方案后重新设置参数。')
    # Older full Potrace exports contained inactive fields for the other engine.
    # Discard only those known dormant fields; all other unknown keys still fail.
    config = {k:v for k,v in config.items() if k not in retired}
    unknown = set(config) - set(SCHEMA)
    if unknown:
        raise ValueError('未知配置项：' + ', '.join(sorted(unknown)))
    result = config_base(config)
    for key, value in config.items():
        spec = SCHEMA[key]
        if spec.get('type') == 'boolean':
            if type(value) is not bool:
                raise ValueError(key + ' 必须是布尔值。')
        elif 'choices' in spec:
            if value not in spec['choices']:
                raise ValueError(key + ' 不在支持的选项内。')
            if key == 'sr_scale':
                value = int(value)
        elif key == 'detail_region':
            parse_detail_region(value)
        elif key == 'crop_ratio':
            parse_crop_ratio(value)
        elif key == 'crop_rect':
            parse_crop_rect(value)
        elif key == 'output_directory':
            if not isinstance(value, str) or len(value) > 4096 or '\x00' in value:
                raise ValueError('输出目录无效。')
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(key + ' 必须是有限数值。')
            if not spec['min'] <= value <= spec['max']:
                raise ValueError(f"{key} 必须在 {spec['min']}–{spec['max']} 范围内。")
            if spec['step'] == 1:
                if value != int(value):
                    raise ValueError(key + ' 必须是整数。')
                value = int(value)
            elif abs(value / spec['step'] - round(value / spec['step'])) > 1e-8:
                raise ValueError(f"{key} 的步长为 {spec['step']}。")
        result[key] = value
    if 'highres_refine' not in config:
        result['highres_refine'] = result['sr_enabled'] and not (is_illustration(result) and result['illustration_profile'] in ('flat_layers','gradient_layers'))
    if result['highres_refine'] and not result['sr_enabled']:
        raise ValueError('高分辨率补充优化需要先启用超分辨率预处理。')
    if is_illustration(result) and result['illustration_profile'] in ('flat_layers','gradient_layers') and (result['diffvg_optimize'] or result['highres_refine']):
        raise ValueError('分层方案的描线和渐变暂不支持 DiffVG 优化；请关闭全图/高分辨率补充优化，或改用边缘清理。超分辨率预处理仍可使用。')
    return result


def parse_detail_region(value):
    if not isinstance(value, str):
        raise ValueError('细节优先区域须为空或 x,y,宽,高。')
    if not value.strip():
        return None
    if not re.fullmatch(r'\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*', value):
        raise ValueError('细节优先区域格式为 x,y,宽,高，使用原图像素整数。')
    x, y, w, h = map(int, value.split(','))
    if min(w, h) < 1 or max(x, y, w, h) > MAX_PIXELS:
        raise ValueError('细节优先区域的宽高必须大于 0，坐标不能超出图片。')
    return x, y, w, h

def parse_crop_ratio(value):
    if value == '':
        return None
    part = r'([0-9]{1,6}(?:\.[0-9]{1,3})?)'
    match = re.fullmatch(rf'\s*{part}\s*[:：]\s*{part}\s*', value) if isinstance(value, str) else None
    if not match or min(Fraction(term) for term in match.groups()) <= 0:
        raise ValueError('裁剪比例须为两个正数，例如 5:4 或 2.35:1，最多六位整数和三位小数。')
    return Fraction(match[1]) / Fraction(match[2])

def parse_crop_rect(value):
    """An optional exact rectangle in EXIF-normalized original-image pixels."""
    if not isinstance(value, str):
        raise ValueError('精确裁剪区域必须为空字符串或 x,y,宽,高。')
    if not value.strip():
        return None
    if not re.fullmatch(r'\s*[0-9]+\s*,\s*[0-9]+\s*,\s*[0-9]+\s*,\s*[0-9]+\s*', value):
        raise ValueError('精确裁剪区域格式为 x,y,宽,高，使用原图非负整数坐标。')
    x, y, w, h = map(int, value.split(','))
    if min(w, h) < 1 or max(x, y, w, h) > MAX_PIXELS:
        raise ValueError('精确裁剪区域宽高必须大于 0，坐标不能超出图片范围。')
    return x, y, w, h


def crop_box(size, config):
    width, height = size
    exact = parse_crop_rect(config.get('crop_rect', ''))
    if exact is not None:
        x, y, w, h = exact
        if x+w > width or y+h > height:
            raise ValueError(f'精确裁剪区域超出 {width} × {height} 原图范围，请重新选择裁剪区域。')
        return x, y, x+w, y+h
    ratio = parse_crop_ratio(config['crop_ratio'])
    if ratio is None:
        return None
    units = min(width // ratio.numerator, height // ratio.denominator)
    if not units:
        raise ValueError(f'图片为 {width} × {height} 像素，无法按此比例裁出整数像素，请更换比例。')
    w, h = units * ratio.numerator, units * ratio.denominator
    x = ((width - w) * config['crop_x'] + 50) // 100
    y = ((height - h) * config['crop_y'] + 50) // 100
    return x, y, x + w, y + h

def decode_image(data):
    from PIL import Image, ImageOps
    if not data or len(data) > MAX_INPUT:
        raise ValueError('图片不能为空，且不能超过 20 MiB。')
    # Check our input budget explicitly before decoding. Turning Pillow's
    # warning threshold into an exception used to reject ordinary large images
    # with an English "decompression bomb" message before this check ran.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP', 'BMP', 'TIFF', 'GIF'):
                    raise ValueError('支持 PNG、JPEG、WebP、BMP、TIFF、GIF 图片。')
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError(f'图片为 {image.width} × {image.height}（{image.width * image.height:,} 像素），超过 4000 万输入像素上限。')
                image.seek(0)
                return ImageOps.exif_transpose(image).convert('RGBA')
        except Image.DecompressionBombError:
            raise ValueError('图片尺寸过大，超过 4000 万输入像素上限。请缩小输入图片。') from None

def normalize_image(data, destination, config=None):
    image = decode_image(data)
    size = image.size
    box = crop_box(size, config) if config else None
    if box:
        image = image.crop(box)
    image.save(destination, 'PNG')
    return size, box

def cropped_detail_region(value, size, box):
    # Existing detail regions refer to the oriented, full-size original.
    x, y, w, h = parse_detail_region(value)
    if x + w > size[0] or y + h > size[1]:
        raise ValueError('细节优先区域超出原图范围。')
    left, top = max(x, box[0]), max(y, box[1])
    right, bottom = min(x + w, box[2]), min(y + h, box[3])
    if right <= left or bottom <= top:
        raise ValueError('细节优先区域位于裁剪框外，请移动裁剪框或修改细节区域。')
    return f'{left-box[0]},{top-box[1]},{right-left},{bottom-top}'

def runtime_info():
    packages = {}
    for name in ('Pillow', 'numpy', 'scipy', 'scikit-learn', 'scikit-image', 'opencv-python-headless'):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = 'missing'
    return {'python':platform.python_version(), 'platform':platform.system(),
            'machine':platform.machine(), 'packages':packages}

def sanitized_detail(value, work=None):
    value = str(value)
    for path in (str(work) if work else '', str(Path.home()), str(Path(__file__).resolve().parent.parent)):
        if path:
            value = value.replace(path, '<local>')
    # Windows and POSIX absolute paths in traceback lines can contain user names.
    value = re.sub(r'File "[^"\n]+"', 'File "<local>"', value)
    value = ''.join(c for c in value if c in '\n\t' or ord(c) >= 32)
    return value[-2400:]

def worker(job_path):
    import faulthandler
    faulthandler.enable()
    job = json.loads(Path(job_path).read_text(encoding='utf-8'))
    if job.get('managed'):
        import time
        while not Path(job_path).with_suffix('.start').exists():
            time.sleep(.02)
    status = Path(job_path).with_suffix('.status.json')
    from status_io import write_json_atomic
    def record(stage, **extra):
        write_json_atomic(status, {'stage':stage, **extra}, optional=True)
    record('import_engine')
    try:
        params = validate(job['config'])
        params.pop('output_directory')
        if is_illustration(params) or any(params[k] for k in ('sr_enabled','curve_simplify','diffvg_optimize','highres_refine')):
            from pipeline import run_pipeline
            run_pipeline(job, params, record)
            record('complete')
            return
        from potrace_engine import convert_potrace
        convert_potrace(job['input'], job['output'], params, record)
        record('complete')
    except BaseException as error:
        # Preserve diagnostics for process-level Python failures as well.
        record('error', kind=type(error).__name__, detail=sanitized_detail(error, Path(job_path).parent))
        raise

def worker_failure(returncode, detail, status):
    code = f'{returncode} (0x{returncode & 0xffffffff:08X})'
    kind = status.get('kind', '')
    detail = detail.strip()
    if kind in ('ImportError', 'ModuleNotFoundError') or 'DLL load failed' in detail or 'No module named' in detail:
        summary = '转换引擎依赖加载失败。请完整解压程序包，不要只复制启动文件。'
    elif status.get('stage') == 'error':
        summary = '转换引擎处理失败（没有自动修改参数）。'
    elif returncode:
        summary = '转换子进程异常退出，尚不能判定为参数问题（没有自动修改参数）。'
    else:
        summary = '转换引擎未生成 SVG 文件（没有自动修改参数）。'
    hint = {0xC0000005:'Windows 内存访问异常', 0xC000001D:'CPU 指令不兼容',
            0xC0000135:'Windows 找不到依赖 DLL', 0xC000007B:'Windows 二进制架构或映像无效',
            0xC0000409:'Windows 快速失败/安全检查终止'}.get(returncode & 0xffffffff)
    summary += f'\n退出码：{code}；阶段：{status.get("stage", "worker_not_started")}。'
    if hint:
        summary += '\n系统状态：' + hint + '（需结合诊断进一步确认原因）。'
    if detail:
        summary += '\n引擎信息：' + detail
    else:
        summary += '\n子进程没有输出错误文本。请运行引擎自检并保留此退出码。'
    return summary

def self_test():
    checks = []
    try:
        from PIL import Image, ImageDraw
        image = Image.new('RGBA', (48, 32), 'white')
        ImageDraw.Draw(image).ellipse((5, 4, 38, 28), fill='#257acc')
        data = io.BytesIO()
        image.save(data, 'PNG')
        with tempfile.TemporaryDirectory(prefix='image-vector-selftest-') as directory:
            for profile in PROFILE_LABELS:
                result = convert(data.getvalue(), 'selftest.png', {'illustration_profile':profile, 'path_limit':16, 'output_directory':directory})
                checks.append({'profile':profile, 'ok':True, 'paths':result['stats']['drawing_paths'], 'bytes':len(result['svg'])})
        return {'ok':True, 'checks':checks, 'runtime':runtime_info()}
    except Exception as error:
        return {'ok':False, 'checks':checks, 'runtime':runtime_info(), 'error':sanitized_detail(error)}

def save_svg_result(destination, svg, pipeline=None):
    """Write a new SVG/report pair; remove only our new files on failure."""
    destination = Path(destination)
    created = []
    try:
        with destination.open('xb') as target:
            created.append(destination)
            target.write(svg)
        if pipeline is not None:
            sidecar = destination.with_suffix('.pipeline.json')
            with sidecar.open('x', encoding='utf-8') as target:
                created.append(sidecar)
                json.dump(pipeline, target, ensure_ascii=False, indent=2)
    except Exception:
        for item in created:
            item.unlink(missing_ok=True)
        raise


def convert(data, name, config, progress=None, control=None):
    if control: control.check()
    config = validate(config)
    output_text = config['output_directory']
    output_dir = Path(output_text) if output_text else Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory(prefix='image-vector-job-') as work:
        work = Path(work)
        normalized = work / 'input.png'
        if progress:
            progress('normalizing')
        source_size, box = normalize_image(data, normalized, config)
        worker_config = config.copy()
        if box and config['detail_region'].strip():
            worker_config['detail_region'] = cropped_detail_region(config['detail_region'], source_size, box)
        if control: control.check()
        from PIL import Image
        with Image.open(normalized) as image:
            width, height = image.size
        if config['sr_enabled'] and width * height * config['sr_scale'] ** 2 > MAX_PROCESSED_PIXELS:
            raise ValueError('超分辨率输出超过 1.6 亿像素，请降低倍数或缩小输入图片。')
        svg_path = work / 'output.svg'
        job = work / 'job.json'
        job.write_text(json.dumps({'input':str(normalized), 'output':str(svg_path), 'config':worker_config, 'managed':control is not None}), encoding='utf-8')
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command.extend(['-u', '-X', 'faulthandler', str(Path(__file__).with_name('main.py'))])
        command += ['--worker', str(job)]
        enhanced = is_illustration(config) or any(config[k] for k in ('sr_enabled','curve_simplify','diffvg_optimize','highres_refine'))
        timeout = 10800 if any(config[k] for k in ('sr_enabled','diffvg_optimize','highres_refine')) else (2700 if enhanced else 1200)
        with forward_progress(job.with_suffix('.status.json'), progress), (work / 'worker.log').open('wb') as log:
            try:
                if control:
                    from task_control import run_managed
                    process = run_managed(command, log, timeout, control, job.with_suffix('.start'))
                else:
                    process = subprocess.run(command, stdout=log, stderr=log, timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired:
                raise ValueError(f'转换超过 {timeout} 秒，子进程已终止（没有自动修改参数）。请缩小图片后重试，或运行引擎自检。') from None
            except OSError as error:
                raise ValueError('无法启动转换子进程：' + sanitized_detail(error, work)) from None
        if process.returncode != 0 or not svg_path.exists():
            detail = sanitized_detail((work / 'worker.log').read_text(encoding='utf-8', errors='replace'), work)
            try:
                status = json.loads(job.with_suffix('.status.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                status = {}
            if status.get('stage') == 'error' and status.get('detail'):
                detail = status.get('kind', 'Error') + ': ' + status['detail']
            raise ValueError(worker_failure(process.returncode, detail, status))
        if svg_path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('SVG 超过 64 MiB；请缩小图片或提高杂点过滤。')
        svg = svg_path.read_bytes()
        if b'<svg' not in svg[:1024]:
            raise ValueError('转换引擎未生成有效 SVG。')
        root = ET.fromstring(svg)
        paths = [e for e in root.iter() if e.tag.rsplit('}', 1)[-1] == 'path']
        commands = ''.join(e.get('d', '') for e in paths)
        stats = {'engine':config['engine'], 'paths':len(paths),
                 'subpaths':len(re.findall('[Mm]', commands)),
                 'segments':len(re.findall('[LlHhVvCcSsQqTtAa]', commands))}
        if enhanced:
            from drawing_stats import drawing_counts
            geometry = drawing_counts(svg_path)
            stats.update(geometry)
            stats['segments'] = geometry['total_segments']
            stats['subpaths'] = geometry['contours']
        stats['drawing_paths'] = len(paths)
        stats['stroke_paths'] = sum(e.get('fill') == 'none' for e in paths)
        stats['illustration_profile'] = config['illustration_profile']
        stats['gradient_count'] = sum(e.tag.rsplit('}', 1)[-1] in ('linearGradient','radialGradient') for e in root.iter())
        if len(paths) > config['path_limit']:
            raise ValueError('Potrace 输出超过填充路径数量上限，未保存文件。')
        if config['curve_simplify'] and config['simplify_target_paths'] and len(paths) > config['simplify_target_paths']:
            raise ValueError('后处理输出超过目标色块数量，未保存文件。')
        report_path = work / 'pipeline_report.json'
        pipeline = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else None
        if pipeline is not None:
            if box:
                pipeline['config']['detail_region'] = config['detail_region']
                pipeline['crop_box'] = box
                pipeline['uncropped_size'] = source_size
        if control: control.begin_save()
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = ''.join(c if c.isalnum() or c in '-_' else '_' for c in Path(name).stem)[:60] or 'image'
        destination = output_dir / (stem + '_' + uuid.uuid4().hex + '.svg')
        save_svg_result(destination, svg, pipeline)
        processed = work / 'processed.png'
        if progress:
            progress('complete')
        return {'path':str(destination.resolve()), 'svg':svg, 'config':config,
                'original':normalized.read_bytes(), 'processed':processed.read_bytes() if processed.exists() else None,
                'processed_available':processed.exists(), 'pipeline':pipeline,
                'width':width, 'height':height, 'stats':stats}
