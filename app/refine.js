'use strict';

// Selection points always use the displayed SVG's image coordinates, never
// screenshot pixels. Zoom/pan changes only the overlay projection.
const refineEditor = (() => {
  const el=id=>document.getElementById(id);
  let hooks, result=null, polygon=[], draft=null, drawing=false, pointer=null;
  let candidate=null, candidateURL=null, preview='current', generation=0, previewGeneration=0, operation=0, previewPending=false;
  const message=text=>{el('refine-status').textContent=text;};
  const current=epoch=>epoch===generation;

  async function post(endpoint,body){
    const response=await fetch(endpoint,{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'局部精修未完成。');
    return data;
  }
  async function discardRemote(item,base){
    if(item&&base)await post('/api/refine-discard',{candidate_id:item.candidate_id,result_id:base}).catch(()=>{});
  }
  function clearCandidate(){
    ++previewGeneration;
    if(candidateURL)URL.revokeObjectURL(candidateURL);
    candidate=null;candidateURL=null;preview='current';
  }
  function reset(){
    ++generation;
    discardRemote(candidate,result?.result_id);
    result=null;polygon=[];draft=null;drawing=false;pointer=null;previewPending=false;
    clearCandidate();render();
  }
  function setResult(next,{preserveSelection=false,pendingPreview=false}={}){
    ++generation;clearCandidate();result=next?.result_id?next:null;
    previewPending=pendingPreview;
    if(!preserveSelection)polygon=[];
    draft=null;drawing=false;pointer=null;
    message(polygon.length?'可调整参数继续精修同一区域，或重新圈画。':'先放大需要修改的位置，再点击“圈画区域”。');
    render();
  }
  function render(){
    if(!hooks)return;
    el('refine-panel').hidden=!result;
    const overlay=el('refine-overlay'),v=view,points=draft||polygon;
    overlay.setAttribute('viewBox',`0 0 ${viewport.clientWidth||1} ${viewport.clientHeight||1}`);
    el('refine-outline').setAttribute('d',points.length?points.map((p,i)=>`${i?'L':'M'}${p[0]*v.scale+v.x} ${p[1]*v.scale+v.y}`).join(' ')+(draft?'':' Z'):'');
    overlay.toggleAttribute('hidden',!result||previewPending||(!drawing&&!points.length));
    overlay.classList.toggle('is-drawing',drawing);
    viewport.classList.toggle('refine-drawing',drawing);
    el('refine-draw').textContent=drawing?'取消圈画':polygon.length?'重新圈画':'圈画区域';
    el('refine-draw').setAttribute('aria-pressed',String(drawing));
    el('refine-draw').disabled=busy||previewPending||!!candidate;
    el('refine-clear').disabled=busy||previewPending||drawing||!polygon.length||!!candidate;
    el('refine-generate').disabled=busy||previewPending||drawing||polygon.length<3;
    for(const id of ['refine-budget','refine-detail'])el(id).disabled=busy||previewPending||drawing;
    el('refine-retry-preview').hidden=!previewPending;el('refine-retry-preview').disabled=busy;
    el('refine-candidate-actions').hidden=!candidate;
    for(const id of ['refine-current','refine-candidate','refine-accept','refine-discard'])el(id).disabled=busy||!candidate;
    el('refine-current').setAttribute('aria-pressed',String(preview==='current'));
    el('refine-candidate').setAttribute('aria-pressed',String(preview==='candidate'));
    el('refine-undo').disabled=busy||previewPending||drawing||!!candidate||!result?.undo_available;
    el('refine-candidate-badge').hidden=preview!=='candidate';
    for(const id of ['zoom-in','zoom-out','fit','actual'])el(id).disabled=drawing||!view.width;
    el('split').tabIndex=view.ready&&!drawing?0:-1;
    el('split').setAttribute('aria-disabled',String(!view.ready||drawing));
  }
  function point(event,clipped=true){
    const r=viewport.getBoundingClientRect();
    const x=(event.clientX-r.left-view.x)/view.scale,y=(event.clientY-r.top-view.y)/view.scale;
    if(!clipped&&(x<0||x>view.width||y<0||y>view.height))return null;
    return [Math.round(Math.max(0,Math.min(view.width,x))*1000)/1000,Math.round(Math.max(0,Math.min(view.height,y))*1000)/1000];
  }
  function finishDrawing(cancelled){
    if(!draft)return;
    const points=draft;draft=null;pointer=null;
    if(!cancelled){
      const step=Math.max(1,Math.ceil(points.length/256));
      const sampled=points.filter((_,index)=>index%step===0);
      let area=0;for(let i=0;i<sampled.length;i++){const a=sampled[i],b=sampled[(i+1)%sampled.length];area+=a[0]*b[1]-b[0]*a[1];}
      if(sampled.length>=3&&Math.abs(area)>=8){polygon=sampled;drawing=false;message('圈选已闭合。可退出圈画后缩放、拖动，再生成候选；圈外保持原结果。');}
      else message('圈选范围太小，请按住鼠标拖出一圈，再松开。');
    }
    render();
  }
  async function showPreview(which){
    if(busy||!result||(which==='candidate'&&!candidateURL))return;
    const epoch=generation,revision=++previewGeneration,url=which==='candidate'?candidateURL:vectorURL;
    try{
      if(await hooks.showVector(url,which==='candidate'?'候选 · 未采用':'矢量',()=>current(epoch)&&revision===previewGeneration)){
        preview=which;render();
      }
    }catch(error){if(current(epoch)&&revision===previewGeneration)showError(error);}
  }
  async function generate(){
    if(busy||previewPending||!result||drawing||polygon.length<3)return;
    const budget=Number(el('refine-budget').value),detail=el('refine-detail').value;
    if(!Number.isInteger(budget)||budget<50||budget>1500){showError(new Error('局部路径预算必须是 50–1500 的整数。'));return;}
    const epoch=generation,base=result.result_id,task=++operation;
    let staged=null,stagedURL=null;
    clearError();hooks.beginTask(true);message('正在生成局部候选，当前结果尚未改变…');el('status').textContent='正在生成局部精修候选…';
    try{
      const next=await post('/api/refine',{result_id:base,polygon:polygon.map(p=>[...p]),options:{path_limit:budget,detail}});
      if(next.cancelled){if(current(epoch)){message('已停止生成，当前结果保持不变。');el('status').textContent='已停止局部精修，当前结果保持不变。';}return;}
      if(!current(epoch)){discardRemote(next,base);return;}
      staged=next;
      if(next.original_result_id&&next.original_result_id!==base)throw new Error('候选与当前结果不匹配，请重新生成。');
      const response=await fetch('/api/refine-preview?candidate_id='+encodeURIComponent(next.candidate_id),{headers});
      if(!response.ok)throw new Error('候选已生成，但无法读取预览。请重试。');
      const url=URL.createObjectURL(await response.blob());stagedURL=url;
      if(!current(epoch)){URL.revokeObjectURL(url);discardRemote(next,base);return;}
      const revision=++previewGeneration;
      const displayed=await hooks.showVector(url,'候选 · 未采用',()=>current(epoch)&&revision===previewGeneration);
      if(!displayed){URL.revokeObjectURL(url);discardRemote(next,base);return;}
      discardRemote(candidate,base);clearCandidate();candidate=next;candidateURL=url;stagedURL=null;preview='candidate';
      const count=next.stats?.drawing_paths??next.stats?.paths;
      message(`候选已生成，尚未采用。局部预算 ${budget}${Number.isFinite(count)?`；候选全图绘制路径 ${count}`:''}。切换原结果对比后再决定。`);
      el('status').textContent='局部候选已生成，尚未采用；请在预览中对比。';
    }catch(error){if(current(epoch)){
      if(staged){
        // A successful POST replaces the server candidate even if its preview
        // cannot be fetched/decoded. The previous candidate is now invalid.
        await discardRemote(staged,base);if(!current(epoch))return;
        clearCandidate();
        try{await hooks.showVector(vectorURL,'矢量',()=>current(epoch));}
        catch{if(current(epoch)){previewPending=true;hooks.invalidatePreview(result);}}
        if(!current(epoch))return;
        message('候选预览加载失败，未显示的候选已放弃；请重新生成。当前已保存结果保持不变。');
      }else message('生成未完成，当前结果及已有候选保持不变；可重试。');
      showError(error);el('status').textContent=staged?'候选预览加载失败，请重新生成。':'局部精修未完成，请查看错误信息。';
    }}
    finally{if(stagedURL)URL.revokeObjectURL(stagedURL);if(task===operation){hooks.endTask();render();}}
  }
  async function adoptOrUndo(undo=false){
    if(busy||previewPending||!result||(undo?!result.undo_available:!candidate))return;
    let epoch=generation,committed=false;
    const base=result.result_id,task=++operation;
    clearError();hooks.beginTask(false);message(undo?'正在撤销上次采用…':'正在采用并另存局部精修结果…');
    try{
      const next=await post(undo?'/api/refine-undo':'/api/refine-accept',undo?{result_id:base}:{result_id:base,candidate_id:candidate.candidate_id});
      if(!current(epoch))return;
      // The server version has already changed. Retain its new ID/metadata
      // before attempting the fallible image fetch, and invalidate old downloads.
      setResult(next,{preserveSelection:true,pendingPreview:true});epoch=generation;committed=true;
      hooks.invalidatePreview(next);
      if(await hooks.loadResult(next,{preserveView:true,isCurrent:()=>current(epoch)})){
        previewPending=false;
        const text=undo?'已撤销上次采用，恢复此前保存的结果。':'已采用局部精修并保存新 SVG；可以继续圈画其他区域。';
        message(text);el('status').textContent=text;
      }
    }catch(error){if(current(epoch)){showError(error);const text=committed?(undo?'已撤销，但预览加载失败。点击“重试预览”加载当前结果。':'已保存新 SVG，但预览加载失败。点击“重试预览”加载当前结果。'):'操作未完成，请查看错误信息。';message(text);el('status').textContent=text;}}
    finally{if(task===operation){hooks.endTask();render();}}
  }
  async function retryPreview(){
    if(busy||!previewPending||!result)return;
    const epoch=generation,task=++operation;
    clearError();hooks.beginTask(false);message('正在重新加载当前已保存结果…');
    try{
      if(await hooks.loadResult(result,{preserveView:true,isCurrent:()=>current(epoch)})){
        previewPending=false;message('当前结果预览已恢复，可继续局部精修。');el('status').textContent='当前已保存结果预览已恢复。';
      }
    }catch(error){if(current(epoch)){showError(error);message('当前结果已保存，预览仍未加载；可以再次重试。');}}
    finally{if(task===operation){hooks.endTask();render();}}
  }
  async function discard(){
    if(busy||!candidate||!result)return;
    const epoch=generation,base=result.result_id,task=++operation;
    clearError();hooks.beginTask(false);
    try{
      await post('/api/refine-discard',{candidate_id:candidate.candidate_id,result_id:base});
      if(!current(epoch))return;
      await hooks.showVector(vectorURL,'矢量',()=>current(epoch));
      if(!current(epoch))return;
      clearCandidate();message('已放弃候选，当前已保存结果保持不变。');
      el('status').textContent='已放弃局部候选，当前结果保持不变。';
    }catch(error){if(current(epoch))showError(error);}
    finally{if(task===operation){hooks.endTask();render();}}
  }
  function init(callbacks){
    hooks=callbacks;
    el('refine-draw').onclick=()=>{if(busy||candidate)return;drawing=!drawing;draft=null;pointer=null;message(drawing?'按住鼠标或触笔，沿边界圈出简单轮廓；松开后自动闭合。圈画期间暂停缩放和平移。':'已退出圈画，可缩放或拖动画布；已有轮廓保留。');render();};
    el('refine-clear').onclick=()=>{polygon=[];message('圈选已清除，可重新圈画。');render();};
    el('refine-generate').onclick=generate;
    el('refine-retry-preview').onclick=retryPreview;
    el('refine-current').onclick=()=>showPreview('current');el('refine-candidate').onclick=()=>showPreview('candidate');
    el('refine-accept').onclick=()=>adoptOrUndo(false);el('refine-undo').onclick=()=>adoptOrUndo(true);el('refine-discard').onclick=discard;
    const overlay=el('refine-overlay');
    overlay.addEventListener('pointerdown',event=>{if(!drawing||busy||event.button!==0||pointer!==null)return;const p=point(event,false);if(!p)return;event.preventDefault();event.stopPropagation();pointer=event.pointerId;draft=[p];overlay.setPointerCapture(pointer);render();});
    overlay.addEventListener('pointermove',event=>{if(event.pointerId!==pointer||!draft)return;event.preventDefault();event.stopPropagation();const p=point(event),last=draft[draft.length-1];if(Math.hypot(p[0]-last[0],p[1]-last[1])*view.scale>=2)draft.push(p);render();});
    overlay.addEventListener('pointerup',event=>{if(event.pointerId!==pointer)return;event.preventDefault();event.stopPropagation();finishDrawing(false);});
    for(const name of ['pointercancel','lostpointercapture'])overlay.addEventListener(name,event=>{if(event.pointerId===pointer)finishDrawing(true);});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&drawing){drawing=false;draft=null;pointer=null;message('已取消圈画，原有轮廓保留。');render();}});
    render();
  }
  return {init,setResult,reset,render,isDrawing:()=>drawing};
})();
