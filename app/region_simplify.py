"""Continue merging adjacent Potrace regions; never regroup disjoint fills."""
import heapq
import json
from pathlib import Path


def reduce_regions(work, output, target, params, record):
    import numpy as np
    import cv2
    from scipy import ndimage as ndi
    from core import parse_detail_region
    from potrace_engine import trace_regions

    work = Path(work)
    job = json.loads((work / 'potrace.json').read_text(encoding='utf-8'))
    labels = np.fromfile(work / 'regions.bin', dtype='<u2').reshape(job['height'], job['width'])
    n = len(job['regions']) + 1
    area = np.bincount(labels.ravel(), minlength=n).astype('int64')
    mass = area.astype('float64')
    roi = parse_detail_region(params['detail_region'])
    if roi:
        x,y,w,h = roi
        mass += (params['potrace_detail_weight'] - 1) * np.bincount(labels[y:y+h,x:x+w].ravel(), minlength=n)
    colors = np.zeros((n,4), dtype='float64')
    for item in job['regions']: colors[item['id']] = item['color']
    lab = cv2.cvtColor(colors[:,:3].astype('uint8')[None], cv2.COLOR_RGB2LAB)[0].astype('float64')
    sums = np.column_stack((lab, colors[:,3])) * mass[:,None]
    color_sums = colors * mass[:,None]
    pairs = []
    for a,b in ((labels[:,:-1],labels[:,1:]), (labels[:-1,:],labels[1:,:])):
        mask = (a != b) & (a > 0) & (b > 0)
        aa,bb = a[mask].astype('int64'),b[mask].astype('int64')
        pairs.append(np.unique(np.minimum(aa,bb)*n+np.maximum(aa,bb)))
    pairs = np.unique(np.concatenate(pairs))
    neighbors = [set() for _ in range(n)]
    for pair in pairs:
        a,b = divmod(int(pair),n); neighbors[a].add(b); neighbors[b].add(a)
    parent = np.arange(n); active = area > 0; active[0] = False
    version = np.zeros(n, dtype='int64'); heap = []
    from merge_cost import MergeCosts
    feature_ids = [0] + [item.get('feature_id',0) for item in job['regions']]
    costs = MergeCosts(mass, sums, area, scale=params.get('_spatial_scale',1),
                       feature_ids=feature_ids if any(feature_ids) else None)
    def push(a,b):
        if a>b: a,b=b,a
        cost = costs.cost(a,b)
        heapq.heappush(heap,(cost,a,b,int(version[a]),int(version[b])))
    for pair in pairs: push(*divmod(int(pair),n))
    initial = count = int(active.sum())
    record('region_simplify',current=0,total=max(0,initial-target),regions=count,target=target)
    while count>target and heap:
        _,a,b,va,vb = heapq.heappop(heap)
        if not(active[a] and active[b]) or va!=version[a] or vb!=version[b]: continue
        if len(neighbors[a]) < len(neighbors[b]):
            a,b = b,a
        absorbed_neighbors = neighbors[b].copy()
        for c in neighbors[b]:
            neighbors[c].discard(b)
            if c!=a: neighbors[c].add(a)
        neighbors[a].update(neighbors[b]);neighbors[a].discard(a);neighbors[a].discard(b)
        union=neighbors[a];neighbors[b].clear();parent[b]=a;active[b]=False
        area[a]+=area[b];mass[a]+=mass[b];sums[a]+=sums[b];color_sums[a]+=color_sums[b]
        if costs.update(a,b,mass[a],sums[a],area[a]):
            version[a]+=1
        else:
            union = absorbed_neighbors - {a,b}
        version[b]+=1;count-=1
        for c in union: push(a,c)
        if count==target or count%100==0:
            if len(heap)>max(10000,count*12):
                heap[:]=[e for e in heap if active[e[1]] and active[e[2]] and version[e[1]]==e[3] and version[e[2]]==e[4]]
                heapq.heapify(heap)
            record('region_simplify',current=initial-count,total=initial-target,regions=count,target=target)
    if count>target:
        raise ValueError(f'透明背景隔开的区域无法继续合并：至少需要 {count} 个色块，目标为 {target}。请提高目标色块数量。')
    roots=parent.copy()
    while np.any(roots!=roots[roots]): roots=roots[roots]
    ids=np.flatnonzero(active);lut=np.zeros(n,dtype='uint16');lut[ids]=np.arange(1,len(ids)+1)
    reduced=lut[roots[labels]];records=[]
    for i,(root,sl) in enumerate(zip(ids,ndi.find_objects(reduced)),1):
        sy,sx=sl
        records.append({'id':i,'area':int(area[root]),'feature_id':costs.feature_id(root),'bbox':[sx.start,sy.start,sx.stop,sy.stop],
                        'color':np.round(color_sums[root]/mass[root]).clip(0,255).astype('uint8').tolist()})
    trace_regions(reduced,records,output,{**params,'path_limit':target},record)
    return {'initial_regions':initial,'merged_regions':count,'target':target}
