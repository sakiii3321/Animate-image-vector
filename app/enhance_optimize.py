"""Differentiable refinement of normalized vector paths against an RGBA target."""
from pathlib import Path
import copy,math,time,xml.etree.ElementTree as ET
import numpy as np
from PIL import Image,ImageColor
from vector_geometry import NS,parse_d,svg_counts


def _color(value):
    if value in (None,'none'):return None
    if value.startswith('rgb('):
        values=[v.strip() for v in value[4:-1].split(',')]
        if len(values)!=3:raise ValueError('不支持的 SVG 颜色。')
        return np.array([float(v[:-1])*2.55 if v.endswith('%') else float(v) for v in values]+[255.],np.float32)/255
    try:return np.asarray(ImageColor.getcolor(value,'RGBA'),np.float32)/255
    except ValueError:raise ValueError('DiffVG 不支持此 SVG 颜色：'+str(value)) from None


def _path_d(shape):
    points=shape.points.detach().cpu().numpy()
    if getattr(shape,'repeat_start',False):points=np.concatenate([points,points[:1]])
    fmt=lambda p:' '.join(f'{float(v):.6f}' for v in p)
    chunks=['M '+fmt(points[0])];idx=1;counts=shape.num_control_points.tolist()
    for k,c in enumerate(counts):
        ids=[(idx+j)%len(points) for j in range(c+1)]
        closing=k==len(counts)-1 and c==0 and shape.is_closed and ids[0]==0
        if not closing:chunks.append(['L ','Q ','C '][c]+' '.join(fmt(points[j]) for j in ids))
        idx+=c+1
    if shape.is_closed:chunks.append('Z')
    return ' '.join(chunks)


def _load_scene(input_path,torch,pydiffvg):
    root=ET.parse(input_path).getroot();shapes=[];records=[];parameters=[]
    # Production normalization guarantees one direct path per group and no transforms.
    for group in root:
        if group.tag!=NS+'g' or len(group)!=1 or group[0].tag!=NS+'path':raise ValueError('DiffVG 输入须先规范化为独立路径组。')
        node=group[0]
        if group.get('transform') or node.get('transform'):raise ValueError('DiffVG 输入仍有未展开的坐标变换。')
        opacity=float(group.get('opacity','1'))*float(node.get('opacity','1'))
        fill=_color(node.get('fill','black'));stroke=_color(node.get('stroke','none'))
        if opacity<1 and fill is not None and stroke is not None:
            raise ValueError('DiffVG 暂不支持同时含填充与描边的半透明组合。请关闭 DiffVG 和高分辨率补充优化；超分与曲线简化仍可保留透明度。')
        if stroke is not None and node.get('stroke-linejoin','round') not in ('round',):
            raise ValueError('DiffVG 暂只支持圆角描边；请关闭优化或使用 Potrace 的圆角路径。')
        ids=[]
        for contour in parse_d(node.get('d','')):
            segs=contour.segments
            if not segs:continue
            # An unclosed filled subpath has an implicit closing edge. Preserve open
            # stroked subpaths rather than adding an unwanted closing stroke.
            closed=contour.closed
            if fill is not None and not closed and stroke is None:
                if np.linalg.norm(segs[-1][-1]-segs[0][0])>1e-8:segs.append(np.array([segs[-1][-1],segs[0][0]]))
                closed=True
            pts=[segs[0][0]];counts=[]
            for s in segs:pts.extend(s[1:]);counts.append(len(s)-2)
            # Potrace writes an open SVG subpath whose final endpoint repeats its
            # start. Tie those endpoints to one parameter without changing the
            # original stroke-cap/closure semantics. Independent endpoints would
            # drift apart and create an extra implicit fill-closing segment.
            repeat_start=not closed and np.linalg.norm(pts[-1]-pts[0])<1e-7
            if (closed or repeat_start) and np.linalg.norm(pts[-1]-pts[0])<1e-7:pts.pop()
            if not pts:continue
            points=torch.tensor(np.asarray(pts),dtype=torch.float32).requires_grad_(True)
            shape=pydiffvg.Path(torch.tensor(counts,dtype=torch.int32),points,closed,
                                 stroke_width=torch.tensor(float(node.get('stroke-width','0'))))
            shape.repeat_start=repeat_start
            ids.append(len(shapes));shapes.append(shape)
        if not ids:continue
        paint={};initial={};export_opacity={}
        for kind,c in [('fill',fill),('stroke',stroke)]:
            if c is None:paint[kind]=None;continue
            # Only RGB is trainable; retain input fill/stroke/group alpha exactly.
            export_opacity[kind]=float(c[3])*float(node.get(kind+'-opacity','1'))
            c[3]*=opacity*float(node.get(kind+'-opacity','1'))
            if not 0<=c[3]<=1:raise ValueError('SVG 透明度无效。')
            if kind=='stroke' and fill is not None and np.array_equal(c[:3],fill[:3]):
                value=paint['fill'][0]
            else:value=torch.tensor(c[:3].copy(),dtype=torch.float32).requires_grad_(True);parameters.append(value)
            paint[kind]=(value,float(c[3]));initial[kind]=c.copy()
        records.append({'node':node,'ids':ids,'paint':paint,'initial':initial,'export_opacity':export_opacity,
                        'even_odd':node.get('fill-rule','nonzero')=='evenodd'})
    return root,shapes,records,parameters


