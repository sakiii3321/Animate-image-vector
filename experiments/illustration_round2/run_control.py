from pathlib import Path
import json,sys,time,shutil,subprocess,hashlib
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/illustration-round2-study'
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'algorithm_records/round1-20261106')]
from core import validate
from pipeline import run_pipeline
from status_io import write_json_atomic
from area_075_override import apply
apply()
config=validate(json.loads((ROOT/'algorithm_records/round1-20261106/area-075.json').read_text(encoding='utf-8')))
inventory=json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))
shard=int(sys.argv[1])
for i,item in enumerate(inventory):
    if i%2!=shard:continue
    work=OUT/'cases'/Path(item['name']).stem/'control';work.mkdir(parents=True,exist_ok=True)
    if (work/'result.json').exists():continue
    source=ROOT/'test_pic'/item['name']
    assert hashlib.sha256(source.read_bytes()).hexdigest()==item['sha256']
    def record(stage,**kw):write_json_atomic(OUT/f'control-status-{shard}.json',{'image':item['name'],'stage':stage,**kw})
    if item['previous_round_same_bytes']:
        old=ROOT/'outputs/illustration-generalization-study/cases'/source.stem/'native/area_only'
        for name in ['output.svg','preview.png','pipeline_report.json']:shutil.copyfile(old/name,work/name)
        result=json.loads((old/'result.json').read_text(encoding='utf-8'))
        result.update({'method':'control','reused_from':str(old),'input_sha256':item['sha256']})
    else:
        with Image.open(source) as im:ImageOps.exif_transpose(im).convert('RGBA').save(work/'input.png')
        started=time.perf_counter();report=run_pipeline({'input':str(work/'input.png'),'output':str(work/'output.svg')},config,record)
        subprocess.run([str(ROOT/'runtime/node/node.exe'),str(ROOT/'experiments/illustration_round2/render_case.cjs'),str(work/'output.svg'),str(work)],check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        result={'image':item['name'],'method':'control','size':[item['width'],item['height']],
                'counts':report['final_counts'],'seconds':time.perf_counter()-started,'input_sha256':item['sha256']}
        for name in ['raster.png','input.png','regions.bin','potrace.json','potrace-trace.log','traced.svg','normalized.svg','reduced-raw.svg','reduced.svg','simplified.svg']:
            path=work/name;assert path.resolve().is_relative_to(OUT.resolve());path.unlink(missing_ok=True)
    result['svg_bytes']=(work/'output.svg').stat().st_size
    (work/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'completed':item['name']}),flush=True)
write_json_atomic(OUT/f'control-status-{shard}.json',{'stage':'complete'})
