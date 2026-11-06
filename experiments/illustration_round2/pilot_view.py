from pathlib import Path
import json,sys,subprocess,xml.etree.ElementTree as ET
from PIL import Image,ImageDraw,ImageOps
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/illustration-round2-study'
ET.register_namespace('','http://www.w3.org/2000/svg')
def compare(name,box,methods):
    folder=OUT/'pilot-checks';folder.mkdir(exist_ok=True)
    labels=['Source']+methods;images=[Image.open(ROOT/'test_pic'/name).convert('RGBA').crop(box)]
    for method in methods:
        svg=OUT/'cases'/Path(name).stem/method/'output.svg'
        if not svg.exists():return
        tree=ET.parse(svg);root=tree.getroot();x0,y0,x1,y1=box
        root.set('viewBox',f'{x0} {y0} {x1-x0} {y1-y0}');root.set('width',str((x1-x0)*5));root.set('height',str((y1-y0)*5))
        output=folder/f'{Path(name).stem}-{method}.svg';tree.write(output,encoding='utf-8',xml_declaration=True)
        png=output.with_suffix('.png')
        subprocess.run([str(ROOT/'runtime/node/node.exe'),str(Path(__file__).with_name('rasterize.cjs')),str(output),str(png)],check=True,capture_output=True)
        images.append(Image.open(png).convert('RGBA'))
    heights=[];tiles=[]
    for im in images:
        scale=320/im.width;im=im.resize((320,round(im.height*scale)),Image.Resampling.LANCZOS)
        tile=Image.new('RGBA',im.size,'white');tile.alpha_composite(im);tiles.append(tile.convert('RGB'));heights.append(im.height)
    sheet=Image.new('RGB',(340*len(images),max(heights)+50),'#eeeeee');draw=ImageDraw.Draw(sheet)
    for i,(label,tile) in enumerate(zip(labels,tiles)):sheet.paste(tile,(340*i+10,35));draw.text((340*i+10,10),label,fill='#222222')
    sheet.save(folder/(Path(name).stem+'-compare.jpg'),quality=95)
compare('test03.png',(1460,85,1540,180),['control','edge_clean'])
compare('test04.png',(380,0,680,300),['control','gradient_layers'])
