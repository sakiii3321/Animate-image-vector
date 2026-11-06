"""Generic local experiments: texture/edge cleanup, residual layers, SVG gradients.

No filenames, annotated locations or image-specific settings enter these methods.
These are new implementations inspired by the recorded literature, not paper reproductions.
"""
from pathlib import Path
import copy,json,math,subprocess,sys
import xml.etree.ElementTree as ET
import cv2,numpy as np
from scipy import ndimage as ndi
from PIL import Image
from skimage.measure import label
from skimage.morphology import skeletonize
from sklearn.cluster import MiniBatchKMeans

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app'))
from core import DEFAULTS
from potrace_engine import prepare_regions,trace_regions
from vector_geometry import normalize_svg,simplify_svg,svg_counts
NS='{http://www.w3.org/2000/svg}'
ET.register_namespace('','http://www.w3.org/2000/svg')
PROTOCOL={'version':4,'path_budget':2000,'base_regions':1200,'base_palette':64,
          'line_pass_limit':700,'residual_palette':24,'gradient_validation_improvement':.25,
          'texture_filter':'two bilateral passes, sigmaColor=18, sigmaSpace=1.5*scale',
          'scale_rule':'clip(max(width,height)/2000,0.75,2)',
          'crop':None,'ROI':None,'SR':False,'DiffVG':False}

def use_area_cost():
    from merge_cost import MergeCosts
    def cost(self,a,b):
        ma,mb=self.descriptors[a][1],self.descriptors[b][1]
        return (ma*mb/(ma+mb))**.75*math.sqrt(max(self.descriptors[a][2],self.descriptors[b][2]))*self.color_difference_squared(a,b)
    MergeCosts.cost=cost

def spatial_scale(shape):return float(np.clip(max(shape[:2])/2000,.75,2))

def clean_texture(rgba):
    """Mild, fixed edge-aware filtering; source alpha is never synthesized."""
    rgb=np.ascontiguousarray(rgba[:,:,:3]);s=spatial_scale(rgb.shape)
    diameter=2*max(2,round(2*s))+1
    for _ in range(2):rgb=cv2.bilateralFilter(rgb,diameter,18,1.5*s)
    out=rgba.copy();out[:,:,:3]=rgb;out[rgba[:,:,3]==0]=rgba[rgba[:,:,3]==0]
    return out

def records_for(labels,rgba,old_colors=None):
    ids=np.unique(labels);ids=ids[ids>0]
    lut=np.zeros(int(labels.max())+1,np.uint16);lut[ids]=np.arange(1,len(ids)+1,dtype=np.uint16)
    labels=lut[labels];areas=np.bincount(labels.ravel(),minlength=len(ids)+1)
    if old_colors is None:
        sums=np.stack([np.bincount(labels.ravel(),weights=rgba[:,:,i].ravel(),minlength=len(ids)+1) for i in range(4)],axis=1)
    records=[]
    for new,(old,box) in enumerate(zip(ids,ndi.find_objects(labels)),1):
        sy,sx=box
        color=old_colors[old] if old_colors is not None else np.round(sums[new]/areas[new]).clip(0,255).astype(np.uint8)
        records.append({'id':new,'area':int(areas[new]),'bbox':[sx.start,sy.start,sx.stop,sy.stop],
                        'color':list(map(int,color)),'feature_id':0})
    return labels,records

