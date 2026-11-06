"""Fixed-method illustration examples for manually selected local refinement.

Only the polygons differ between images. Full-size validation renders are
temporary; the retained deliverables are candidate SVGs, cropped panels and JSON.
"""
from pathlib import Path
import json
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app'))
from illustration_engine import render_svg
from local_refine import refine_selection, _selection_mask
from drawing_stats import drawing_counts

CASES = [
    ('134948250_p0', [[785,948],[822,888],[920,807],[1012,800],[1054,832],
                     [1048,903],[957,984],[902,1032],[826,1034]]),
    ('test03', [[1160,360],[1210,330],[1330,310],[1420,335],[1440,435],
                [1390,520],[1300,555],[1220,520],[1160,440]]),
    ('test04', [[950,900],[1030,880],[1160,930],[1220,1000],
                [1190,1080],[1080,1120],[970,1080],[930,990]]),
]
OPTIONS = {'path_limit':300, 'detail':'fine'}


def make_panel(source, before, after, polygon, destination):
    margin = 18
    x0 = max(0, min(p[0] for p in polygon)-margin)
    y0 = max(0, min(p[1] for p in polygon)-margin)
    x1 = min(source.width, max(p[0] for p in polygon)+margin)
    y1 = min(source.height, max(p[1] for p in polygon)+margin)
    box = (x0,y0,x1,y1)
    images = [source.crop(box),Image.fromarray(before).crop(box),Image.fromarray(after).crop(box)]
    draw = ImageDraw.Draw(images[0])
    outline=[(x-x0,y-y0) for x,y in polygon]
    draw.line(outline+[outline[0]],fill=(234,65,75,255),width=1)
    target_width=520
    ratio=target_width/(x1-x0)
    target_height=round((y1-y0)*ratio)
    canvas=Image.new('RGB',(3*target_width+48,target_height+85),(248,249,247))
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
    small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',15)
    d=ImageDraw.Draw(canvas)
    for index,(image,title) in enumerate(zip(images,['Original + selection','Current edge_clean','Local refine: fine / 300'])):
        x=12+index*(target_width+12)
        d.text((x,12),title,font=font,fill=(25,43,38))
        display=image.resize((target_width,target_height),Image.Resampling.LANCZOS)
        canvas.paste(display,(x,45),display.getchannel('A'))
    d.text((12,target_height+56),'Same crop and scale. Pixel error is a reference metric, not a visual-quality rating.',font=small,fill=(75,85,80))
    canvas.save(destination)
    return list(box)


def main():
    output=ROOT/'outputs/local-refinement-study/examples'
    output.mkdir(parents=True,exist_ok=True)
    results=[]
    for name,polygon in CASES:
        current=ROOT/'outputs/software-optimization-study/regression'/name/'edge_clean/output.svg'
        source_path=ROOT/'test_pic'/(name+'.png')
        with Image.open(source_path) as image:
            source=image.convert('RGBA')
        print('Start',name,source.size,flush=True)
        with tempfile.TemporaryDirectory(prefix='validation-',dir=output) as tmp:
            work=Path(tmp)
            result=refine_selection(source_path.read_bytes(),current.read_bytes(),polygon,OPTIONS,work)
            final_svg=output/(name+'-refined.svg')
            final_svg.write_bytes(result['svg'])
            before=render_svg(ET.parse(current).getroot(),work/'before.png')
            after=render_svg(ET.fromstring(result['svg']),work/'after.png')
            selected=_selection_mask(polygon,(0,0,source.width,source.height))
            outside=~ndi.binary_dilation(selected,iterations=3)
            changed=np.any(before!=after,axis=2)
            outside_changed=int(np.count_nonzero(changed&outside))
            outside_max=0
            for channel in range(4):
                delta=np.abs(before[:,:,channel].astype(np.int16)-after[:,:,channel].astype(np.int16))
                outside_max=max(outside_max,int(delta[outside].max()))
            reference=np.asarray(source)
            mae_before=float(np.abs(reference[selected,:3].astype(float)-before[selected,:3]).mean())
            mae_after=float(np.abs(reference[selected,:3].astype(float)-after[selected,:3]).mean())
            interior=ndi.binary_erosion(selected,iterations=3)
            counts=drawing_counts(final_svg)
            root=ET.fromstring(result['svg'])
            old_paths=[dict(element.attrib) for element in ET.parse(current).getroot().iter()
                       if element.tag.rsplit('}',1)[-1]=='path']
            new_paths=[dict(element.attrib) for element in root.iter()
                       if element.tag.rsplit('}',1)[-1]=='path']
            old_paths_unchanged=old_paths==new_paths[:len(old_paths)]
            assert old_paths_unchanged
            ids=[element.get('id') for element in root.iter() if element.get('id')]
            assert len(ids)==len(set(ids))
            assert counts['embedded_images']==0
            assert counts['drawing_paths']==result['report']['after_paths']
            assert result['report']['added_paths']<=OPTIONS['path_limit']
            outside_y,outside_x=np.nonzero(changed&outside)
            outside_box=([int(outside_x.min()),int(outside_y.min()),int(outside_x.max())+1,int(outside_y.max())+1]
                         if outside_changed else None)
            frame=(outside_x<3)|(outside_x>=source.width-3)|(outside_y<3)|(outside_y>=source.height-3)
            panel_box=make_panel(source,before,after,polygon,output/(name+'-comparison.png'))
            report={'image':name,'source':str(source_path.relative_to(ROOT)),
                'current_svg':str(current.relative_to(ROOT)), 'options':OPTIONS,
                'refinement':result['report'],'validation':{
                    'render_size':[after.shape[1],after.shape[0]],
                    'outside_excluded_boundary_pixels':3,
                    'outside_compared_pixels':int(np.count_nonzero(outside)),
                    'outside_changed_pixels':outside_changed,'outside_max_rgba_difference':outside_max,
                    'outside_changed_bbox':outside_box,'outside_changed_in_3px_canvas_frame':int(frame.sum()),
                    'outside_changed_fraction':outside_changed/max(1,int(np.count_nonzero(outside))),
                    'all_old_path_attributes_unchanged':old_paths_unchanged,
                    'selected_rgb_mae_before':mae_before,'selected_rgb_mae_after':mae_after,
                    'interior_rgb_mae_before':float(np.abs(reference[interior,:3].astype(float)-before[interior,:3]).mean()),
                    'interior_rgb_mae_after':float(np.abs(reference[interior,:3].astype(float)-after[interior,:3]).mean()),
                    'embedded_images':counts['embedded_images'],'ids_unique':True,'counts':counts,
                    'panel_crop_box':panel_box,
                    'metric_note':'RGB MAE measures reference-pixel reconstruction, not line smoothness or subjective illustration quality.'}}
            (output/(name+'-report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            results.append(report)
            print(name,'added',result['report']['added_paths'],'total',counts['drawing_paths'],
                  'MAE',round(mae_before,3),'->',round(mae_after,3),'outside changed',outside_changed,flush=True)
    (output/'summary.json').write_text(json.dumps({'method_options':OPTIONS,'cases':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Saved',output,flush=True)


if __name__ == '__main__':
    main()
