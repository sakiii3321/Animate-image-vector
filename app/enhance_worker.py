"""Python 3.12 enhancement entry point, isolated from the conversion worker."""
import faulthandler
import json
from pathlib import Path
import sys
import traceback
from status_io import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'runtime' / 'enhancement'
sys.path[:0] = [str(RUNTIME / 'diffvg'), str(RUNTIME / 'pydeps'), str(RUNTIME / 'sr')]


def probe():
    result = {'sr': {'available': False}, 'diffvg': {'available': False}, 'python_version': sys.version.split()[0]}
    try:
        import torch
        import numpy
        from PIL import Image
        result['torch'] = torch.__version__
        from enhance_sr import preferred_device
        selected = preferred_device(torch)
        result['sr_device'] = selected['device']
        result['diffvg_device'] = 'CPU'
        try:
            from srvgg_arch import SRVGGNetCompact
            checkpoint = torch.load(RUNTIME / 'sr' / 'realesr-animevideov3.pth', map_location='cpu', weights_only=True)
            model = SRVGGNetCompact(3, 3, 64, 16, 4, 'prelu')
            model.load_state_dict(checkpoint.get('params_ema', checkpoint.get('params')), strict=True)
            result['sr'] = {'available': True, 'reason': '', 'model': 'Real-ESRGAN AnimeVideo-v3',
                            'scales': [2, 4], 'device_policy': 'prefer_cuda', **selected}
        except Exception as error:
            result['sr']['reason'] = str(error)
        try:
            import pydiffvg
            pydiffvg.set_use_gpu(False)
            result['diffvg'] = {'available': True, 'reason': '', 'device': 'CPU'}
        except Exception as error:
            result['diffvg']['reason'] = str(error)
    except Exception as error:
        for key in ('sr', 'diffvg'):
            result[key]['reason'] = str(error)
    return result


def main():
    faulthandler.enable()
    if sys.argv[1:] == ['--probe']:
        print(json.dumps(probe(), ensure_ascii=False), flush=True)
        return
    job = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
    def record(stage, **details):
        write_json_atomic(job['status'], {'stage': stage, **details}, optional=True)
    try:
        if job['action'] == 'super_resolution':
            from enhance_sr import run
        elif job['action'] == 'optimize':
            from enhance_optimize import run
        else:
            raise ValueError('Unsupported enhancement action')
        result = run(job, record)
        write_json_atomic(job['result'], result)
        record('enhancement_complete', action=job['action'])
    except BaseException as error:
        record('enhancement_error', kind=type(error).__name__, detail=str(error))
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == '__main__':
    main()