def remove_edge_mixtures(labels,records,scale=1):
    """Absorb thin intermediate-color fragments only when two adjacent endpoints explain them.

    Isolated real dots have no two-color mixture support and are retained.
    Larger/darker independent cores are not treated as anti-aliasing merely for being small.
    """
    n=len(records)+1;areas=np.zeros(n,np.int64);colors=np.zeros((n,4),float)
    for r in records:areas[r['id']]=r['area'];colors[r['id']]=r['color']
    boundary=np.zeros(labels.shape,bool);pairs=[]
    for a,b,axis in [(labels[:,:-1],labels[:,1:],1),(labels[:-1,:],labels[1:,:],0)]:
        different=a!=b
        if axis:boundary[:,:-1]|=different;boundary[:,1:]|=different
        else:boundary[:-1,:]|=different;boundary[1:,:]|=different
        valid=different&(a>0)&(b>0)
        aa,bb=a[valid].astype(np.int64),b[valid].astype(np.int64)
        pairs.append(np.minimum(aa,bb)*n+np.maximum(aa,bb))
    encoded,counts=np.unique(np.concatenate(pairs),return_counts=True)
    neighbors=[[] for _ in range(n)]
    for p,count in zip(encoded,counts):
        a,b=divmod(int(p),n);neighbors[a].append((b,int(count)));neighbors[b].append((a,int(count)))
    depth=ndi.distance_transform_edt(~boundary)
    maxdepth=ndi.maximum(depth,labels,index=np.arange(n));del depth
    parent=np.arange(n);removed=[]
    for i in range(1,n):
        if areas[i]>400*scale*scale or maxdepth[i]>1.1*scale:continue
        adjacent=[j for j,_ in sorted(neighbors[i],key=lambda item:-item[1]) if areas[j]>=3*areas[i] and abs(colors[j,3]-colors[i,3])<4][:5]
        best=None
        for ai,a in enumerate(adjacent):
            for b in adjacent[ai+1:]:
                direction=colors[b,:3]-colors[a,:3];norm=float(direction@direction)
                if norm<25**2:continue
                t=float((colors[i,:3]-colors[a,:3])@direction/norm)
                error=float(np.linalg.norm(colors[i,:3]-(colors[a,:3]+t*direction)))
                if .08<t<.92 and error<10 and (best is None or error<best[0]):
                    best=(error,a if t<.5 else b,a,b,t)
        if best:
            parent[i]=best[1];removed.append({'id':i,'area':int(areas[i]),'target':int(best[1]),'mixture_error':best[0]})
    while np.any(parent!=parent[parent]):parent=parent[parent]
    merged=parent[labels].astype(np.uint16)
    merged,new_records=records_for(merged,None,old_colors=colors)
    return merged,new_records,removed

def join_thin_neighbors(labels,records,scale=1):
    """Join compatible thin regions, including diagonal contacts lost by 4-connectivity."""
    n=len(records)+1;colors=np.zeros((n,4),np.uint8);boundary=np.zeros(labels.shape,bool)
    for r in records:colors[r['id']]=r['color']
    boundary[:,1:]|=labels[:,1:]!=labels[:,:-1];boundary[:,:-1]|=labels[:,1:]!=labels[:,:-1]
    boundary[1:]|=labels[1:]!=labels[:-1];boundary[:-1]|=labels[1:]!=labels[:-1]
    depth=ndi.maximum(ndi.distance_transform_edt(~boundary),labels,index=np.arange(n))
    lab=cv2.cvtColor(colors[None,:,:3],cv2.COLOR_RGB2LAB)[0].astype(float);lab[:,0]/=2.55
    parent=np.arange(n);unions=0
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    pairs=[]
    for a,b in [(labels[:-1,:-1],labels[1:,1:]),(labels[:-1,1:],labels[1:,:-1]),(labels[:,:-1],labels[:,1:]),(labels[:-1],labels[1:])]:
        valid=(a!=b)&(a>0)&(b>0);aa,bb=a[valid].astype(np.int64),b[valid].astype(np.int64)
        pairs.append(np.minimum(aa,bb)*n+np.maximum(aa,bb))
    for encoded in np.unique(np.concatenate(pairs)):
        a,b=divmod(int(encoded),n)
        if max(depth[a],depth[b])>1.2*scale or abs(int(colors[a,3])-int(colors[b,3]))>4:continue
        if np.linalg.norm(lab[a]-lab[b])>9:continue
        ra,rb=root(a),root(b)
        if ra!=rb:parent[rb]=ra;unions+=1
    for i in range(n):parent[i]=root(i)
    merged,items=records_for(parent[labels].astype(np.uint16),colors[labels])
    return merged,items,unions

