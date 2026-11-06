"""Remove only this experiment's regenerable pilot/diagnostic intermediates."""
from pathlib import Path
import json, shutil
ROOT = Path(__file__).resolve().parents[2]
STUDY = (ROOT / 'outputs/illustration-round2-study').resolve()
removed = []

def remove(path, parent):
    target = path.resolve(); parent = parent.resolve()
    assert parent.is_relative_to(STUDY) and target.is_relative_to(parent) and target != parent
    assert not path.is_symlink() and not path.is_junction()
    size = sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) if path.is_dir() else path.stat().st_size
    removed.append({'path': str(path.relative_to(STUDY)), 'bytes': size})
    if path.is_dir(): shutil.rmtree(path)
    else: path.unlink()

pilots = [STUDY / 'cases/test03' / name for name in ['edge_clean-v1', 'edge_clean-v2']]
pilots += [STUDY / 'cases/test04' / name for name in ['gradient_layers-v1', 'gradient_layers-v2']]
for folder in pilots:
    assert (folder / 'result.json').exists()
    for path in folder.iterdir():
        if path.name not in {'output.svg', 'preview.png', 'result.json', 'method-report.json', 'gradient-fits.json'}: remove(path, folder)
for name in ['test03', 'test04']:
    folder = STUDY / 'edge-diagnosis' / name
    assert (folder / 'stages.jpg').exists() and (folder / 'diagnosis.json').exists()
    for path in folder.iterdir():
        if path.name not in {'stages.jpg', 'diagnosis.json', 'pipeline_report.json'}: remove(path, folder)
folder = STUDY / 'pilot-checks'
if folder.exists():
    for path in folder.iterdir():
        if path.is_file() and path.suffix in {'.svg', '.png'}: remove(path, folder)
report = {'freed_bytes': sum(row['bytes'] for row in removed), 'removed': removed,
          'scope': 'Only round-two generated pilot/diagnosis intermediates; final candidates, source images and prior rounds preserved.'}
(STUDY / 'intermediate-cleanup.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({'freed_bytes': report['freed_bytes'], 'entries': len(removed)}))
