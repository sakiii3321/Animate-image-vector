from pathlib import Path
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/illustration-round2-study'
sys.path.insert(0,str(Path(__file__).parent))
from methods import PROTOCOL
files=list((Path(__file__).parent).glob('*.py'))+list((Path(__file__).parent).glob('*.cjs'))
appfiles=list((ROOT/'app').glob('*.py'))+list((ROOT/'app').glob('*.cjs'))
manifest={'protocol':PROTOCOL,'methods':['control','edge_clean','flat_layers','gradient_layers'],
          'inputs':json.loads((OUT/'inventory.json').read_text(encoding='utf-8')),
          'experimental_code_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
          'production_code_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in appfiles},
          'comparison':'12 native inputs; four methods, 48 SVGs; maximum 2000 total drawing paths including strokes. One shared configuration per method; no image-specific ROI or tuning.',
          'implementation':'Local prototypes inspired by research; not full reproductions of LIVE, Vector Scaffolding or gradient-layer decomposition.',
          'development_pilots':'Versions 1-3 are development attempts, retained separately; final blind candidates use v4. V3 was revised after full-image inspection found that removing every detected line before budget-limited reconstruction caused lost details.'}
(OUT/'protocol.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Frozen: 12 images, 4 methods, 48 candidates, protocol version',PROTOCOL['version'])
