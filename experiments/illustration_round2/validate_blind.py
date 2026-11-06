from pathlib import Path
from collections import Counter
from html.parser import HTMLParser
import csv, hashlib, json, re, xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / 'outputs/illustration-round2-study'
PUBLIC = ROOT / 'outputs/illustration-blind-review-round2'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
key = json.loads((PRIVATE / 'sealed-key.json').read_text(encoding='utf-8'))
protocol = key['protocol']
data = json.loads((PUBLIC / 'data.js').read_text(encoding='utf-8').removeprefix('window.REVIEW_DATA = ').rstrip(';\n'))
assert data['experiment_id'] == key['experiment_id']
for group in ['experimental_code_sha256', 'production_code_sha256']:
    for name, digest in protocol[group].items(): assert sha(ROOT / name) == digest, name
for item in protocol['inputs']: assert sha(ROOT / 'test_pic' / item['name']) == item['sha256']
assert len(data['cases']) == len({c['id'] for c in data['cases']}) == 12
assert {c['source_name'] for c in data['cases']} == {c['name'] for c in protocol['inputs']}
for letter in 'ABCD':
    counts = Counter(c['assignments'][letter] for c in key['cases'])
    assert set(counts) == set(protocol['methods']) and set(counts.values()) == {3}

def remove_metadata(root):
    for parent in root.iter():
        for child in list(parent):
            if child.tag.rsplit('}', 1)[-1] in {'metadata', 'title', 'desc'}: parent.remove(child)
    return root

seen = []; paths = []; gradients = 0
for case, secret in zip(data['cases'], key['cases']):
    assert set(case) == {'id', 'source_name', 'width', 'height', 'original', 'candidates'}
    assert case['id'] == secret['id']
    assert sha(PUBLIC / case['original']) == secret['input']['sha256']
    assert len(case['candidates']) == 4 and {v['id'] for v in case['candidates']} == set('ABCD')
    for candidate in case['candidates']:
        assert set(candidate) == {'id', 'svg', 'preview'}
        f = PUBLIC / candidate['svg']; measurement = secret['measurements'][candidate['id']]
        assert f.exists() and (PUBLIC / candidate['preview']).exists()
        assert sha(f) == measurement['anonymous_sha256']
        svg = ET.parse(f).getroot()
        assert [float(svg.get('width')), float(svg.get('height'))] == [case['width'], case['height']]
        assert [float(v) for v in svg.get('viewBox').split()] == [0, 0, case['width'], case['height']]
        tags = [el.tag.rsplit('}', 1)[-1] for el in svg.iter()]
        assert set(tags) <= {'svg', 'g', 'path', 'defs', 'linearGradient', 'stop'}
        assert 0 < tags.count('path') == measurement['drawing_paths'] <= 2000
        ids = [el.get('id') for el in svg.iter() if el.get('id')]
        assert len(ids) == len(set(ids))
        for element in svg.iter():
            for attr, value in element.attrib.items():
                assert not attr.lower().startswith('on') and not attr.endswith('href')
                for target in re.findall(r'url\((.*?)\)', value): assert target.startswith('#') and target[1:] in ids
        original = remove_metadata(ET.parse(measurement['source_svg']).getroot())
        assert ET.tostring(original) == ET.tostring(svg), 'Anonymous copy changed drawing'
        result = measurement['result']
        if measurement['method'] != 'control': assert result['protocol'] == protocol['protocol']
        paths.append(tags.count('path')); gradients += tags.count('linearGradient'); seen.append(candidate['svg'])
assert len(seen) == len(set(seen)) == len(list(PUBLIC.rglob('*.svg'))) == 48
for name in ['index.html', 'data.js', 'review.js', 'review-model.js']:
    assert not re.search(r'potrace|vtracer|area_only|baseline|sealed-key|method_descriptions|edge_clean|flat_layers|gradient_layers', (PUBLIC / name).read_text(encoding='utf-8'), re.I)

class Page(HTMLParser):
    def __init__(self): super().__init__(); self.ids = set(); self.assets = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            assert attrs['id'] not in self.ids; self.ids.add(attrs['id'])
        if tag == 'script' and attrs.get('src'): self.assets.append(attrs['src'])
page = Page(); page.feed((PUBLIC / 'index.html').read_text(encoding='utf-8'))
assert all((PUBLIC / name).exists() for name in page.assets)
assert set(re.findall(r"\$\('([^']+)'\)", (PUBLIC / 'review.js').read_text(encoding='utf-8'))) <= page.ids
with (PUBLIC / '评分表.csv').open(encoding='utf-8-sig', newline='') as f: rows = list(csv.DictReader(f))
assert len(rows) == 48
assert {(r['图片编号'], r['候选']) for r in rows} == {(c['id'], v['id']) for c in data['cases'] for v in c['candidates']}
assert all(not r[field] for r in rows for field in ['整体还原_1到5', '细节保留_1到5', '线条连续_1到5', '色彩渐变_1到5'])
summary = {'images': 12, 'svg_files': 48, 'position_balance': True, 'all_input_and_algorithm_hashes_match': True,
           'drawings_unchanged_by_anonymization': True, 'path_range': [min(paths), max(paths)],
           'embedded_images': 0, 'gradients': gradients, 'score_rows': 48, 'static_assets_and_dom_ids_valid': True,
           'browser_interaction_tested': False, 'public_bytes': sum(p.stat().st_size for p in PUBLIC.rglob('*') if p.is_file())}
(PRIVATE / 'validation.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary))
