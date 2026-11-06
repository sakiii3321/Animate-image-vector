"""Package every frozen round-two result, with a balanced private assignment key."""
from pathlib import Path
from datetime import datetime, timezone
import csv, hashlib, json, random, re, shutil, uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / 'outputs/illustration-round2-study'
PUBLIC = ROOT / 'outputs/illustration-blind-review-round2'
TEMPLATES = ROOT / 'experiments/illustration_round2/templates/blind-review'
METHODS = ['control', 'edge_clean', 'flat_layers', 'gradient_layers']
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
protocol = json.loads((PRIVATE / 'protocol.json').read_text(encoding='utf-8'))
inventory = protocol['inputs']
assert len(inventory) == 12

# Do not create a partially populated review or replace identities on reruns.
for item in inventory:
    assert sha(ROOT / 'test_pic' / item['name']) == item['sha256']
    for method in METHODS:
        work = PRIVATE / 'cases' / Path(item['name']).stem / method
        result = json.loads((work / 'result.json').read_text(encoding='utf-8'))
        assert result['input_sha256'] == item['sha256']
        assert result['size'] == [item['width'], item['height']]
        assert not (work / 'error.json').exists()
        if method != 'control': assert result['protocol'] == protocol['protocol']
        assert (work / 'output.svg').exists() and (work / 'preview.png').exists()

PUBLIC.mkdir(exist_ok=True)
keyfile = PRIVATE / 'sealed-key.json'
if keyfile.exists():
    key = json.loads(keyfile.read_text(encoding='utf-8'))
else:
    rng = random.SystemRandom()
    shuffled = inventory.copy(); rng.shuffle(shuffled)
    rows = []
    for block in range(3):
        methods = METHODS.copy(); rng.shuffle(methods)
        columns = list(range(4)); rng.shuffle(columns)
        shifts = list(range(4)); rng.shuffle(shifts)
        rows.extend([[methods[(col + shift) % 4] for col in columns] for shift in shifts])
    key = {'experiment_id': 'illustration-r2-' + uuid.uuid4().hex[:10],
           'created_utc': datetime.now(timezone.utc).isoformat(),
           'protocol': protocol,
           'method_descriptions': {
               'control': 'Archived round-one area exponent 0.75 control; detector off; 100 colors; 3000 to 2000 paths.',
               'edge_clean': 'Two bilateral passes; AA mixture absorption; compatible thin-region union; 100 colors; no separate line pass.',
               'flat_layers': '64-color large fills, then coherent centerline residual strokes, then color residual fills.',
               'gradient_layers': 'Same layered route with validated native SVG linear gradients in large fills.'},
           'caveats': [
               'Route comparison, not single-parameter causal attribution.',
               'At most 2000 drawing paths INCLUDING open strokes; counts and file sizes may differ.',
               'No source-specific crop, ROI, parameter table, super-resolution or DiffVG.',
               'Six inputs unchanged from round one and six new/replaced; report groups separately.',
               'Prior development reference and user-identified defect images must be flagged in analysis.',
               'Prototype v4 only; development versions v1-v3 excluded. No production default changed.',
               'Experimental timings were recorded during concurrent jobs; not a serial speed benchmark.',
               'Control historical metrics at 1024 scale are not directly comparable with new native metrics.'
           ],
           'cases': [{'id': f'I{i:02d}', 'input': item, 'assignments': dict(zip('ABCD', row))}
                     for i, (item, row) in enumerate(zip(shuffled, rows), 1)]}
    keyfile.write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding='utf-8')

