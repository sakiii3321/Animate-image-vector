"""Isolated, cancellable local refinement and explicit version saving."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

from core import sanitized_detail, worker_failure, save_svg_result
from status_io import forward_progress

MAX_SVG_BYTES = 64 * 1024 * 1024


def worker(job_path):
    import faulthandler
    import time
    from status_io import write_json_atomic
    faulthandler.enable()
    job_path = Path(job_path)
    job = json.loads(job_path.read_text(encoding='utf-8'))
    if job.get('managed'):
        while not job_path.with_suffix('.start').exists():
            time.sleep(.02)
    def record(stage, **extra):
        write_json_atomic(job_path.with_suffix('.status.json'), {'stage':stage, **extra}, optional=True)
    try:
        record('refine_prepare')
        from local_refine import refine_selection
        result = refine_selection(Path(job['original']).read_bytes(), Path(job['current']).read_bytes(),
                                  job['polygon'], job.get('options', {}),
                                  work_dir=job_path.parent, record=record)
        Path(job['output']).write_bytes(result['svg'])
        Path(job['report']).write_text(json.dumps(result['report'], ensure_ascii=False, indent=2), encoding='utf-8')
        record('refine_complete')
    except BaseException as error:
        record('error', kind=type(error).__name__, detail=sanitized_detail(error, job_path.parent))
        raise


def run_refinement(current, polygon, options, progress=None, control=None):
    """Return an unsaved result patch; the current result is never mutated."""
    from drawing_stats import drawing_counts
    if control:
        control.check()
    with tempfile.TemporaryDirectory(prefix='image-vector-refine-') as directory:
        work = Path(directory)
        original, source = work/'original.png', work/'current.svg'
        original.write_bytes(current['original'])
        source.write_bytes(current['svg'])
        output, report_path = work/'candidate.svg', work/'report.json'
        job_path = work/'job.json'
        job_path.write_text(json.dumps({'original':str(original), 'current':str(source),
            'output':str(output), 'report':str(report_path), 'polygon':polygon, 'options':options,
            'managed':control is not None}), encoding='utf-8')
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command += ['-u', '-X', 'faulthandler', str(Path(__file__).with_name('main.py'))]
        command += ['--refine-worker', str(job_path)]
        with forward_progress(job_path.with_suffix('.status.json'), progress), (work/'worker.log').open('wb') as log:
            try:
                if control:
                    from task_control import run_managed
                    process = run_managed(command, log, 1200, control, job_path.with_suffix('.start'))
                else:
                    process = subprocess.run(command, stdout=log, stderr=log, timeout=1200,
                                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired:
                raise ValueError('局部精修超时，原结果未改变；请缩小圈选范围或降低局部路径预算。') from None
            except OSError as error:
                raise ValueError('无法启动局部精修：'+sanitized_detail(error, work)) from None
        if process.returncode or not output.is_file() or not report_path.is_file():
            detail = sanitized_detail((work/'worker.log').read_text(encoding='utf-8', errors='replace'), work)
            try:
                state = json.loads(job_path.with_suffix('.status.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                state = {}
            if state.get('detail'):
                detail = state['detail']
            raise ValueError(worker_failure(process.returncode, detail, state))
        if output.stat().st_size > MAX_SVG_BYTES:
            raise ValueError('精修后的 SVG 超过 64 MiB，原结果未改变；请减少局部路径预算。')
        svg = output.read_bytes()
        root = ET.fromstring(svg)
        counts = drawing_counts(output)
        if counts['embedded_images']:
            raise ValueError('局部精修必须生成纯矢量结果。')
        report = json.loads(report_path.read_text(encoding='utf-8'))
        stats = {**current['stats'], **counts, 'paths':counts['drawing_paths'],
                 'segments':counts['total_segments'], 'subpaths':counts['contours'],
                 'gradient_count':sum(e.tag.rsplit('}',1)[-1] in ('linearGradient','radialGradient') for e in root.iter())}
        pipeline = copy.deepcopy(current.get('pipeline') or {'config':current['config'],
            'source_size':[current['width'], current['height']], 'stages':[]})
        pipeline.setdefault('stages', []).append({'stage':'local_refine', 'report':report})
        pipeline['final_counts'] = counts
        pipeline['refinement_count'] = current.get('refinement_count', 0) + 1
        if control:
            control.check()
        return {'svg':svg, 'stats':stats, 'pipeline':pipeline, 'refinement_report':report,
                'refinement_count':current.get('refinement_count', 0) + 1}


def save_refinement(candidate):
    """Save a new version exclusively; failures leave earlier files untouched."""
    previous = Path(candidate['path'])
    folder = previous.parent
    folder.mkdir(parents=True, exist_ok=True)
    # Avoid an ever-growing filename after repeated local refinements.
    stem = previous.stem.split('_refined_')[0][:60]
    destination = folder/(stem+'_refined_'+uuid.uuid4().hex+'.svg')
    save_svg_result(destination, candidate['svg'], candidate['pipeline'])
    return {**candidate, 'path':str(destination.resolve())}