def skeleton_chains(mask):
    """Trace graph edges once. Suppress triangle shortcuts in the 8-neighbor skeleton."""
    skel=skeletonize(mask);yy,xx=np.nonzero(skel);pixels=set(zip(map(int,yy),map(int,xx)))
    graph={}
    for y,x in pixels:
        adj=[]
        for dy,dx in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
            q=(y+dy,x+dx)
            if q not in pixels:continue
            if dy and dx and ((y+dy,x) in pixels or (y,x+dx) in pixels):continue
            adj.append(q)
        graph[(y,x)]=adj
    # Several neighboring skeleton pixels can encode one junction. Contract
    # them to one shared point instead of dropping their short connecting edges.
    branches={p for p in graph if len(graph[p])>2};joint={};unseen=branches.copy()
    while unseen:
        first=unseen.pop();cluster=[first];queue=[first]
        while queue:
            p=queue.pop()
            for q in graph[p]:
                if q in unseen:unseen.remove(q);cluster.append(q);queue.append(q)
        center=np.mean([(x+.5,y+.5) for y,x in cluster],axis=0)
        for p in cluster:joint[p]=center
    used=set();chains=[]
    starts=sorted(p for p in graph if len(graph[p])!=2)+sorted(p for p in graph if len(graph[p])==2)
    for start in starts:
        for nxt in graph[start]:
            edge=tuple(sorted((start,nxt)))
            if edge in used:continue
            used.add(edge);points=[start,nxt];previous,current=start,nxt
            while current!=start and len(graph[current])==2:
                following=graph[current][0] if graph[current][1]==previous else graph[current][1]
                edge=tuple(sorted((current,following)))
                if edge in used:break
                used.add(edge);points.append(following);previous,current=current,following
            curve=np.asarray([(x+.5,y+.5) for y,x in points],float)
            if points[0] in joint:curve[0]=joint[points[0]]
            if points[-1] in joint:curve[-1]=joint[points[-1]]
            if np.max(np.linalg.norm(curve-curve[0],axis=1))<.2:continue
            chains.append(curve)
    return chains

def centerline_paths(source,current,mask,limit):
    s=spatial_scale(source.shape);distance=cv2.distanceTransform(mask.astype(np.uint8),cv2.DIST_L2,3)
    candidates=[]
    for chain in skeleton_chains(mask):
        length=float(np.linalg.norm(np.diff(chain,axis=0),axis=1).sum())
        if length<10*s or len(chain)<5:continue
        xx=np.clip(chain[:,0].astype(int),0,source.shape[1]-1);yy=np.clip(chain[:,1].astype(int),0,source.shape[0]-1)
        target=source[yy,xx,:3].astype(float);prediction=current[yy,xx,:3].astype(float)
        color=np.median(target,axis=0);before=float(np.sum((target-prediction)**2));after=float(np.sum((target-color)**2))
        if before-after<120 or after>.85*before:continue
        width=float(np.clip(2*np.median(distance[yy,xx])-.5,.6,12*s))
        candidates.append(((before-after)*width,chain,width,np.round(color).astype(int)))
    group=ET.Element(NS+'g');guard=np.zeros(mask.shape,np.uint8)
    for gain,chain,width,color in sorted(candidates,key=lambda item:-item[0])[:limit]:
        # Smooth pixel stair steps before fitting a continuous cubic centerline.
        points=chain.copy()
        if len(points)>5:
            points=ndi.gaussian_filter1d(points,.7,axis=0,mode='nearest');points[0]=chain[0];points[-1]=chain[-1]
        points=cv2.approxPolyDP(points.astype(np.float32),.75*s,False).reshape(-1,2).astype(float)
        if len(points)<2:continue
        d=[f'M {points[0,0]:.4f} {points[0,1]:.4f}']
        for i in range(len(points)-1):
            a,b=points[i],points[i+1];previous=points[max(0,i-1)];following=points[min(len(points)-1,i+2)]
            c1=a+(b-previous)/6;c2=b-(following-a)/6
            d.append(f'C {c1[0]:.4f} {c1[1]:.4f} {c2[0]:.4f} {c2[1]:.4f} {b[0]:.4f} {b[1]:.4f}')
        ET.SubElement(group,NS+'path',{'d':' '.join(d),'fill':'none','stroke':'#'+''.join(f'{v:02x}' for v in color),
            'stroke-width':f'{width:.4f}','stroke-linecap':'round','stroke-linejoin':'round'})
        cv2.polylines(guard,[np.round(chain-.5).astype(np.int32)],False,1,max(1,math.ceil(width+2*s)))
    return group,guard>0,{'considered':len(candidates),'selected':len(group)}

def trace(labels,records,work,params,record):
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    trace_regions(labels,records,work/'raw.svg',params,record)
    normalize_svg(work/'raw.svg',work/'normalized.svg',labels.shape[1],labels.shape[0])
    simplify_svg(work/'normalized.svg',work/'curves.svg',.3,record)
    return ET.parse(work/'curves.svg').getroot()