ET.register_namespace('', 'http://www.w3.org/2000/svg')
cases, manifest, scores = [], [], []
for case in key['cases']:
    item = case['input']; source = ROOT / 'test_pic' / item['name']
    folder = PUBLIC / case['id']; folder.mkdir(exist_ok=True)
    original = folder / ('original' + source.suffix.lower())
    if not original.exists() or sha(original) != item['sha256']: shutil.copyfile(source, original)
    public = {'id': case['id'], 'source_name': item['name'], 'width': item['width'], 'height': item['height'],
              'original': original.relative_to(PUBLIC).as_posix(), 'candidates': []}
    case['measurements'] = {}
    for letter, method in case['assignments'].items():
        work = PRIVATE / 'cases' / source.stem / method
        result = json.loads((work / 'result.json').read_text(encoding='utf-8'))
        tree = ET.parse(work / 'output.svg'); root = tree.getroot()
        for parent in root.iter():
            for child in list(parent):
                if child.tag.rsplit('}', 1)[-1] in {'metadata', 'title', 'desc'}: parent.remove(child)
        tags = [el.tag.rsplit('}', 1)[-1] for el in root.iter()]
        assert set(tags) <= {'svg', 'g', 'path', 'defs', 'linearGradient', 'stop'}
        assert 0 < tags.count('path') <= 2000
        output = folder / f'{case["id"]}-{letter}.svg'
        tree.write(output, encoding='utf-8', xml_declaration=True)
        assert not re.search(r'potrace|vtracer|edge_clean|flat_layers|gradient_layers|generator', output.read_text(encoding='utf-8'), re.I)
        preview = folder / f'{case["id"]}-{letter}.png'; shutil.copyfile(work / 'preview.png', preview)
        public['candidates'].append({'id': letter, 'svg': output.relative_to(PUBLIC).as_posix(),
                                     'preview': preview.relative_to(PUBLIC).as_posix()})
        case['measurements'][letter] = {'method': method, 'source_svg': str(work / 'output.svg'),
             'anonymous_sha256': sha(output), 'drawing_paths': tags.count('path'),
             'gradients': tags.count('linearGradient'), 'result': result}
        manifest.append({'image_id': case['id'], 'candidate': letter, 'sha256': sha(output)})
        scores.append([key['experiment_id'], case['id'], item['name'], letter, '', '', '', '', ''])
    cases.append(public)
keyfile.write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding='utf-8')
data = {'experiment_id': key['experiment_id'], 'cases': cases}
(PUBLIC / 'data.js').write_text('window.REVIEW_DATA = ' + json.dumps(data, ensure_ascii=False, indent=2) + ';\n', encoding='utf-8')
(PUBLIC / 'checksums.json').write_text(json.dumps({'experiment_id': key['experiment_id'], 'files': manifest}, indent=2), encoding='utf-8')
with (PUBLIC / '评分表.csv').open('w', encoding='utf-8-sig', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['批次','图片编号','原图文件','候选','整体还原_1到5','细节保留_1到5','线条连续_1到5','色彩渐变_1到5','备注'])
    writer.writerows(scores)
for name in ['review.js', 'review-model.js']: shutil.copyfile(TEMPLATES / name, PUBLIC / name)
html = (TEMPLATES / 'index.html').read_text(encoding='utf-8')
html = html.replace('8 张原图', '12 张原图').replace('插画矢量图盲评</h1>', '插画矢量图盲评 · 第二轮</h1>')
html = html.replace('轮廓是否平顺，细线是否断裂。', '轮廓是否平顺，细线是否断裂、拼接或出现串珠。')
html = html.replace('各方法不保证同等路径数量或文件大小', '每份最多 2000 条绘制路径（包含细线），实际数量和文件大小可不同')
(PUBLIC / 'index.html').write_text(html, encoding='utf-8')
(PUBLIC / '使用说明.txt').write_text('''插画矢量图盲评 · 第二轮

用桌面浏览器打开 index.html，保留整个文件夹。无需联网或安装。
12 张原图，每张 A/B/C/D 四份，共 48 份 SVG。字母对应关系按图片打乱；同一字母不是同一方法。与上一轮的编号也没有对应关系。

所有方法使用相同的原尺寸完整画幅；每种方法在所有图片上使用同一组规则和参数。没有针对某张图的裁剪、细节框或超分辨率。
每份最多 2000 条绘制路径，包含填充路径和独立描线。实际数量、节点数、文件大小可以不同。此轮比较整条算法路线，并非单一参数实验。

先看全图，再滚轮放大、拖动观察；所有视图同步。两栏比较适合检查细线、眼部、花纹和噪点区域。页面直接加载 SVG，PNG 仅为备用预览。
整体还原、细节保留、线条连续、色彩渐变，各 1～5 分；允许同分和留空。低清原图不要求补出原本不存在的细节。噪声减少同时也可能损失真实笔触，请据原图判断。

请定期导出 JSON，防止浏览器本地文件自动保存失效。导入同一轮 JSON 可继续评分；旧轮评分会被拒绝，避免混淆。
完成后把导出的 JSON 或 CSV 发回对话。对应表在评分文件夹外独立保管，页面与导出评分都不加载方法身份。
''', encoding='utf-8')
print(json.dumps({'experiment_id': key['experiment_id'], 'images': len(cases), 'svg_files': len(manifest),
                  'bytes': sum(p.stat().st_size for p in PUBLIC.rglob('*') if p.is_file())}))
