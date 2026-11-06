"""Render a small inspection sheet from anonymous previews; no algorithm decisions."""
from pathlib import Path
import json, subprocess, xml.etree.ElementTree as ET
from PIL import Image, ImageOps, ImageDraw, ImageFont
ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / 'outputs/illustration-blind-review-round2'
OUT = ROOT / 'outputs/illustration-round2-study/visual-checks'; OUT.mkdir(exist_ok=True)
data = json.loads((PUBLIC / 'data.js').read_text(encoding='utf-8').removeprefix('window.REVIEW_DATA = ').rstrip(';\n'))
font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 16)
def white(image):
    rgba = image.convert('RGBA'); bg = Image.new('RGBA', rgba.size, 'white'); bg.alpha_composite(rgba); return bg.convert('RGB')
def draw_cell(canvas, image, label, x, y, width=300, height=360):
    image = ImageOps.contain(white(image), (width - 16, height - 32))
    canvas.paste(image, (x + (width - image.width) // 2, y + 28 + (height - 32 - image.height) // 2))
    ImageDraw.Draw(canvas).text((x + 8, y + 5), label, font=font, fill='#243b34')
for start in range(0, 12, 3):
    canvas = Image.new('RGB', (1500, 1080), '#eef1ed')
    for row, case in enumerate(data['cases'][start:start+3]):
        with Image.open(PUBLIC / case['original']) as original: draw_cell(canvas, original, case['id'] + ' source: ' + case['source_name'], 0, row * 360)
        for col, candidate in enumerate(case['candidates'], 1):
            with Image.open(PUBLIC / candidate['preview']) as image: draw_cell(canvas, image, case['id'] + '-' + candidate['id'], col * 300, row * 360)
    canvas.save(OUT / f'all-{start//3+1}.jpg', quality=91)

# User-reported locations are diagnostic views only. They never enter methods.py.
ET.register_namespace('', 'http://www.w3.org/2000/svg')
for source_name, box in [('test03.png', (1460,85,1540,180)), ('test04.png', (380,0,680,300))]:
    case = next(c for c in data['cases'] if c['source_name'] == source_name)
    canvas = Image.new('RGB', (1750, 470), '#eef1ed'); x0,y0,x1,y1 = box
    with Image.open(PUBLIC / case['original']) as original: draw_cell(canvas, original.crop(box), case['id']+' source', 0, 0, 350, 470)
    for col, candidate in enumerate(case['candidates'], 1):
        svg = ET.parse(PUBLIC / candidate['svg']); root = svg.getroot()
        root.set('viewBox', f'{x0} {y0} {x1-x0} {y1-y0}'); root.set('width', str((x1-x0)*6)); root.set('height', str((y1-y0)*6))
        temp = OUT / 'crop.svg'; png = OUT / 'crop.png'; svg.write(temp, encoding='utf-8', xml_declaration=True)
        subprocess.run([str(ROOT/'runtime/node/node.exe'), str(Path(__file__).with_name('rasterize.cjs')), str(temp), str(png)], check=True, capture_output=True)
        with Image.open(png) as image: draw_cell(canvas, image, case['id']+'-'+candidate['id'], col*350, 0, 350, 470)
        temp.unlink(); png.unlink()
    canvas.save(OUT / (Path(source_name).stem+'-detail.jpg'), quality=94)
print('Created four anonymous full-image sheets and two defect-location sheets.')