def render(root,destination):
    destination=Path(destination);svg=destination.with_suffix('.svg')
    ET.ElementTree(root).write(svg,encoding='utf-8',xml_declaration=True)
    subprocess.run([str(ROOT/'runtime/node/node.exe'),str(Path(__file__).with_name('rasterize.cjs')),str(svg),str(destination)],
                   check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    with Image.open(destination) as image:out=np.asarray(image.convert('RGBA')).copy()
    return out

def ridge_mask(rgba):
    rgb=np.ascontiguousarray(rgba[:,:,:3]);gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    s=spatial_scale(rgba.shape);radius=max(3,round(5*s));kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*radius+1,)*2)
    dark=cv2.morphologyEx(gray,cv2.MORPH_BLACKHAT,kernel).astype(float)
    bright=cv2.morphologyEx(gray,cv2.MORPH_TOPHAT,kernel).astype(float)
    strong=np.maximum(dark,bright)>16
    # Estimate stroke coverage from the local ridge response. Low-coverage
    # anti-alias fringes must not become opaque, wider replacement strokes.
    local_dark=cv2.dilate(dark,np.ones((2*radius+1,)*2,np.uint8))
    local_bright=cv2.dilate(bright,np.ones((2*radius+1,)*2,np.uint8))
    weak=(((dark>6)&(dark>=.4*local_dark))|((bright>6)&(bright>=.4*local_bright)))&(rgba[:,:,3]>250)
    mask=ndi.binary_propagation(strong&weak,mask=weak)
    components,count=ndi.label(mask,np.ones((3,3),np.uint8));distance=cv2.distanceTransform(mask.astype(np.uint8),cv2.DIST_L2,3)
    areas=np.bincount(components.ravel());widths=ndi.mean(distance,components,index=np.arange(1,count+1))*2
    lengths=areas[1:]/np.maximum(1,widths)
    keep=(lengths>=10*s)&(lengths/np.maximum(1,widths)>=3)
    lookup=np.r_[False,keep];return lookup[components]

def fit_gradient(points,values,flat_color):
    """Fit one SVG linear gradient; validation pixels decide whether it replaces a flat fill."""
    if len(points)<80:return None
    points=np.asarray(points,float);values=np.asarray(values,float)
    if len(points)>4096:
        take=np.random.default_rng(42).choice(len(points),4096,replace=False);points=points[take];values=values[take]
    origin=points.mean(axis=0);scale=max(1,float(np.ptp(points,axis=0).max()));xy=(points-origin)/scale
    train=np.arange(len(points))%4!=0;valid=~train
    plane=np.column_stack((np.ones(len(points)),xy))
    coefficients=np.linalg.lstsq(plane[train],values[train],rcond=None)[0]
    direction=np.linalg.svd(coefficients[1:],full_matrices=False)[0][:,0]
    projected=xy@direction;lo,hi=float(projected.min()),float(projected.max())
    if hi-lo<1e-6:return None
    t=(projected-lo)/(hi-lo)
    basis=np.column_stack((np.maximum(1-2*t,0),1-np.abs(2*t-1),np.maximum(2*t-1,0)))
    weights=np.ones(train.sum())
    for _ in range(3):
        design=basis[train]*weights[:,None]**.5
        stops=np.linalg.lstsq(design,values[train]*weights[:,None]**.5,rcond=None)[0].clip(0,255)
        residual=np.linalg.norm(basis[train]@stops-values[train],axis=1)
        weights=np.minimum(1,8/np.maximum(1,residual))
    before=float(np.mean((values[valid]-np.asarray(flat_color))**2));after=float(np.mean((basis[valid]@stops-values[valid])**2))
    if before<4 or after>before*.75 or before-after<1.5 or np.linalg.norm(stops[0]-stops[-1])<3:return None
    return {'start':(origin+direction*lo*scale).tolist(),'end':(origin+direction*hi*scale).tolist(),
            'stops':np.round(stops).astype(int).tolist(),'validation_mse_before':before,'validation_mse_after':after}

def add_gradients(root,labels,records,source):
    paths=list(root.iter(NS+'path'))
    if len(paths)!=len(records):raise ValueError('Region/path correspondence lost before gradient fitting')
    defs=ET.Element(NS+'defs');root.insert(0,defs);fits=[]
    for path,r in zip(paths,records):
        if r['area']<80 or r['color'][3]<250:continue
        x0,y0,x1,y1=r['bbox'];mask=labels[y0:y1,x0:x1]==r['id']
        inner=cv2.erode(mask.astype(np.uint8),np.ones((3,3),np.uint8))>0
        yy,xx=np.nonzero(inner)
        if len(xx)<80:continue
        fit=fit_gradient(np.column_stack((xx+x0,yy+y0)),source[y0:y1,x0:x1,:3][inner],r['color'][:3])
        if not fit:continue
        ident='g'+str(len(fits)+1)
        gradient=ET.SubElement(defs,NS+'linearGradient',{'id':ident,'gradientUnits':'userSpaceOnUse',
            'x1':str(fit['start'][0]),'y1':str(fit['start'][1]),'x2':str(fit['end'][0]),'y2':str(fit['end'][1]),'color-interpolation':'sRGB'})
        for offset,color in zip(('0','.5','1'),fit['stops']):ET.SubElement(gradient,NS+'stop',{'offset':offset,'stop-color':'#'+''.join(f'{v:02x}' for v in color)})
        path.set('fill',f'url(#{ident})')
        if path.get('stroke')!='none':path.set('stroke',f'url(#{ident})')
        fits.append({'region':r['id'],**fit})
    if not fits:root.remove(defs)
    return fits

