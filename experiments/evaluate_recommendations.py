"""Measure recommendation behavior for every test image; no per-image tuning."""
from pathlib import Path
import hashlib,json,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from image_recommendation import analyze_image
records=[]
for path in sorted((ROOT/'test_pic').iterdir()):
    if path.suffix.lower() not in {'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff'}:continue
    started=time.perf_counter();result=analyze_image(path)
    records.append({'name':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'wall_seconds':round(time.perf_counter()-started,3),'analysis':result})
OUT=ROOT/'outputs/software-optimization-study';OUT.mkdir(exist_ok=True)
(OUT/'recommendations.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([{k:r[k] for k in ['name','wall_seconds']}|{
    'type':r['analysis']['type'],'profile':r['analysis']['recommended_profile'],
    'complexity':r['analysis']['complexity']['level'],'features':r['analysis']['features']}
    for r in records],indent=2))
