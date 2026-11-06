"""Stage ablations only; crop coordinates are never read by conversion methods."""
from pathlib import Path
import sys,json,subprocess,xml.etree.ElementTree as ET
import numpy as np
from PIL import Image,ImageDraw,ImageOps
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/illustration-round2-study/edge-diagnosis'
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'algorithm_records/round1-20261106')]
from area_075_override import apply
from core import validate
from pipeline import run_pipeline
from status_io import write_json_atomic
apply();OUT.mkdir(parents=True,exist_ok=True)
ET.register_namespace('','http://www.w3.org/2000/svg')
config=validate(json.loads((ROOT/'algorithm_records/round1-20261106/area-075.json').read_text(encoding='utf-8')))
for name,box in [('test03.png',(1460,85,1540,180)),('test04.png',(380,0,680,300))]:
    work=OUT/Path(name).stem;work.mkdir(exist_ok=True)
    def record(stage,**kw):write_json_atomic(OUT/'status.json',{'image':name,'stage':stage,**kw})
    if not (work/'pipeline_report.json').exists():
        run_pipeline({'input':str(ROOT/'test_pic'/name),'output':str(work/'output.svg')},config,record)
    job=json.loads((work/'potrace.json').read_text(encoding='utf-8'))
    regions=np.fromfile(work/'regions.bin',dtype='<u2').reshape(job['height'],job['width'])
    colors=np.zeros((len(job['regions'])+1,4),np.uint8)
    for item in job['regions']:colors[item['id']]=item['color']
    x0,y0,x1,y1=box
    patches=[('Original',Image.open(ROOT/'test_pic'/name).convert('RGBA').crop(box)),
             ('Region labels',Image.fromarray(colors[regions[y0:y1,x0:x1]]))]
    tree=ET.parse(work/'reduced.svg')
    for el in tree.getroot().iter():
        if el.tag.rsplit('}',1)[-1]=='path':el.set('stroke','none')
    tree.write(work/'no-stroke.svg',encoding='utf-8',xml_declaration=True)
    for file,label in [('no-stroke.svg','Before simplify / no stroke'),('reduced.svg','Before simplify / stroke 1'),('output.svg','After simplify / stroke 1')]:
        folder=work/Path(file).stem;folder.mkdir(exist_ok=True)
        clipped=ET.parse(work/file);clipped.getroot().set('viewBox',f'{x0} {y0} {x1-x0} {y1-y0}')
        clipped.getroot().set('width',str((x1-x0)*6));clipped.getroot().set('height',str((y1-y0)*6))
        clipped.write(folder/'crop.svg',encoding='utf-8',xml_declaration=True)
        subprocess.run([str(ROOT/'runtime/node/node.exe'),str(Path(__file__).with_name('rasterize.cjs')),str(folder/'crop.svg'),str(folder/'crop.png')],check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        patches.append((label,Image.open(folder/'crop.png').convert('RGBA')))
    sheet=Image.new('RGB',(350*len(patches),660),'#eeeeee');draw=ImageDraw.Draw(sheet)
    for i,(label,patch) in enumerate(patches):
        blank=Image.new('RGBA',patch.size,'white');blank.alpha_composite(patch)
        ratio=min(330/blank.width,600/blank.height)
        blank=blank.convert('RGB').resize((round(blank.width*ratio),round(blank.height*ratio)),Image.Resampling.NEAREST if label=='Region labels' else Image.Resampling.LANCZOS)
        sheet.paste(blank,(350*i+10,40));draw.text((350*i+10,10),label,fill='#222222')
    sheet.save(work/'stages.jpg',quality=95)
    ids=np.unique(regions[y0:y1,x0:x1]);items=[r for r in job['regions'] if r['id'] in ids]
    result={'image':name,'diagnostic_crop':box,'intersecting_regions':len(items),
            'areas_under_16':[r for r in items if r.get('area',0)<16],
            'note':'Coordinates are evidence-only; no conversion rule consumes this crop.'}
    (work/'diagnosis.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'completed':name,'regions_in_crop':len(items),'small_regions':len(result['areas_under_16'])}),flush=True)
write_json_atomic(OUT/'status.json',{'stage':'complete'})