def residual_regions(source,rendered,mask,limit,line_pass=False):
    if limit<=0 or mask.sum()<8:return np.zeros(mask.shape,np.uint16),[],{}
    rgb=source[:,:,:3].astype(float);prediction=rendered[:,:,:3].astype(float)
    s=spatial_scale(source.shape);opaque=source[:,:,3]>250;mask=mask&opaque
    positions=np.flatnonzero(mask)
    if len(positions)<8:return np.zeros(mask.shape,np.uint16),[],{}
    values=rgb.reshape(-1,3)[positions];sample=values[np.random.default_rng(42).choice(len(values),min(50000,len(values)),replace=False)]
    ncolors=min(16 if line_pass else 24,len(np.unique(sample,axis=0)))
    model=MiniBatchKMeans(n_clusters=ncolors,random_state=42,n_init=3,batch_size=4096,reassignment_ratio=0).fit(sample.astype(np.float32))
    q=np.zeros(mask.size,np.uint8)
    for start in range(0,len(positions),250000):q[positions[start:start+250000]]=model.predict(values[start:start+250000].astype(np.float32))+1
    comp=label(q.reshape(mask.shape),background=0,connectivity=2).astype(np.int32)
    n=int(comp.max())+1;areas=np.bincount(comp.ravel(),minlength=n);candidates=[]
    errors=np.mean((rgb-prediction)**2,axis=2)
    slices=ndi.find_objects(comp)
    for ident,box in enumerate(slices,1):
        if box is None or areas[ident]<max(5,5*s*s):continue
        sy,sx=box;local=comp[box]==ident;target=rgb[box][local]
        color=np.median(target,axis=0)
        before=float(errors[box][local].sum());after=float(np.sum(np.mean((target-color)**2,axis=1)))
        if before-after<max(40,areas[ident]*8) or after>.85*before:continue
        padded=np.pad(local.astype(np.uint8),1)
        distance=cv2.distanceTransform(padded,cv2.DIST_L2,3)[1:-1,1:-1]
        width=max(1,float(distance[local].mean())*2);length=areas[ident]/width
        elongation=length/width
        if line_pass:
            if length<8*s or elongation<3:continue
        else:
            # Tiny edgeless residuals/AA fragments are not reintroduced as beads.
            if distance.max()<1.35*s and (elongation<6 or length<14*s):continue
            if areas[ident]<16*s*s:continue
        candidates.append((before-after,ident,np.round(color).astype(np.uint8),box))
    chosen=sorted(candidates,key=lambda item:-item[0])[:limit]
    lookup=np.zeros(n,np.uint16);records=[]
    for new,(gain,old,color,box) in enumerate(chosen,1):
        lookup[old]=new;sy,sx=box
        records.append({'id':new,'area':int(areas[old]),'bbox':[sx.start,sy.start,sx.stop,sy.stop],
                        'color':[int(c) for c in color]+[255],'feature_id':0})
    return lookup[comp],records,{'considered':len(candidates),'selected':len(records)}

