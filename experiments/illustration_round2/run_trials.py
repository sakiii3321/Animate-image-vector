from pathlib import Path
import sys,json,time,traceback,subprocess,hashlib,shutil
import numpy as np
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/illustration-round2-study'
sys.path[:0]=[str(Path(__file__).parent),str(ROOT/'app')]
from methods import run_method,PROTOCOL
from status_io import write_json_atomic
inventory=json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))
shard=int(sys.argv[1]);method=sys.argv[2]
only=sys.argv[3] if len(sys.argv)>3 else None
for i,item in enumerate(inventory):
    if only and item['name']!=only:continue
    if not only and i%2!=shard:continue
    work=OUT/'cases'/Path(item['name']).stem/method;work.mkdir(parents=True,exist_ok=True)
    if (work/'result.json').exists():continue
    source=ROOT/'test_pic'/item['name'];assert hashlib.sha256(source.read_bytes()).hexdigest()==item['sha256']
    def record(stage,**kw):write_json_atomic(OUT/f'{method}-status-{shard}.json',{'image':item['name'],'stage':stage,**kw})
    try:
        with Image.open(source) as im:ImageOps.exif_transpose(im).convert('RGBA').save(work/'input.png')
        started=time.perf_counter();record('starting')
        result=run_method(work/'input.png',work,method,record)
        result.update({'image':item['name'],'method':method,'size':[item['width'],item['height']],
                       'seconds':time.perf_counter()-started,'svg_bytes':(work/'output.svg').stat().st_size,
                       'input_sha256':item['sha256'],'protocol':PROTOCOL})
        subprocess.run([str(ROOT/'runtime/node/node.exe'),str(ROOT/'experiments/illustration_round2/render_case.cjs'),str(work/'output.svg'),str(work)],check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def white_rgb(path):
            with Image.open(path) as image:
                image=image.convert('RGBA');background=Image.new('RGBA',image.size,'white');background.alpha_composite(image)
                return np.asarray(background.convert('RGB'),dtype=np.float32)
        delta=white_rgb(work/'input.png')-white_rgb(work/'raster.png')
        result['native_rgb_mae']=float(np.abs(delta).mean());result['native_rgb_rmse']=float(np.sqrt(np.mean(delta*delta)))
        del delta
        (work/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        (work/'error.json').unlink(missing_ok=True)
        keep={'output.svg','preview.png','result.json','method-report.json','gradient-fits.json'}
        for temporary in work.iterdir():
            if temporary.name in keep:continue
            assert work.resolve().is_relative_to(OUT.resolve()) and temporary.resolve().is_relative_to(work.resolve())
            if temporary.is_dir():shutil.rmtree(temporary)
            else:temporary.unlink()
        print(json.dumps(result),flush=True)
    except Exception as error:
        result={'image':item['name'],'method':method,'error':str(error),'traceback':traceback.format_exc()}
        (work/'error.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True);raise
write_json_atomic(OUT/f'{method}-status-{shard}.json',{'stage':'complete'})
