"""Unblind the supplied scores against the final v4 key; preserve paired comparisons."""
from pathlib import Path
from statistics import mean, median, pstdev
from collections import Counter
import hashlib, json

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/illustration-round2-study'
SOURCE=ROOT/'test_pic/评分2.json'
key=json.loads((OUT/'sealed-key.json').read_text(encoding='utf-8'))
scores=json.loads(SOURCE.read_text(encoding='utf-8-sig'))
dimensions=['overall','detail','line','color']
names={'control':'上一轮较优对照（面积权重 0.75）',
       'edge_clean':'边缘碎片整理',
       'flat_layers':'色面＋残差补线',
       'gradient_layers':'渐变色面＋残差补线'}
assert scores['version']==1 and scores['experiment_id']==key['experiment_id']=='illustration-r2-3c9f1647bd'
cases={c['id']:c for c in key['cases']}
expected={(c['id'],letter) for c in key['cases'] for letter in c['assignments']}
seen=set();records=[]
for row in scores['rows']:
    ident=(row['image_id'],row['candidate'])
    assert ident in expected and ident not in seen, ident
    seen.add(ident);case=cases[ident[0]]
    assert row['source_name']==case['input']['name']
    assert all(type(row[d]) is int and 1<=row[d]<=5 for d in dimensions),row
    measurement=case['measurements'][ident[1]]
    svg=ROOT/'outputs/illustration-blind-review-round2'/ident[0]/f'{ident[0]}-{ident[1]}.svg'
    assert hashlib.sha256(svg.read_bytes()).hexdigest()==measurement['anonymous_sha256']
    assert case['assignments'][ident[1]]==measurement['method']
    records.append({**row,'method':measurement['method'],
                    'composite':mean(row[d] for d in dimensions),
                    'previous_round_same_bytes':case['input']['previous_round_same_bytes'],
                    'prior_reference':row['source_name']=='134948250_p0.png',
                    'reported_defect_image':row['source_name'] in {'test03.png','test04.png'},
                    'drawing_paths':measurement['drawing_paths'],
                    'svg_bytes':svg.stat().st_size,'svg_sha256':measurement['anonymous_sha256']})
assert seen==expected and len(records)==48

def aggregate(subset):
    stats=[]
    for method,label in names.items():
        rows=[r for r in subset if r['method']==method]
        cells=[r[d] for r in rows for d in dimensions]
        avg=mean(r['composite'] for r in rows)
        assert abs(avg-sum(cells)/len(cells))<1e-12
        stats.append({'method':method,'label':label,'images':len(rows),'composite_mean':avg,
                      'dimension_means':{d:mean(r[d] for r in rows) for d in dimensions},
                      'median_image_composite':median(r['composite'] for r in rows),
                      'minimum_image_composite':min(r['composite'] for r in rows),
                      'maximum_image_composite':max(r['composite'] for r in rows),
                      'between_image_sd':pstdev(r['composite'] for r in rows),
                      'total_svg_bytes':sum(r['svg_bytes'] for r in rows),
                      'mean_drawing_paths':mean(r['drawing_paths'] for r in rows)})
    return sorted(stats,key=lambda r:-r['composite_mean'])

def paired(a,b,subset=records):
    images=sorted({r['image_id'] for r in subset})
    index={(r['image_id'],r['method']):r for r in subset};result={}
    for dim in ['composite',*dimensions]:
        values=[index[(image,a)][dim]-index[(image,b)][dim] for image in images]
        result[dim]={'mean_delta':mean(values),'median_delta':median(values),
                     'wins':sum(v>0 for v in values),'ties':sum(v==0 for v in values),'losses':sum(v<0 for v in values)}
    return result

