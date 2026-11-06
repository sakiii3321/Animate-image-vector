"""Archive the complete, unpublished v3 experiment before a general algorithm revision."""
from pathlib import Path
import json, hashlib, shutil
ROOT=Path(__file__).resolve().parents[2]
STUDY=(ROOT/'outputs/illustration-round2-study').resolve()
DEST=(STUDY/'development-v3').resolve()
assert not DEST.exists()
protocol=json.loads((STUDY/'protocol.json').read_text(encoding='utf-8'))
assert protocol['protocol']['version']==3
DEST.mkdir()
for name,digest in protocol['experimental_code_sha256'].items():
    source=ROOT/name;assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
    target=DEST/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
shutil.copyfile(STUDY/'protocol.json',DEST/'protocol.json')
for item in protocol['inputs']:
    for method in ['edge_clean','flat_layers','gradient_layers']:
        source=(STUDY/'cases'/Path(item['name']).stem/method).resolve()
        target=(DEST/'cases'/Path(item['name']).stem/method).resolve()
        assert source.is_relative_to(STUDY) and target.is_relative_to(DEST)
        assert (source/'result.json').exists()
        target.parent.mkdir(parents=True,exist_ok=True);source.rename(target)
for name in ['sealed-key.json','validation.json','render-validation.json','visual-checks']:
    source=(STUDY/name).resolve();target=(DEST/name).resolve()
    assert source.is_relative_to(STUDY) and target.is_relative_to(DEST)
    if source.exists():source.rename(target)
source=(ROOT/'outputs/illustration-blind-review-round2').resolve();target=(DEST/'public-review').resolve()
assert source.is_relative_to((ROOT/'outputs').resolve()) and target.is_relative_to(DEST)
source.rename(target)
(DEST/'reason.txt').write_text('Full-image inspection found a general removal/reconstruction mismatch: all ridge candidates were inpainted out before only a budget-limited subset could be reconstructed. The next revision keeps those source lines in the base layer. All 12 images will be rerun using the same revised algorithm, not selected per image. V3 is an unpublished development trial, not the final blind round.\n',encoding='utf-8')
print('Archived all v3 results, source hashes and unpublished review before the general revision.')