def run(job,record):
    import torch,pydiffvg
    torch.set_num_threads(4);torch.manual_seed(42);pydiffvg.set_use_gpu(False)
    started=time.perf_counter();config=job['config'];target_image=Image.open(job['target']).convert('RGBA')
    width=int(job['width']);height=int(job['height'])
    if min(width,height)<=0:raise ValueError('优化画布尺寸无效。')
    if abs(target_image.width/width-target_image.height/height)>1e-5:raise ValueError('优化目标与 SVG 宽高比不一致。')
    if config.get('highres_refine') and not config.get('sr_enabled'):raise ValueError('高分辨率补充优化需要先启用超分辨率。')
    record('postprocess_prepare',current=0,total=1)
    before=svg_counts(job['input']);root,shapes,records,colors=_load_scene(job['input'],torch,pydiffvg)
    points=[s.points for s in shapes];p0=[p.detach().clone() for p in points];c0=[c.detach().clone() for c in colors]
    output=Path(job['output'])
    if not points or not colors or not any(v and v[1]>0 for r in records for v in r['paint'].values()):
        output.write_bytes(Path(job['input']).read_bytes())
        return {'skipped':'empty_or_invisible_svg','before':before,'after':before,'elapsed_seconds':time.perf_counter()-started}
    node_count=sum(p.numel() for p in points)
    optimizer=torch.optim.Adam([{'params':points,'lr':.025},{'params':colors,'lr':.001}],foreach=True)
    def paint(r,kind):
        value=r['paint'][kind]
        return None if value is None else torch.cat([value[0],value[0].new_tensor([value[1]])])
    def render(canvas_w,canvas_h,scale,offset=(0.,0.),selected=None):
        chosen=range(len(records)) if selected is None else selected
        ss=[];gg=[];offset_tensor=torch.tensor(offset,dtype=torch.float32);scale_tensor=torch.tensor(scale,dtype=torch.float32)
        for index in chosen:
            r=records[index];ids=[]
            for sid in r['ids']:
                s=copy.copy(shapes[sid]);native=shapes[sid].points
                if s.repeat_start:native=torch.cat([native,native[:1]])
                s.points=(native-offset_tensor)*scale_tensor
                s.stroke_width=shapes[sid].stroke_width*float(scale_tensor.mean());ids.append(len(ss));ss.append(s)
            gg.append(pydiffvg.ShapeGroup(torch.tensor(ids,dtype=torch.int32),paint(r,'fill'),
                         use_even_odd_rule=r['even_odd'],stroke_color=paint(r,'stroke')))
        if not ss:return None
        scene=pydiffvg.RenderFunction.serialize_scene(canvas_w,canvas_h,ss,gg)
        return pydiffvg.RenderFunction.apply(canvas_w,canvas_h,2,2,42,None,*scene)
    def tensor_image(im):return torch.tensor(np.asarray(im).copy(),dtype=torch.float32)/255
    def update(raw,target):
        if raw is None:return {'skipped_empty_tile':True}
        alpha=raw[:,:,3:4];ta=target[:,:,3:4]
        premul=raw[:,:,:3]*alpha;reference=target[:,:,:3]*ta
        mse=(premul-reference).square().mean();edge=mse.new_zeros(())
        if raw.shape[0]>1:edge=edge+((premul[1:]-premul[:-1])-(reference[1:]-reference[:-1])).abs().mean()
        if raw.shape[1]>1:edge=edge+((premul[:,1:]-premul[:,:-1])-(reference[:,1:]-reference[:,:-1])).abs().mean()
        coverage=(alpha-ta).square().mean()
        reg=sum((p-q).square().sum() for p,q in zip(points,p0))/node_count
        loss=mse+.2*edge+coverage+.002*reg
        if not torch.isfinite(loss):raise ValueError('DiffVG 产生非有限损失，已停止。')
        loss.backward()
        if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in points+colors):raise ValueError('DiffVG 产生非有限梯度，已停止。')
        optimizer.step()
        with torch.no_grad():
            for p,q in zip(points,p0):p.copy_(q+(p-q).clamp(-.6,.6))
            for c,q in zip(colors,c0):c.copy_((q+(c-q).clamp(-.03,.03)).clamp(0,1))
        return {'loss':float(loss.detach()),'mse':float(mse.detach()),'edge_l1':float(edge.detach()),'alpha_mse':float(coverage.detach())}
    steps=int(config.get('diffvg_iterations',30)) if config.get('diffvg_optimize') else 0
    if config.get('diffvg_optimize') and not 1<=steps<=100:raise ValueError('DiffVG 迭代次数必须在 1–100 之间。')
    # Bound the complete frame's longest side and never upscale a small source.
    factor=min(1.,1024/max(width,height));cw=max(1,round(width*factor));ch=max(1,round(height*factor))
    target=tensor_image(target_image.resize((cw,ch),Image.Resampling.LANCZOS));trace=[]
    for step in range(1,steps+1):
        optimizer.zero_grad(set_to_none=True);raw=render(cw,ch,[cw/width,ch/height]);metrics=update(raw,target)
        row={'stage':'diffvg_global','current':step,'total':steps,**metrics};trace.append(row);record(**row)
    touched=set();covered=0;tile_count=0
    if config.get('highres_refine'):
        sx=target_image.width/width;sy=target_image.height/height
        nx=max(1,math.ceil(target_image.width/1024));ny=max(1,math.ceil(target_image.height/1024))
        xs=np.linspace(0,target_image.width,nx+1,dtype=int);ys=np.linspace(0,target_image.height,ny+1,dtype=int)
        boxes=[(int(xs[x]),int(ys[y]),int(xs[x+1]),int(ys[y+1])) for y in range(ny) for x in range(nx)]
        order=np.random.default_rng(42).permutation(len(boxes));tile_count=len(boxes)
        bounds=[]
        for r in records:
            allpoints=torch.cat([shapes[i].points.detach() for i in r['ids']]).numpy()
            margin=max(float(shapes[i].stroke_width) for i in r['ids'])/2+1
            bounds.append((allpoints.min(axis=0)-margin,allpoints.max(axis=0)+margin))
        for step,tid in enumerate(order,1):
            x0,y0,x1,y1=boxes[tid];padx=math.ceil(16*sx);pady=math.ceil(16*sy)
            bx=max(0,x0-padx);by=max(0,y0-pady);rx=min(target_image.width,x1+padx);ry=min(target_image.height,y1+pady)
            selected=[i for i,(lo,hi) in enumerate(bounds) if hi[0]>=bx/sx and hi[1]>=by/sy and lo[0]<=rx/sx and lo[1]<=ry/sy]
            optimizer.zero_grad(set_to_none=True);raw=render(rx-bx,ry-by,[sx,sy],(bx/sx,by/sy),selected)
            if raw is not None:raw=raw[y0-by:y1-by,x0-bx:x1-bx]
            metrics=update(raw,tensor_image(target_image.crop((x0,y0,x1,y1))))
            touched.update(selected);covered+=(x1-x0)*(y1-y0)
            row={'stage':'highres_refine','current':step,'total':tile_count,'target_box':[x0,y0,x1,y1],**metrics};trace.append(row);record(**row)
        if covered!=target_image.width*target_image.height:raise ValueError('高分辨率补充未覆盖完整画面。')
    for r in records:
        node=r['node'];node.set('d',' '.join(_path_d(shapes[i]) for i in r['ids']))
        for kind in ('fill','stroke'):
            value=r['paint'][kind]
            if value is not None:
                node.set(kind,'rgb('+','.join(f'{float(v)*255:.6f}' for v in value[0].detach().cpu())+')')
                node.set(kind+'-opacity',f'{r["export_opacity"][kind]:.8g}')
    ET.register_namespace('','http://www.w3.org/2000/svg');ET.ElementTree(root).write(output,encoding='utf-8',xml_declaration=True)
    after=svg_counts(output)
    if any(before[k]!=after[k] for k in ('fill_paths','contours','total_segments','curve_segments','nodes')):
        raise ValueError('DiffVG 导出改变了路径结构，结果未提交。')
    return {'before':before,'after':after,'global_steps':steps,'global_size':[cw,ch],
            'highres_tiles':tile_count,'covered_target_pixels':covered,'target_pixels':target_image.width*target_image.height,
            'touched_paths':len(touched),'active_paths':len(records),'target_size':list(target_image.size),
            'alpha_preserved':True,'elapsed_seconds':time.perf_counter()-started,'trace':trace}
