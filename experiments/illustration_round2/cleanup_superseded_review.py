"""Discard redundant unpublished v3 copies after v4 has passed validation."""
from pathlib import Path
import json, shutil
ROOT=Path(__file__).resolve().parents[2]
STUDY=(ROOT/'outputs/illustration-round2-study').resolve();DEV=(STUDY/'development-v3').resolve()
validation=json.loads((STUDY/'validation.json').read_text(encoding='utf-8'))
render=json.loads((STUDY/'render-validation.json').read_text(encoding='utf-8'))
assert validation['svg_files']==48 and render['verified']==48
assert json.loads((STUDY/'protocol.json').read_text(encoding='utf-8'))['protocol']['version']==4
removed=[]
def discard(path):
    target=path.resolve();assert target.is_relative_to(DEV) and target!=DEV and not path.is_symlink() and not path.is_junction()
    size=sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) if path.is_dir() else path.stat().st_size
    removed.append({'path':str(path.relative_to(STUDY)),'bytes':size})
    if path.is_dir():shutil.rmtree(path)
    else:path.unlink()
# The anonymous v3 copies duplicated the recorded originals and were never delivered.
if (DEV/'public-review').exists():discard(DEV/'public-review')
keyfile=DEV/'sealed-key.json'
key=json.loads(keyfile.read_text(encoding='utf-8'))
for case in key['cases']:
    for measurement in case['measurements'].values():
        if measurement['method']!='control':
            measurement['source_svg']=str(DEV/'cases'/Path(case['input']['name']).stem/measurement['method']/'output.svg')
keyfile.write_text(json.dumps(key,ensure_ascii=False,indent=2),encoding='utf-8')
# Retain v3 code, protocol, metrics and review sheets; keep two complete defect cases.
for folder in (DEV/'cases').iterdir():
    if folder.name in {'test03','test04'}:continue
    for method in folder.iterdir():
        for filename in ['output.svg','preview.png']:
            file=method/filename
            if file.exists():discard(file)
report={'freed_bytes':sum(r['bytes'] for r in removed),'removed':removed,
        'retained':'V3 code/protocol and all 36 metric records, six review sheets, complete test03/test04 v3 vectors. All 48 final v4/control candidates retained.'}
(STUDY/'superseded-cleanup.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'freed_bytes':report['freed_bytes'],'entries':len(removed)}))
