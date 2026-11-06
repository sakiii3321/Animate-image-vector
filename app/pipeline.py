"""Optional processing stages around the existing isolated tracing worker."""
from pathlib import Path
import json,shutil,time

def run_pipeline(job, config, record):
    from PIL import Image
    from core import MAX_PROCESSED_PIXELS, parse_detail_region
    from vector_geometry import normalize_svg, simplify_svg, svg_counts
    from drawing_stats import drawing_counts
    from illustration_profiles import is_illustration, resize_illustration_canvas
    work=Path(job['output']).parent;source=Path(job['input']);output=Path(job['output'])
    Image.MAX_IMAGE_PIXELS=MAX_PROCESSED_PIXELS
    with Image.open(source) as im:width,height=im.size
    scale=config['sr_scale'] if config['sr_enabled'] else 1
    if width*height*scale*scale>MAX_PROCESSED_PIXELS:
        raise ValueError('超分辨率输出超过 1.6 亿像素，请降低倍数或缩小输入图片。')
    roi=parse_detail_region(config['detail_region'])
    if roi and (roi[0]+roi[2]>width or roi[1]+roi[3]>height):
        raise ValueError('细节优先区域超出规范化后图片范围。')
    start=time.perf_counter();stages=[];illustration=is_illustration(config);illustration_report=None
    if config['sr_enabled'] or config['diffvg_optimize'] or config['highres_refine']:
        from enhancement_runtime import runtime_capabilities, run_backend
        caps=runtime_capabilities()
        for capability,needed in [('sr',config['sr_enabled']),('diffvg',config['diffvg_optimize'] or config['highres_refine'])]:
            if needed and not caps[capability]['available']:
                raise ValueError(caps[capability].get('reason') or '增强运行时不可用。')
    target=source
    if config['sr_enabled']:
        record('super_resolution',current=0,total=1)
        target=work/'processed.png'
        report=run_backend('super_resolution',{'input':str(source),'output':str(target),'config':config,'width':width,'height':height},work,record)
        with Image.open(target) as im:
            if im.size!=(width*scale,height*scale):raise ValueError('超分辨率输出尺寸不符合所选倍数。')
        stages.append({'stage':'super_resolution','report':report})
    raw=work/'traced.svg';record('convert')
    from potrace_engine import convert_potrace
    params=dict(config);params['_spatial_scale']=scale
    params['_structure_source']=str(source)
    if roi:params['detail_region']=','.join(str(v*scale) for v in roi)
    if illustration:
        from illustration_engine import convert_illustration
        if config['curve_simplify'] and config.get('simplify_target_paths'):
            params['path_limit']=min(params['path_limit'],config['simplify_target_paths'])
        illustration_report=convert_illustration(str(target),str(raw),params,record)
    else:
        convert_potrace(str(target),str(raw),params,record)
    normalized=work/'normalized.svg';record('normalize_svg')
    if illustration and not (config['diffvg_optimize'] or config['highres_refine']):
        resize_illustration_canvas(raw,normalized,width,height)
    else:
        normalize_svg(raw,normalized,width,height)
    stages.append({'stage':'vectorize','counts':svg_counts(normalized),'target_size':[width*scale,height*scale]})
    if illustration_report is not None:
        stages[-1]['report']=illustration_report
    current=normalized
    if config['curve_simplify'] and not illustration:
        target_paths=config.get('simplify_target_paths',0)
        if target_paths:
            before=svg_counts(current)
            report={'target':target_paths,'before':before,'skipped':before['fill_paths']<=target_paths}
            if before['fill_paths']>target_paths:
                from region_simplify import reduce_regions
                reduced=work/'reduced-raw.svg'
                report.update(reduce_regions(work,reduced,target_paths,params,record))
                current=work/'reduced.svg';normalize_svg(reduced,current,width,height)
            report['after']=svg_counts(current)
            if report['after']['fill_paths']>target_paths:raise ValueError('色块简化未达到目标数量。')
            stages.append({'stage':'region_simplify','report':report})
        record('curve_simplify')
        simplified=work/'simplified.svg';report=simplify_svg(current,simplified,config['curve_tolerance'],record)
        stages.append({'stage':'curve_simplify','report':report});current=simplified
    if config['diffvg_optimize'] or config['highres_refine']:
        record('diffvg_prepare')
        optimized=work/'optimized.svg'
        report=run_backend('optimize',{'input':str(current),'output':str(optimized),'target':str(target),'config':config,'width':width,'height':height},work,record)
        stages.append({'stage':'optimization','report':report});current=optimized
    shutil.copyfile(current,output)
    result={'config':config,'source_size':[width,height],'target_size':[width*scale,height*scale],'stages':stages,'final_counts':drawing_counts(output),'elapsed_seconds':time.perf_counter()-start}
    (work/'pipeline_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