per_image=[];winners=Counter();outright=Counter()
for image,case in cases.items():
    rows=[r for r in records if r['image_id']==image];best=max(r['composite'] for r in rows)
    winning=[r['method'] for r in rows if r['composite']==best]
    winners.update(winning)
    if len(winning)==1:outright.update(winning)
    vals={r['method']:r['composite'] for r in rows}
    per_image.append({'image_id':image,'source_name':case['input']['name'],
                      'assignments':case['assignments'],'composites':vals,'best_methods':winning,
                      'gradient_minus_control':vals['gradient_layers']-vals['control'],
                      'gradient_minus_flat':vals['gradient_layers']-vals['flat_layers']})

oldkey=json.loads((ROOT/'outputs/illustration-blind-study-private/sealed-key.json').read_text(encoding='utf-8'))
oldscores=json.loads((ROOT/'test_pic/评分1.json').read_text(encoding='utf-8-sig'))
assert oldkey['experiment_id']==oldscores['experiment_id']
oldcases={c['id']:c for c in oldkey['cases']}
oldcontrol={}
for row in oldscores['rows']:
    c=oldcases[row['image_id']]
    if c['assignments'][row['candidate']]=='area_only':
        oldcontrol[row['source_name']]={**row,'composite':mean(row[d] for d in dimensions),
            'sha256':c['measurements'][row['candidate']]['anonymous_sha256']}
repeated=[]
for row in records:
    if row['method']!='control' or not row['previous_round_same_bytes']:continue
    old=oldcontrol[row['source_name']]
    assert old['sha256']==row['svg_sha256'], 'Repeated control is not the same SVG'
    repeated.append({'image':row['source_name'],'identical_svg':True,
                     'round1':{d:old[d] for d in ['composite',*dimensions]},
                     'round2':{d:row[d] for d in ['composite',*dimensions]}})
assert len(repeated)==6

subsets={'all_images':records,
         'six_unchanged_inputs':[r for r in records if r['previous_round_same_bytes']],
         'six_new_or_replaced_inputs':[r for r in records if not r['previous_round_same_bytes']],
         'excluding_prior_reference':[r for r in records if not r['prior_reference']],
         'excluding_reference_and_reported_defect_images':[r for r in records if not r['prior_reference'] and not r['reported_defect_image']]}
result={'experiment_id':key['experiment_id'],'score_file':str(SOURCE),
        'score_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'saved_utc':scores['saved_utc'],
        'valid_rows':48,'valid_rating_cells':192,'missing_scores':0,
        'definition':'Mean of four 1-5 dimensions within each image, then equally weighted across images. Descriptive ordinal-score summaries from one reviewer.',
        'groups':{group:aggregate(rows) for group,rows in subsets.items()},
        'paired':{f'{a}_vs_{b}':paired(a,b) for a,b in [('edge_clean','control'),('flat_layers','control'),('gradient_layers','control'),('gradient_layers','flat_layers'),('gradient_layers','edge_clean'),('flat_layers','edge_clean')]},
        'best_including_ties':dict(winners),'outright_best':dict(outright),'per_image':per_image,
        'same_svg_ratings_across_rounds':repeated,'records':records,
        'limitations':['Single reviewer and 12 selected illustrations; no population-wide superiority claim.',
                       'All 12 images were reviewed during development; new/replaced six are not untouched holdout data.',
                       'Use same-round paired differences versus control; image set and rating context changed between rounds.',
                       'Only the area-only previous winner is present as a control; structure-075 was not retested in round two.',
                       'Routes change multiple stages; scores do not isolate every individual parameter.',
                       'All candidates capped at 2000 drawing paths including strokes; actual counts, nodes and file sizes differ.',
                       'V3 removal of all ridges was never submitted for scoring; round two tests v4 only.',
                       'No production default or algorithm source was modified by this analysis.']}
(OUT/'score2-analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:result[k] for k in ['valid_rows','valid_rating_cells','missing_scores','groups','paired','best_including_ties','outright_best','per_image','same_svg_ratings_across_rounds']},ensure_ascii=False,indent=2))
