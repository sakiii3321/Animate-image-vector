"""Real-ESRGAN compact anime model, padded tiled inference with preserved alpha."""
from pathlib import Path
import gc
import time

MAX_SR_PIXELS = 160_000_000


def preferred_device(torch):
    """GPU is preferred; a broken CUDA probe must not disable CPU inference."""
    try:
        if torch.cuda.is_available():
            return {'backend': 'cuda', 'device': torch.cuda.get_device_name(0), 'fallback_reason': ''}
        reason = '未检测到可用的 NVIDIA CUDA GPU，使用 CPU。'
    except (RuntimeError, AssertionError, OSError) as error:
        reason = 'CUDA 初始化不可用，使用 CPU：' + str(error)[:600]
    return {'backend': 'cpu', 'device': 'CPU', 'fallback_reason': reason}


def _infer(model, rgb, scale, backend, record, started, fallback_reason=''):
    """One complete device attempt; no output file is written until it succeeds."""
    import torch
    from PIL import Image
    h, w = rgb.shape[:2]
    dtype = torch.float16 if backend == 'cuda' else torch.float32
    model = model.to(device=backend, dtype=dtype)
    result = Image.new('RGB', (w * scale, h * scale))
    tile, pad = 256, 24
    total = ((w + tile - 1) // tile) * ((h + tile - 1) // tile)
    done = 0
    device_details = {'device': backend, 'fallback_reason': fallback_reason}
    record('sr_inference', done=0, current=0, total=total, scale=scale,
           width=w * scale, height=h * scale, **device_details)
    with torch.inference_mode():
        for y in range(0, h, tile):
            for x in range(0, w, tile):
                right, bottom = min(x + tile, w), min(y + tile, h)
                px0, py0 = max(0, x-pad), max(0, y-pad)
                px1, py1 = min(w, right+pad), min(h, bottom+pad)
                inp = torch.from_numpy(rgb[py0:py1, px0:px1].copy()).permute(2, 0, 1).unsqueeze(0).to(device=backend, dtype=dtype) / 255
                pred = model(inp).clamp(0, 1)
                pixels = (pred[0].float().cpu().permute(1, 2, 0).numpy()*255).round().astype('uint8')
                patch = Image.fromarray(pixels)
                if scale != 4:
                    patch = patch.resize(((px1-px0)*scale, (py1-py0)*scale), Image.Resampling.LANCZOS)
                patch = patch.crop(((x-px0)*scale, (y-py0)*scale, (right-px0)*scale, (bottom-py0)*scale))
                result.paste(patch, (x*scale, y*scale))
                done += 1
                record('sr_inference', done=done, current=done, total=total, scale=scale,
                       elapsed_seconds=round(time.perf_counter()-started, 2), **device_details)
                del inp, pred, pixels, patch
    return result, done


def run(job, record):
    import numpy as np
    import torch
    from PIL import Image
    from srvgg_arch import SRVGGNetCompact
    started = time.perf_counter()
    scale = job['config'].get('sr_scale', 2)
    if isinstance(scale, bool) or scale not in (2, 4):
        raise ValueError('超分辨率倍数必须为 2 或 4。')
    scale = int(scale)
    with Image.open(job['input']) as image:
        source = image.convert('RGBA')
    w, h = source.size
    if w * h * scale * scale > MAX_SR_PIXELS:
        raise ValueError('超分输出不能超过 1.6 亿像素，请降低倍数或缩小原图。')
    # Alpha is resampled independently, never discarded or treated as RGB.
    rgb = np.asarray(source.convert('RGB'))
    alpha = source.getchannel('A')
    torch.set_num_threads(4)
    torch.manual_seed(42)
    torch.backends.cudnn.benchmark = False
    selected = preferred_device(torch)
    backend = selected['backend']
    fallback_reason = selected['fallback_reason']
    attempted_devices = [backend]
    model_dir = Path(__file__).resolve().parents[1] / 'runtime' / 'enhancement' / 'sr'
    checkpoint = torch.load(model_dir / 'realesr-animevideov3.pth', map_location='cpu', weights_only=True)
    state = checkpoint.get('params_ema', checkpoint.get('params'))
    def load_model():
        model = SRVGGNetCompact(3, 3, 64, 16, 4, 'prelu')
        model.load_state_dict(state, strict=True)
        return model.eval()
    # Validate model weights before the CUDA retry scope. Corrupt models and file
    # errors must remain errors, rather than masquerading as GPU incompatibility.
    model = load_model()
    tile, pad = 256, 24
    if backend == 'cuda':
        try:
            result, done = _infer(model, rgb, scale, backend, record, started)
        except (RuntimeError, AssertionError) as error:
            fallback_reason = 'GPU 超分执行失败，已改用 CPU 重新处理：' + str(error)[:600]
            backend = 'cpu'
        if backend == 'cpu':
            # Leave the except block first so its traceback releases CUDA tensors.
            # Reload original FP32 weights, not a half-precision model copied back.
            model = None
            gc.collect()
            try:
                torch.cuda.empty_cache()
            except (RuntimeError, AssertionError):
                pass  # CPU inference does not require a healthy CUDA context.
            attempted_devices.append('cpu')
            record('sr_cpu_fallback', device='cpu', fallback_reason=fallback_reason)
            model = load_model()
            result, done = _infer(model, rgb, scale, backend, record, started, fallback_reason)
    else:
        record('sr_cpu_fallback', device='cpu', fallback_reason=fallback_reason)
        result, done = _infer(model, rgb, scale, backend, record, started, fallback_reason)
    result.putalpha(alpha.resize(result.size, Image.Resampling.LANCZOS))
    destination = Path(job['output']);destination.parent.mkdir(parents=True, exist_ok=True)
    result.save(destination, 'PNG')
    return {'stage': 'super_resolution', 'model': 'Real-ESRGAN AnimeVideo-v3',
            'scale': scale, 'input_size': [w, h], 'output_size': list(result.size),
            'width': result.width, 'height': result.height,
            'device_policy': 'prefer_cuda', 'backend': backend,
            'device': selected['device'] if backend == 'cuda' else 'CPU',
            'attempted_devices': attempted_devices, 'fallback_reason': fallback_reason,
            'precision': 'torch.float16' if backend == 'cuda' else 'torch.float32',
            'tile': tile, 'pad': pad, 'tiles': done,
            'alpha': 'independently resampled with Lanczos',
            'elapsed_seconds': time.perf_counter()-started}
