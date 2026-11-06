"""Canonical SVG counts and corner-protected adjacent Bezier simplification.

Counts are geometric, not XML-token counts: a nonzero Z closure is a line;
a zero-length repeated closure is not a new segment or node. No contours or
filled paths are dropped. Error bounds are sampled geometry bounds, not an
analytic Hausdorff guarantee.
"""
from pathlib import Path
from dataclasses import dataclass
import heapq,re,math,itertools,xml.etree.ElementTree as ET
import numpy as np

TOKEN=re.compile(r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?')
NS='{http://www.w3.org/2000/svg}'

@dataclass
class Contour:
    segments:list
    closed:bool=True

def parse_d(d):
    tokens=TOKEN.findall(d);i=0;cmd=None;cur=np.zeros(2);start=None;segments=[];contours=[];previous=None
    def finish(closed):
        nonlocal segments,start
        if start is not None and segments:contours.append(Contour(segments,closed))
        segments=[];start=None
    while i<len(tokens):
        if tokens[i].isalpha():cmd=tokens[i];i+=1
        if cmd is None:raise ValueError('Missing SVG command')
        relative=cmd.islower();c=cmd.upper()
        if c=='Z':
            if start is not None and np.linalg.norm(cur-start)>1e-8:segments.append(np.array([cur.copy(),start.copy()]))
            if start is not None:cur=start.copy()
            finish(True);previous=None;cmd=None;continue
        size={'M':2,'L':2,'H':1,'V':1,'Q':4,'C':6,'S':4,'T':2}.get(c)
        if size is None:raise ValueError('Unsupported SVG command '+cmd)
        vals=np.array(list(map(float,tokens[i:i+size])));i+=size
        if c=='M':
            finish(False);cur=vals+cur if relative else vals;start=cur.copy();cmd='l' if relative else 'L';previous=None;continue
        if start is None:start=cur.copy()
        if c=='H':end=np.array([vals[0]+cur[0] if relative else vals[0],cur[1]]);p=np.array([cur,end])
        elif c=='V':end=np.array([cur[0],vals[0]+cur[1] if relative else vals[0]]);p=np.array([cur,end])
        else:
            pts=vals.reshape(-1,2)+(cur if relative else 0)
            if c=='S':pts=np.vstack([2*cur-previous[-2] if previous is not None and len(previous)==4 else cur,pts])
            elif c=='T':pts=np.vstack([2*cur-previous[-2] if previous is not None and len(previous)==3 else cur,pts])
            p=np.vstack([cur,pts]);end=pts[-1]
        if np.max(np.abs(p-p[0]))>1e-9:segments.append(p.copy())
        cur=end.copy();previous=p
    finish(False)
    # Filled SVG paths implicitly close even when the explicit Z was omitted.
    return contours

def svg_counts(file):
    root=ET.parse(file).getroot();counts=dict(fill_paths=0,contours=0,total_segments=0,curve_segments=0,anchors=0,handles=0,nodes=0,embedded_images=0)
    for el in root.iter():
        tag=el.tag.rsplit('}',1)[-1]
        if tag=='image':counts['embedded_images']+=1
        if tag!='path' or el.get('fill')=='none':continue
        counts['fill_paths']+=1
        for contour in parse_d(el.get('d','')):
            segs=list(contour.segments)
            if not segs:continue
            # All candidates are filled, so SVG implicitly closes open subpaths.
            if np.linalg.norm(segs[-1][-1]-segs[0][0])>1e-8:segs.append(np.array([segs[-1][-1],segs[0][0]]))
            counts['contours']+=1;counts['total_segments']+=len(segs);counts['anchors']+=len(segs)
            counts['curve_segments']+=sum(len(s)>2 for s in segs)
            counts['handles']+=sum(len(s)-2 for s in segs)
    counts['nodes']=counts['anchors']+counts['handles']
    return counts

def evaluate(p,t):
    t=np.asarray(t)[:,None];u=1-t
    if len(p)==2:return u*p[0]+t*p[1]
    if len(p)==3:return u*u*p[0]+2*u*t*p[1]+t*t*p[2]
    return u**3*p[0]+3*u*u*t*p[1]+3*u*t*t*p[2]+t**3*p[3]

def tangent(p,at_end=False):
    diffs=(p[-1]-p[-2::-1]) if at_end else (p[1:]-p[0])
    for d in diffs:
        norm=np.linalg.norm(d)
        if norm>1e-9:return d/norm
    return np.zeros(2)

def angle(a,b):
    if np.linalg.norm(a)<1e-9 or np.linalg.norm(b)<1e-9:return 180.0
    return math.degrees(math.acos(float(np.clip(a@b,-1,1))))

def degree_reduce(p,tol):
    if len(p)<=2 or tol<=0:return p
    t=np.linspace(0,1,13);original=evaluate(p,t)
    candidates=[np.array([p[0],p[-1]])]
    if len(p)==4:candidates.append(np.array([p[0],.75*(p[1]+p[2])-.25*(p[0]+p[-1]),p[-1]]))
    for q in candidates:
        if angle(tangent(p),tangent(q))>12 or angle(tangent(p,True),tangent(q,True))>12:continue
        if np.max(np.linalg.norm(evaluate(q,t)-original,axis=1))<=tol:return q
    return p

@dataclass
class Span:
    p:np.ndarray
    samples:np.ndarray
    source_count:int=1
    start_tangent:np.ndarray=None
    end_tangent:np.ndarray=None
    error:float=0.0
    def __post_init__(self):
        if self.start_tangent is None:self.start_tangent=tangent(self.p)
        if self.end_tangent is None:self.end_tangent=tangent(self.p,True)

def fit_pair(a,b,corner_degrees=35):
    # A corner/tip remains an explicit anchor, regardless of the tolerance gene.
    if angle(a.end_tangent,b.start_tangent)>corner_degrees:return None
    if a.source_count+b.source_count>64:return None
    pts=np.vstack([a.samples,b.samples[1:]])
    lengths=np.linalg.norm(np.diff(pts,axis=0),axis=1);length=float(lengths.sum())
    chord=np.linalg.norm(pts[-1]-pts[0])
    if length<1e-8 or chord<1e-5:return None
    t=np.r_[0,np.cumsum(lengths)]/length;u=1-t
    b0=u**3;b1=3*u*u*t;b2=3*u*t*t;b3=t**3
    d0=a.start_tangent;d1=b.end_tangent
    residual=pts-(b0+b1)[:,None]*pts[0]-(b2+b3)[:,None]*pts[-1]
    A=b1[:,None]*d0;B=-b2[:,None]*d1
    aa=float((A*A).sum());ab=float((A*B).sum());bb=float((B*B).sum())
    ar=float((A*residual).sum());br=float((B*residual).sum());det=aa*bb-ab*ab
    if det<1e-12:return None
    alpha=(ar*bb-br*ab)/det;beta=(br*aa-ar*ab)/det
    if min(alpha,beta)<0 or max(alpha,beta)>4*length:return None
    p=np.array([pts[0],pts[0]+alpha*d0,pts[-1]-beta*d1,pts[-1]])
    error=float(np.max(np.linalg.norm(evaluate(p,t)-pts,axis=1)))
    return error,Span(p,pts,a.source_count+b.source_count,d0,d1,error)

def simplify_contour_levels(contour,levels):
    segs=contour.segments
    if not segs:return [[] for _ in levels]
    # Rotate a closed contour to the strongest turn. This protects the wrap tip
    # as well as every other strong turn, and avoids arbitrary closure artifacts.
    if contour.closed:
        turn=[angle(tangent(segs[i-1],True),tangent(segs[i])) for i in range(len(segs))]
        anchor=int(np.argmax(turn));segs=segs[anchor:]+segs[:anchor]
    sampled=np.vstack([evaluate(p,np.linspace(0,1,9))[:-1] for p in segs])
    signed_area=.5*float(np.sum(sampled[:,0]*np.roll(sampled[:,1],-1)-sampled[:,1]*np.roll(sampled[:,0],-1)))
    local_cap=max(.02,.1*math.sqrt(abs(signed_area)))
    n=len(segs);nodes=[Span(p,evaluate(p,np.linspace(0,1,9))) for p in segs]
    nxt=list(range(1,n))+[-1];prev=[-1]+list(range(n-1));active=[True]*n;version=[0]*n;heap=[];count=n;serial=itertools.count()
    def push(i):
        j=nxt[i]
        if j<0:return
        fit=fit_pair(nodes[i],nodes[j])
        if fit is not None:heapq.heappush(heap,(fit[0],next(serial),i,j,version[i],version[j],fit[1]))
    for i in range(n-1):push(i)
    output=[]
    for tol in levels:
        if tol==0:output.append([p.copy() for p in segs]);continue
        effective_tol=min(tol,local_cap)
        while heap and heap[0][0]<=effective_tol and count>3:
            error,_,i,j,vi,vj,span=heapq.heappop(heap)
            if not(active[i] and active[j]) or vi!=version[i] or vj!=version[j] or nxt[i]!=j:continue
            nodes[i]=span;active[j]=False;nxt[i]=nxt[j]
            if nxt[j]>=0:prev[nxt[j]]=i
            version[i]+=1;version[j]+=1;count-=1
            if prev[i]>=0:push(prev[i])
            push(i)
        ordered=[nodes[i] for i in range(n) if active[i]];candidate=[]
        for i,span in enumerate(ordered):
            protected=angle(ordered[i-1].end_tangent,span.start_tangent)>35 or angle(span.end_tangent,ordered[(i+1)%len(ordered)].start_tangent)>35
            candidate.append(span.p if protected else degree_reduce(span.p,max(0,effective_tol-span.error)))
        poly=np.vstack([evaluate(p,np.linspace(0,1,9))[:-1] for p in candidate])
        candidate_area=.5*float(np.sum(poly[:,0]*np.roll(poly[:,1],-1)-poly[:,1]*np.roll(poly[:,0],-1)))
        if signed_area*candidate_area<=0 and abs(signed_area)>1e-8:candidate=[p.copy() for p in segs]
        output.append(candidate)
    return output

def _number(value):
    value=str(value).strip()
    if value.endswith('px'):value=value[:-2]
    try:result=float(value)
    except ValueError:raise ValueError('SVG 尺寸或描边宽度必须是像素数值。') from None
    if not math.isfinite(result):raise ValueError('SVG 包含无效数值。')
    return result


def _transform(value):
    matrix=np.eye(3)
    if not value:return matrix
    consumed=[]
    for match in re.finditer(r'([A-Za-z]+)\s*\(([^)]*)\)',value):
        name=match.group(1);v=[float(x) for x in re.split(r'[\s,]+',match.group(2).strip()) if x]
        if not all(math.isfinite(x) for x in v):raise ValueError('SVG 变换包含无效数值。')
        m=np.eye(3)
        if name=='matrix' and len(v)==6:m=np.array([[v[0],v[2],v[4]],[v[1],v[3],v[5]],[0,0,1.]])
        elif name=='translate' and len(v) in (1,2):m[:2,2]=[v[0],v[1] if len(v)>1 else 0]
        elif name=='scale' and len(v) in (1,2):m[0,0]=v[0];m[1,1]=v[-1]
        elif name=='rotate' and len(v) in (1,3):
            a=math.radians(v[0]);m[:2,:2]=[[math.cos(a),-math.sin(a)],[math.sin(a),math.cos(a)]]
            if len(v)==3:m[:2,2]=np.array(v[1:])-m[:2,:2]@np.array(v[1:])
        elif name in ('skewX','skewY') and len(v)==1:m[0 if name=='skewX' else 1,1 if name=='skewX' else 0]=math.tan(math.radians(v[0]))
        else:raise ValueError('不支持的 SVG 变换：'+name)
        matrix=matrix@m;consumed.append((match.start(),match.end()))
    leftover=value
    for a,b in reversed(consumed):leftover=leftover[:a]+leftover[b:]
    if leftover.strip(' ,\t\r\n'):raise ValueError('无法解析 SVG 变换。')
    return matrix


def _serialize(contours):
    out=[];fmt=lambda p:' '.join(f'{float(v):.6f}' for v in p)
    for c in contours:
        if not c.segments:continue
        out.append('M '+fmt(c.segments[0][0]))
        for s in c.segments:out.append({2:'L ',3:'Q ',4:'C '}[len(s)]+' '.join(fmt(q) for q in s[1:]))
        if c.closed:out.append('Z')
    return ' '.join(out)


def normalize_svg(input_path,output_path,width,height):
    """Flatten engine-generated transforms without flattening paint opacity.

    A one-path opacity group remains a group so fill/stroke overlap is composited
    once. Unsupported paint servers, clipping, and overlapping multi-path opacity
    groups are rejected rather than silently changing artwork.
    """
    width=float(width);height=float(height)
    if min(width,height)<=0 or not all(math.isfinite(v) for v in (width,height)):raise ValueError('SVG 输出尺寸无效。')
    source=ET.parse(input_path).getroot()
    if source.tag.rsplit('}',1)[-1]!='svg':raise ValueError('输入不是 SVG。')
    vb=[float(x) for x in re.split(r'[\s,]+',source.get('viewBox','').strip()) if x]
    if not vb:vb=[0,0,_number(source.get('width',width)),_number(source.get('height',height))]
    if len(vb)!=4 or min(vb[2:])<=0:raise ValueError('SVG viewBox 无效。')
    base=np.array([[width/vb[2],0,-vb[0]*width/vb[2]],[0,height/vb[3],-vb[1]*height/vb[3]],[0,0,1.]])
    out=ET.Element(NS+'svg',{'width':f'{width:g}','height':f'{height:g}','viewBox':f'0 0 {width:g} {height:g}'})
    inherited={'fill':'black','stroke':'none','fill-rule':'nonzero','fill-opacity':'1','stroke-opacity':'1','stroke-width':'1','stroke-linecap':'butt','stroke-linejoin':'miter','stroke-miterlimit':'4'}
    paint=set(inherited)
    forbidden={'filter','clip-path','mask','marker-start','marker-end','marker-mid','vector-effect','stroke-dasharray','stroke-dashoffset','paint-order','mix-blend-mode'}
    def visit(node,parent_matrix,properties,parent_opacity):
        tag=node.tag.rsplit('}',1)[-1]
        if tag in ('title','desc','metadata'):return
        if tag=='defs' and not len(node):return
        if tag not in ('svg','g','path'):raise ValueError('增强处理不支持 SVG 元素：'+tag)
        attrs=dict(node.attrib)
        for part in attrs.pop('style','').split(';'):
            if ':' in part:
                key,val=part.split(':',1);attrs[key.strip()]=val.strip()
        if any(k in attrs and attrs[k] not in ('none','') for k in forbidden):raise ValueError('增强处理暂不支持 SVG 裁剪、滤镜或标记。')
        if attrs.get('display')=='none' or attrs.get('visibility') in ('hidden','collapse'):
            raise ValueError('增强处理不接受隐藏的 SVG 图形。')
        props=dict(properties);props.update({k:v for k,v in attrs.items() if k in paint})
        for k in ('fill','stroke'):
            if props[k].startswith('url('):raise ValueError('增强处理暂不支持渐变或图案填充。')
        opacity=parent_opacity*_number(attrs.get('opacity','1'))
        if not 0<=opacity<=1:raise ValueError('SVG 透明度超出范围。')
        if tag in ('svg','g') and _number(attrs.get('opacity','1'))<1:
            if sum(1 for e in node.iter() if e.tag.rsplit('}',1)[-1]=='path')>1:
                raise ValueError('增强处理暂不支持包含多条路径的半透明组合；请先合并其透明度层级。')
        matrix=parent_matrix@_transform(attrs.get('transform'))
        if tag=='path':
            contours=parse_d(attrs.get('d',''))
            for c in contours:
                for i,s in enumerate(c.segments):c.segments[i]=s@matrix[:2,:2].T+matrix[:2,2]
            if props['stroke']!='none':
                gram=matrix[:2,:2].T@matrix[:2,:2];scale=math.sqrt(max(0,float(np.trace(gram)/2)))
                if not np.allclose(gram,np.eye(2)*scale*scale,rtol=1e-6,atol=1e-8):raise ValueError('带描边路径不支持非等比/倾斜变换。')
                props['stroke-width']=f'{_number(props["stroke-width"])*scale:.8g}'
            group=ET.SubElement(out,NS+'g',{'opacity':f'{opacity:.8g}'})
            if 'id' in attrs:group.set('id',attrs['id'])
            ET.SubElement(group,NS+'path',{'d':_serialize(contours),**props})
        else:
            for child in node:visit(child,matrix,props,opacity)
    visit(source,base,inherited,1.)
    ET.register_namespace('','http://www.w3.org/2000/svg');ET.ElementTree(out).write(output_path,encoding='utf-8',xml_declaration=True)
    return {'width':width,'height':height,**svg_counts(output_path)}


def simplify_svg(input_path,output_path,tolerance=.3,record=None):
    tolerance=float(tolerance)
    if not math.isfinite(tolerance) or tolerance<0:raise ValueError('曲线简化容差必须为非负有限数值。')
    record=record or (lambda *a,**k:None)
    root=ET.parse(input_path).getroot();before=svg_counts(input_path)
    paths=list(root.iter(NS+'path'));total=len(paths)
    for i,p in enumerate(paths,1):
        contours=parse_d(p.get('d',''))
        if p.get('fill','black')!='none' and tolerance>0:
            changed=[]
            for c in contours:
                original_closed=c.closed
                coincident=np.linalg.norm(c.segments[-1][-1]-c.segments[0][0])<1e-8
                if not c.closed and p.get('stroke','none')!='none' and not coincident:changed.append(c);continue
                if not c.closed:
                    if np.linalg.norm(c.segments[-1][-1]-c.segments[0][0])>1e-8:c.segments.append(np.array([c.segments[-1][-1],c.segments[0][0]]))
                    c.closed=True
                # Keep a coincident open stroke open: adding Z changes the cap
                # into a join, while removing its repeated endpoint breaks fill.
                output_closed=original_closed or p.get('stroke','none')=='none'
                c.closed=output_closed
                changed.append(Contour(simplify_contour_levels(c,[0,tolerance])[1],output_closed))
            p.set('d',_serialize(changed))
        if i==1 or i%50==0 or i==total:record('curve_simplify',current=i,total=total)
    ET.register_namespace('','http://www.w3.org/2000/svg');ET.ElementTree(root).write(output_path,encoding='utf-8',xml_declaration=True)
    after=svg_counts(output_path)
    if any(before[k]!=after[k] for k in ('fill_paths','contours')):raise ValueError('曲线简化改变了色块或孔洞数量，已停止。')
    return {'before':before,'after':after,'tolerance':tolerance}

if __name__=='__main__':
    import sys,json
    print(json.dumps(svg_counts(sys.argv[1]),indent=2))
