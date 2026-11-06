'use strict';

const cropEditor = (() => {
  const el = id => document.getElementById(id);
  const presetRatios = ['16:9','9:16','4:3','3:4','1:1'];
  let file = null, source = null, previewURL = null, request = null;
  let failure = '', draft = null, drag = null, locked = false, initialized = false;
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const unavailable = () => locked || (typeof busy !== 'undefined' && busy);

  function terms(value) {
    const match = typeof value === 'string' && /^\s*([0-9]{1,6}(?:\.[0-9]{1,3})?)\s*[:：]\s*([0-9]{1,6}(?:\.[0-9]{1,3})?)\s*$/.exec(value);
    if (!match || !Number(match[1]) || !Number(match[2])) {
      throw new Error('请输入正数宽高比，例如 5:4 或 2.35:1，最多六位整数和三位小数。');
    }
    const width = Math.round(Number(match[1])*1000), height = Math.round(Number(match[2])*1000);
    let a = width, b = height;
    while (b) [a,b] = [b,a%b];
    return [width/a,height/a];
  }

  function validateRect(value) {
    if (typeof value !== 'string') throw new Error('精确裁剪区域必须为空字符串或 x,y,宽,高。');
    if (!value.trim()) return null;
    if (!/^\s*[0-9]+\s*,\s*[0-9]+\s*,\s*[0-9]+\s*,\s*[0-9]+\s*$/.test(value)) {
      throw new Error('精确裁剪区域格式为 x,y,宽,高，使用原图非负整数坐标。');
    }
    const [x,y,w,h] = value.split(',').map(Number);
    if (![x,y,w,h].every(v => Number.isSafeInteger(v) && v >= 0 && v <= 40000000) || !w || !h) {
      throw new Error('精确裁剪区域宽高必须大于 0，坐标不能超出图片范围。');
    }
    return {x,y,w,h};
  }

  function rawConfig() {
    return {crop_ratio:el('opt-crop_ratio').value, crop_x:Number(el('opt-crop_x').value),
      crop_y:Number(el('opt-crop_y').value), crop_rect:el('opt-crop_rect').value};
  }

  function validateConfig(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('裁剪配置必须是对象。');
    const own = (key,fallback) => Object.prototype.hasOwnProperty.call(value,key) ? value[key] : fallback;
    const config = {crop_ratio:own('crop_ratio',''),crop_x:own('crop_x',50),
      crop_y:own('crop_y',50),crop_rect:own('crop_rect','')};
    const rect = validateRect(config.crop_rect);
    if (typeof config.crop_ratio !== 'string') throw new Error('裁剪比例必须为字符串。');
    if (config.crop_ratio) terms(config.crop_ratio);
    for (const value of [config.crop_x,config.crop_y]) {
      if (!Number.isInteger(value) || value < 0 || value > 100) throw new Error('裁剪位置必须在 0–100 之间。');
    }
    if (source && rect && (rect.x+rect.w > source.width || rect.y+rect.h > source.height)) {
      throw new Error(`精确裁剪区域超出 ${source.width} × ${source.height} 原图范围，请重新编辑裁剪。`);
    }
    return config;
  }

  function getConfig() { return validateConfig(rawConfig()); }

  function fullRect() { return {x:0,y:0,w:source.width,h:source.height}; }

  function committedRect() {
    const config = getConfig(), exact = validateRect(config.crop_rect);
    if (exact) return exact;
    if (!config.crop_ratio) return fullRect();
    const [a,b] = terms(config.crop_ratio);
    const units = Math.min(Math.floor(source.width/a),Math.floor(source.height/b));
    if (!units) throw new Error('此比例无法在这张图片中裁出整数像素，请更换比例。');
    const w = units*a, h = units*b;
    return {x:Math.round((source.width-w)*config.crop_x/100),
      y:Math.round((source.height-h)*config.crop_y/100),w,h};
  }

  function makeDraft() {
    const config = rawConfig();
    try {
      const rect = committedRect();
      let ratio = config.crop_ratio;
      if (ratio) {
        const [a,b] = terms(ratio);
        // An imported exact rectangle is authoritative, even if a stale ratio
        // field describes a different shape. Show that rectangle as free crop.
        if (rect.w*b !== rect.h*a) ratio = '';
      }
      return {rect,ratio,error:''};
    } catch (error) {
      return {rect:fullRect(),ratio:'',error:error.message};
    }
  }

  function syncDraftControls() {
    if (!draft) return;
    const mode = !draft.ratio ? 'free' : presetRatios.includes(draft.ratio) ? draft.ratio : 'custom';
    el('crop-preset').value = mode;
    el('custom-ratio-field').hidden = mode !== 'custom';
    if (mode === 'custom') el('crop-custom-ratio').value = draft.ratio;
  }

  function layoutStage() {
    if (!source || !el('crop-dialog').open) return;
    const workspace = el('crop-workspace'), styles = getComputedStyle(workspace);
    const width = workspace.clientWidth-parseFloat(styles.paddingLeft)-parseFloat(styles.paddingRight);
    const height = workspace.clientHeight-parseFloat(styles.paddingTop)-parseFloat(styles.paddingBottom);
    const scale = Math.min(width/source.width,height/source.height);
    if (!(scale > 0)) return;
    Object.assign(el('crop-stage').style,{width:source.width*scale+'px',height:source.height*scale+'px'});
  }

  function renderDraft() {
    const dialog = el('crop-dialog');
    if (!dialog?.open) return;
    if (source && !draft) { draft = makeDraft(); syncDraftControls(); }
    const ready = !!(source && draft);
    el('crop-stage').hidden = !ready;
    el('crop-loading').hidden = ready;
    el('crop-loading').textContent = failure || '正在读取原图…';
    el('crop-error').hidden = !draft?.error;
    el('crop-error').textContent = draft?.error || '';
    for (const id of ['crop-preset','crop-custom-ratio','crop-reset']) el(id).disabled = unavailable() || !ready;
    el('crop-apply').disabled = unavailable() || !ready || !!draft.error;
    if (!ready) { el('crop-size').textContent = ''; return; }
    const {x,y,w,h} = draft.rect;
    Object.assign(el('crop-frame').style,{left:x/source.width*100+'%',top:y/source.height*100+'%',
      width:w/source.width*100+'%',height:h/source.height*100+'%'});
    el('crop-size').textContent = `${w} × ${h} px · 左上角 ${x}, ${y}` + (draft.ratio ? ` · 锁定 ${draft.ratio}` : ' · 自由比例');
    layoutStage();
  }

  function render() {
    if (!initialized) return;
    let ready = true, text = '完整原图', detail = '保留原始画布，或打开裁剪调整构图';
    try {
      const config = getConfig();
      if (source) {
        const rect = committedRect();
        const full = rect.x===0 && rect.y===0 && rect.w===source.width && rect.h===source.height;
        text = full ? '完整原图' : `${rect.w} × ${rect.h} px`;
        detail = full ? `${source.width} × ${source.height} px · 可调整构图`
          : `${config.crop_ratio || '自由比例'} · 左上角 ${rect.x}, ${rect.y}`;
      } else if (config.crop_rect) {
        text = '已设置精确裁剪'; detail = '选图后核对裁剪范围';
      } else if (config.crop_ratio) {
        text = `固定 ${config.crop_ratio}`; detail = '选图后可调整选框大小与位置';
      }
    } catch (error) { ready = false; text = '请调整裁剪设置'; detail = error.message; }
    el('crop-summary').textContent = text;
    el('crop-summary-detail').textContent = detail;
    el('crop-open').disabled = !file || unavailable();
    el('crop-settings').disabled = unavailable();
    if (el('convert')) el('convert').disabled = !file || unavailable() || !ready;
    renderDraft();
  }

  async function loadPreview() {
    if (!file || request) return;
    const controller = new AbortController(), selectedFile = file;
    request = controller; failure = '';
    let createdURL = null;
    render();
    try {
      const response = await fetch('/api/crop-preview',{method:'POST',headers,body:selectedFile,signal:controller.signal});
      if (!response.ok) throw new Error((await response.json()).error || '无法读取裁剪预览。');
      const blob = await response.blob();
      if (request !== controller || file !== selectedFile) return;
      const width = Number(response.headers.get('X-Source-Width')), height = Number(response.headers.get('X-Source-Height'));
      if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || Math.min(width,height)<=0) throw new Error('裁剪预览缺少原图尺寸。');
      createdURL = URL.createObjectURL(blob);
      el('crop-source').src = createdURL;
      await el('crop-source').decode();
      if (request !== controller || file !== selectedFile) return;
      if (previewURL) URL.revokeObjectURL(previewURL);
      previewURL = createdURL; source = {width,height};
    } catch (error) {
      if (request === controller && error.name !== 'AbortError') failure = error.message || '无法读取裁剪预览。';
    } finally {
      if (createdURL && createdURL !== previewURL) URL.revokeObjectURL(createdURL);
      if (request === controller) { request = null; render(); }
    }
  }

  function clearConfig() {
    el('opt-crop_ratio').value = ''; el('opt-crop_rect').value = '';
    el('opt-crop_x').value = '50'; el('opt-crop_y').value = '50';
  }

  function setFile(next) {
    const replacing = !!file && next !== file;
    request?.abort(); request = null;
    if (previewURL) URL.revokeObjectURL(previewURL);
    previewURL = null; source = null; failure = ''; drag = null; draft = null;
    el('crop-source').removeAttribute('src');
    if (el('crop-dialog').open) el('crop-dialog').close('cancel');
    if (replacing || !next) clearConfig();
    file = next;
    render();
    if (file) loadPreview();
    if (replacing || !next) document.dispatchEvent(new Event('crop-change'));
  }

  function open() {
    if (!file || unavailable() || el('crop-dialog').open) return;
    draft = source ? makeDraft() : null;
    syncDraftControls();
    el('crop-dialog').showModal();
    render();
    if (!source && !request) loadPreview();
    requestAnimationFrame(() => { layoutStage(); if (draft) el('crop-frame').focus({preventScroll:true}); });
  }

  function cancel() {
    drag = null; draft = null;
    if (el('crop-dialog').open) el('crop-dialog').close('cancel');
    render();
  }

  function apply() {
    if (unavailable() || !source || !draft || draft.error) return;
    const previous = JSON.stringify(rawConfig()), {x,y,w,h} = draft.rect;
    const full = x===0 && y===0 && w===source.width && h===source.height;
    el('opt-crop_ratio').value = draft.ratio;
    el('opt-crop_rect').value = full && !draft.ratio ? '' : [x,y,w,h].join(',');
    el('opt-crop_x').value = w===source.width ? '50' : String(Math.round(x*100/(source.width-w)));
    el('opt-crop_y').value = h===source.height ? '50' : String(Math.round(y*100/(source.height-h)));
    draft = null; drag = null; el('crop-dialog').close('apply'); render();
    if (previous !== JSON.stringify(rawConfig())) document.dispatchEvent(new Event('crop-change'));
  }

  function fitRatio(ratio) {
    const [a,b] = terms(ratio), current = draft.rect;
    const maximum = Math.min(Math.floor(source.width/a),Math.floor(source.height/b));
    if (!maximum) throw new Error('此比例无法在这张图片中裁出整数像素，请更换比例。');
    const units = clamp(Math.floor(Math.min(current.w/a,current.h/b)),1,maximum);
    const w = a*units, h = b*units;
    draft.rect = {x:clamp(Math.round(current.x+current.w/2-w/2),0,source.width-w),
      y:clamp(Math.round(current.y+current.h/2-h/2),0,source.height-h),w,h};
  }

  function changeRatio() {
    if (unavailable() || !draft) return;
    const mode = el('crop-preset').value;
    el('custom-ratio-field').hidden = mode !== 'custom';
    const ratio = mode==='free' ? '' : mode==='custom' ? el('crop-custom-ratio').value.trim() : mode;
    try { if (ratio) fitRatio(ratio); draft.ratio = ratio; draft.error = ''; }
    catch (error) { draft.error = error.message; }
    renderDraft();
  }

  function resizeCorner(rect, corner, px, py) {
    const sx = corner.includes('w') ? -1 : 1, sy = corner.includes('n') ? -1 : 1;
    const ax = sx<0 ? rect.x+rect.w : rect.x, ay = sy<0 ? rect.y+rect.h : rect.y;
    if (draft.ratio) {
      const [a,b] = terms(draft.ratio);
      const maximum = Math.floor(Math.min((sx<0 ? ax : source.width-ax)/a,(sy<0 ? ay : source.height-ay)/b));
      if (maximum < 1) return rect;
      const wantedW = Math.max(a,(px-ax)*sx), wantedH = Math.max(b,(py-ay)*sy);
      const units = clamp(Math.round((wantedW*a+wantedH*b)/(a*a+b*b)),1,maximum);
      const w = units*a, h = units*b;
      return {x:sx<0 ? ax-w : ax,y:sy<0 ? ay-h : ay,w,h};
    }
    const x = Math.round(clamp(px,sx<0 ? 0 : ax+1,sx<0 ? ax-1 : source.width));
    const y = Math.round(clamp(py,sy<0 ? 0 : ay+1,sy<0 ? ay-1 : source.height));
    return {x:Math.min(ax,x),y:Math.min(ay,y),w:Math.abs(x-ax),h:Math.abs(y-ay)};
  }

  function pointerPosition(event) {
    const bounds = el('crop-stage').getBoundingClientRect();
    return {x:(event.clientX-bounds.left)*source.width/bounds.width,
      y:(event.clientY-bounds.top)*source.height/bounds.height};
  }

  function init() {
    if (initialized) return;
    initialized = true;
    el('crop-open').addEventListener('click',open);
    el('crop-cancel').addEventListener('click',cancel);
    el('crop-close').addEventListener('click',cancel);
    el('crop-apply').addEventListener('click',apply);
    el('crop-dialog').addEventListener('cancel',event => { event.preventDefault(); cancel(); });
    el('crop-dialog').addEventListener('close',() => { drag = null; draft = null; render(); });
    el('crop-preset').addEventListener('change',changeRatio);
    el('crop-custom-ratio').addEventListener('input',changeRatio);
    el('crop-reset').addEventListener('click',() => {
      if (unavailable() || !source) return;
      draft = {ratio:'',rect:fullRect(),error:''}; syncDraftControls(); renderDraft();
    });
    const frame = el('crop-frame');
    frame.addEventListener('pointerdown',event => {
      if (unavailable() || !draft || draft.error || event.button!==0 || drag) return;
      event.preventDefault(); event.stopPropagation();
      drag = {id:event.pointerId,position:pointerPosition(event),rect:{...draft.rect},
        corner:event.target.closest('[data-crop-handle]')?.dataset.cropHandle || null};
      frame.setPointerCapture(event.pointerId);
    });
    frame.addEventListener('pointermove',event => {
      if (unavailable() || !drag || event.pointerId!==drag.id) return;
      event.preventDefault();
      const pointer = pointerPosition(event), rect = drag.rect;
      draft.rect = drag.corner ? resizeCorner(rect,drag.corner,pointer.x,pointer.y) : {
        ...rect,x:clamp(Math.round(rect.x+pointer.x-drag.position.x),0,source.width-rect.w),
        y:clamp(Math.round(rect.y+pointer.y-drag.position.y),0,source.height-rect.h)};
      renderDraft();
    });
    frame.addEventListener('pointerup',event => { if (drag?.id===event.pointerId) { drag=null; frame.releasePointerCapture(event.pointerId); } });
    frame.addEventListener('pointercancel',() => { drag=null; });
    frame.addEventListener('lostpointercapture',() => { drag=null; });
    frame.addEventListener('keydown',event => {
      if (unavailable() || !draft || draft.error || !event.key.startsWith('Arrow')) return;
      event.preventDefault(); event.stopPropagation();
      const step = event.shiftKey ? 10 : 1, rect = draft.rect;
      const dx = event.key==='ArrowLeft' ? -step : event.key==='ArrowRight' ? step : 0;
      const dy = event.key==='ArrowUp' ? -step : event.key==='ArrowDown' ? step : 0;
      const corner = event.target.closest('[data-crop-handle]')?.dataset.cropHandle;
      if (corner) {
        const sx=corner.includes('w')?-1:1, sy=corner.includes('n')?-1:1;
        let x=sx<0?rect.x:rect.x+rect.w, y=sy<0?rect.y:rect.y+rect.h;
        if (draft.ratio) { const [a,b]=terms(draft.ratio), delta=dx*sx+dy*sy; x+=sx*a*delta; y+=sy*b*delta; }
        else { x+=dx; y+=dy; }
        draft.rect=resizeCorner(rect,corner,x,y);
      } else draft.rect={...rect,x:clamp(rect.x+dx,0,source.width-rect.w),y:clamp(rect.y+dy,0,source.height-rect.h)};
      renderDraft();
    });
    new ResizeObserver(layoutStage).observe(el('crop-workspace'));
    window.addEventListener('beforeunload',() => { request?.abort(); if (previewURL) URL.revokeObjectURL(previewURL); });
    render();
  }

  function syncPreset() {
    if (el('crop-dialog')?.open && source) { draft=makeDraft(); syncDraftControls(); }
    render();
  }

  function setBusy(value) { locked=!!value; if (locked && el('crop-dialog')?.open) cancel(); render(); }

  return {init,terms,validateRect,validateConfig,getConfig,setFile,syncPreset,render,setBusy,open};
})();