def run_method(source_path,work,method,record):
    use_area_cost();cv2.setNumThreads(4);work=Path(work);work.mkdir(parents=True,exist_ok=True)
    source=np.asarray(Image.open(source_path).convert('RGBA')).copy();filtered=clean_texture(source)
    stage={};params={**DEFAULTS,'engine':'potrace','curve_simplify':True,'potrace_palette_colors':100,'potrace_smoothing':0,
       'potrace_min_region_area':8,'potrace_preserve_structure':False,'potrace_stroke_width':1.,
       'potrace_turn_policy':'black','detail_region':'','path_limit':2000}
    if method=='edge_clean':base=filtered;budget=2000
    else:
        record('extract_lines');ridges=ridge_mask(filtered)
        # Preserve source lines in the base: a finite stroke budget cannot
        # guarantee that every detected ridge will be reconstructed later.
        # The rendered residual, rather than destructive removal, selects additions.
        base=filtered.copy()
        budget=PROTOCOL['base_regions'];params['potrace_palette_colors']=PROTOCOL['base_palette']
    base_path=work/'base-input.png';Image.fromarray(base).save(base_path)
    record('base_regions');labels,records=prepare_regions(base_path,budget,'',record,params={**params,'path_limit':budget})
    labels,records,removed=remove_edge_mixtures(labels,records,spatial_scale(source.shape));stage['edge_mixtures_absorbed']=len(removed)
    labels,records,joined=join_thin_neighbors(labels,records,spatial_scale(source.shape));stage['thin_regions_joined']=joined
    # Node tracing paints larger stroked fills first. Preserve that same order
    # when associating path geometry with region colors/gradient samples.
    records.sort(key=lambda r:(-r['area'],r['id']))
    # Stroke-free tiny regions avoid turning single-pixel masks into enlarged discs.
    root=trace(labels,records,work/'base-trace',{**params,'path_limit':2000},record)
    paths=list(root.iter(NS+'path'))
    if len(paths)!=len(records):raise ValueError('Missing traced regions')
    for path,r in zip(paths,records):
        if r['area']<24*spatial_scale(source.shape)**2:path.set('stroke','none')
    stage['base_regions']=len(records)
    if method=='gradient_layers':
        record('fit_gradients');fits=add_gradients(root,labels,records,base);stage['gradients']=len(fits)
        (work/'gradient-fits.json').write_text(json.dumps(fits),encoding='utf-8')
    if method!='edge_clean':
        record('render_base');current=render(root,work/'base-render.png')
        line_guard=np.zeros(labels.shape,bool);line_group=None
        for pass_index in range(2):
            record('residual_layer',current=pass_index,total=2)
            count=sum(1 for _ in root.iter(NS+'path'));available=2000-count
            error=np.mean(np.abs(filtered[:,:,:3].astype(float)-current[:,:,:3]),axis=2)
            if pass_index==0:
                mask=ridges;limit=min(available,PROTOCOL['line_pass_limit'])
                line_group,line_guard,details=centerline_paths(filtered,current,mask,limit)
                if len(line_group):
                    before=current;root.append(line_group);current=render(root,work/f'layer-{pass_index}-render.png')
                    mse_before=float(np.mean((filtered[:,:,:3][line_guard].astype(float)-before[:,:,:3][line_guard])**2))
                    mse_after=float(np.mean((filtered[:,:,:3][line_guard].astype(float)-current[:,:,:3][line_guard])**2))
                    details.update({'rendered_band_mse_before':mse_before,'rendered_band_mse_after':mse_after})
                    if mse_after>mse_before:
                        root.remove(line_group);line_group=None;current=before;line_guard[:]=False;details['rejected_after_render']=True
                stage[f'layer_{pass_index}']=details
                continue
            else:
                # Hysteresis keeps a connected residual instead of thresholding it into tiny pieces.
                mask=ndi.binary_propagation((error>16)&~line_guard,mask=(error>7)&(source[:,:,3]>250)&~line_guard);limit=available
            overlay,items,details=residual_regions(filtered,current,mask,limit,line_pass=pass_index==0)
            if items:
                layer=trace(overlay,items,work/f'layer-{pass_index}',{**params,'path_limit':max(1,len(items)),'potrace_stroke_width':0},record)
                insertion=list(root).index(line_group) if line_group is not None and line_group in list(root) else len(root)
                for offset,element in enumerate(list(layer)):root.insert(insertion+offset,element)
                current=render(root,work/f'layer-{pass_index}-render.png')
            stage[f'layer_{pass_index}']=details
    ET.ElementTree(root).write(work/'output.svg',encoding='utf-8',xml_declaration=True)
    counts=svg_counts(work/'output.svg')
    counts['drawing_paths']=sum(1 for _ in root.iter(NS+'path'))
    counts['stroke_paths']=sum(p.get('fill')=='none' for p in root.iter(NS+'path'))
    assert counts['drawing_paths']<=2000 and counts['embedded_images']==0
    (work/'method-report.json').write_text(json.dumps({'method':method,'protocol':PROTOCOL,'params':params,'stages':stage,'counts':counts},indent=2),encoding='utf-8')
    return {'counts':counts,'stages':stage}
