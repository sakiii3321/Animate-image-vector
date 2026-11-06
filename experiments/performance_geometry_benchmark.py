"""Serial interleaved timing with byte-for-byte output/report parity checks."""
from pathlib import Path
import sys,json,time,hashlib,statistics,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(Path(__file__).parent)]
import vector_geometry as current
import performance_geometry_baseline as reference
OUT=ROOT/'outputs/performance-geometry-study';OUT.mkdir(exist_ok=True)
samples=[('test04',100),('test03',100),('test06',100),('test02',100)]
rows=[]
for name,limit in samples:
    source=ROOT/'outputs/illustration-round2-study/cases'/name/'control/output.svg'
    tree=ET.parse(source);root=tree.getroot()
    for child in list(root)[limit:]:root.remove(child)
    sample=OUT/(name+'-sample.svg');tree.write(sample,encoding='utf-8',xml_declaration=True)
    timings={operation:{'before':[],'after':[]} for operation in ['counts','normalize','simplify']}
    for repeat in range(3):
        results={}
        variants=[('before',reference),('after',current)]
        if repeat%2:variants.reverse()
        for tag,module in variants:
            for operation in timings:
                destination=OUT/f'{name}-{operation}-{tag}.svg'
                started=time.perf_counter()
                if operation=='counts':report=module.svg_counts(sample);digest=None
                elif operation=='normalize':report=module.normalize_svg(sample,destination,float(root.get('width')),float(root.get('height')));digest=None
                else:report=module.simplify_svg(sample,destination,.3);digest=None
                timings[operation][tag].append(time.perf_counter()-started)
                if operation!='counts':digest=hashlib.sha256(destination.read_bytes()).hexdigest()
                results[(operation,tag)]=(report,digest)
        for operation in timings:assert results[(operation,'before')]==results[(operation,'after')],(name,operation)
    measured={operation:{'before_seconds':statistics.median(times['before']),
                         'after_seconds':statistics.median(times['after']),
                         'speedup':statistics.median(times['before'])/statistics.median(times['after']),
                         'raw_seconds':times} for operation,times in timings.items()}
    row={'image':name,'paths':current.svg_counts(sample)['fill_paths'],'input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
         'sample_sha256':hashlib.sha256(sample.read_bytes()).hexdigest(),'operations':measured,'outputs_and_reports_identical':True}
    rows.append(row);print(json.dumps(row),flush=True)
    # Keep only the reusable samples; benchmark output copies are redundant.
    for operation in ['normalize','simplify']:
        for tag in ['before','after']:
            path=OUT/f'{name}-{operation}-{tag}.svg'
            assert path.resolve().is_relative_to(OUT.resolve());path.unlink()
summary={'method':'Three serial interleaved runs per variant; median wall clock. First 100 engine output groups per image. This measures geometry postprocessing, not end-to-end conversion.',
         'baseline_sha256':hashlib.sha256(Path(reference.__file__).read_bytes()).hexdigest(),
         'optimized_sha256':hashlib.sha256(Path(current.__file__).read_bytes()).hexdigest(),'cases':rows}
(OUT/'benchmark.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print('Benchmark saved:',OUT/'benchmark.json',flush=True)
