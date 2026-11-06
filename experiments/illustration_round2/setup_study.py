from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,shutil
from PIL import Image,ImageOps,ImageDraw

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/illustration-round2-study'
ARCHIVE=ROOT/'algorithm_records/round1-20261106'
OUT.mkdir(parents=True,exist_ok=True)
ARCHIVE.mkdir(parents=True,exist_ok=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if not (ARCHIVE/'manifest.json').exists():
    archived=[]
    for folder,patterns in [('app',['*.py','*.cjs']),('tests',['test_detail_preservation.py','test_structure_features.py'])]:
        for pattern in patterns:
            for source in (ROOT/folder).glob(pattern):
                destination=ARCHIVE/folder/source.name;destination.parent.mkdir(exist_ok=True)
                shutil.copyfile(source,destination)
                archived.append({'path':destination.relative_to(ARCHIVE).as_posix(),'sha256':sha(destination)})
    for src,name in [
        ('outputs/illustration-blind-study-private/score1-analysis.json','blind-scores-analysis.json'),
        ('test_pic/评分1.json','blind-scores-original.json'),
        ('outputs/illustration-generalization-study/protocol.json','protocol.json'),
        ('outputs/illustration-generalization-study/area-only-detail-tests.log','known-thin-line-regression.log')]:
        shutil.copyfile(ROOT/src,ARCHIVE/name)
    protocol=json.loads((ARCHIVE/'protocol.json').read_text(encoding='utf-8'))
    for name,structure in [('area-075',False),('structure-075',True)]:
        settings={**protocol['config'],'potrace_preserve_structure':structure}
        (ARCHIVE/(name+'.json')).write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'recorded_utc':datetime.now(timezone.utc).isoformat(),'source_files':archived,
              'baseline_mean':3.28125,'area_075_mean':3.46875,'structure_075_mean':3.5,
              'new_image_means':{'area_075':3.4642857142857144,'structure_075':3.392857142857143},
              'area_075_override':'Override MergeCosts.cost only: harmonic_bucketed_area**0.75 * sqrt(focus_weight) * LabAlphaDistanceSquared. Detector disabled. Same rule used for both merge stages.',
              'limits':['Single reviewer; 8 illustrations, including one development reference.',
                        'Area-only did not pass existing continuous-thin-line regression.',
                        'Default production area exponent remains 0.5; structure is optional.',
                        'Configuration alone cannot activate area-only; recorded override is required.']}
    (ARCHIVE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (ARCHIVE/'README.txt').write_text('''第一轮较优算法记录\n\n本目录保存源码快照、精确参数、评分原件和已知缺陷，不包含重复的便携运行时或大体积 SVG。\n\narea-075：Potrace 前的区域合并，仅将面积代价指数从 0.5 改为 0.75，关闭结构检测。需要同时应用 area_075_override.py 中的函数；仅导入 JSON 不会改变指数。\nstructure-075：开启现有结构保护，合并代价带保护边界优先级，面积指数 0.75。\n\n两者均用 100 个初始颜色、平滑 1、近色小块阈值 8、描边 1、初次 3000 路径再合并到 2000、曲线容差 0.3；无裁剪、无 ROI、无超分、无 DiffVG。\n\n源码按原便携项目结构保存；复现时使用相同项目运行时和 app 目录结构。manifest.json 记录源文件 SHA256。area-only 的连续细线回归缺陷尚未修复，不能据平均分直接设为默认。\n''',encoding='utf-8')

old=json.loads((ROOT/'outputs/illustration-generalization-study/protocol.json').read_text(encoding='utf-8'))['inputs']
inventory=[];thumbs=[]
for p in sorted((ROOT/'test_pic').iterdir()):
    if p.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:continue
    with Image.open(p) as im:source=ImageOps.exif_transpose(im).convert('RGBA')
    item={'name':p.name,'width':source.width,'height':source.height,'bytes':p.stat().st_size,'sha256':sha(p),
          'previous_round_same_bytes':old.get(p.name)==sha(p)}
    inventory.append(item)
    preview=Image.new('RGB',(300,370),'#eeeeee');small=ImageOps.contain(source,(288,330));background=Image.new('RGBA',small.size,'white');background.alpha_composite(small)
    preview.paste(background.convert('RGB'),((300-small.width)//2,28+(330-small.height)//2));ImageDraw.Draw(preview).text((8,7),p.name,fill='#222222');thumbs.append(preview)
sheet=Image.new('RGB',(1200,370*((len(thumbs)+3)//4)),'#eeeeee')
for i,p in enumerate(thumbs):sheet.paste(p,((i%4)*300,(i//4)*370))
sheet.save(OUT/'inventory.jpg',quality=92)
(OUT/'inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'images':len(inventory),'unchanged':sum(i['previous_round_same_bytes'] for i in inventory),'changed_or_new':[i['name'] for i in inventory if not i['previous_round_same_bytes']],'archive':str(ARCHIVE)},ensure_ascii=True))
