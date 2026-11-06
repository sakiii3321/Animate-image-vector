"""Record full-set v3/v4 observations, without placing measurements in the blind UI."""
from pathlib import Path
import json, statistics
ROOT=Path(__file__).resolve().parents[2];STUDY=ROOT/'outputs/illustration-round2-study'
protocol=json.loads((STUDY/'protocol.json').read_text(encoding='utf-8'))
rows=[]
for item in protocol['inputs']:
    for method in ['edge_clean','flat_layers','gradient_layers']:
        relative=Path('cases')/Path(item['name']).stem/method/'result.json'
        old=json.loads((STUDY/'development-v3'/relative).read_text(encoding='utf-8'))
        new=json.loads((STUDY/relative).read_text(encoding='utf-8'))
        assert new['protocol']['version']==4 and old['protocol']['version']==3
        assert new['input_sha256']==old['input_sha256']==item['sha256']
        rows.append({'image':item['name'],'method':method,'v3_mae':old['native_rgb_mae'],
                     'v4_mae':new['native_rgb_mae'],'v3_rmse':old['native_rgb_rmse'],
                     'v4_rmse':new['native_rgb_rmse'],'v4_paths':new['counts']['drawing_paths'],
                     'v4_strokes':new['counts']['stroke_paths']})
summary={}
for method in ['edge_clean','flat_layers','gradient_layers']:
    group=[r for r in rows if r['method']==method]
    summary[method]={'images':len(group),'v3_mean_image_mae':statistics.mean(r['v3_mae'] for r in group),
                     'v4_mean_image_mae':statistics.mean(r['v4_mae'] for r in group),
                     'mae_improved_images':sum(r['v4_mae']<r['v3_mae']-1e-6 for r in group),
                     'mae_worsened_images':sum(r['v4_mae']>r['v3_mae']+1e-6 for r in group)}
report={'purpose':'Check the universal base-line preservation revision; objective errors are not human scores.',
        'weighting':'Equal image weighting at each native resolution, RGB 0-255, alpha composited white.',
        'summary':summary,'rows':rows}
(STUDY/'revision-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(summary))
