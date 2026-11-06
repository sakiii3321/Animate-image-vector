'use strict';
(() => {
  const data = window.REVIEW_DATA, M = window.ReviewModel;
  const $ = id => document.getElementById(id);
  const storageKey = 'blind-review-' + data.experiment_id;
  let model = M.create(data), index = 0, focus = 'A', pair = window.innerWidth < 1100;
  let zoom = 1, centerX = 0.5, centerY = 0.5, panes = [], dragging = null;
  const message = text => {$('message').textContent = text;};
  const storageMessage = (text, error) => {$('storage-status').textContent = text; $('storage-status').classList.toggle('error', !!error);};
  try {
    const stored = localStorage.getItem(storageKey);
    if (stored) {model = M.validate(data, JSON.parse(stored)); storageMessage('已恢复当前浏览器内的评分。仍请定期导出备份。');}
  } catch (_) {storageMessage('本地自动保存不可用，请用“导出 JSON”保存评分。', true);}
  $('reviewer').value = model.reviewer;
  function save() {
    model.reviewer = $('reviewer').value;
    model.saved_utc = new Date().toISOString();
    try {localStorage.setItem(storageKey, JSON.stringify(model)); storageMessage('已暂存到当前浏览器 · 请导出 JSON 作为独立备份。');}
    catch (_) {storageMessage('自动保存失败；当前评分仍在页面中，请立即导出 JSON。', true);}
    updateProgress();
  }
  function updateProgress() {
    const p = M.progress(model), count = model.rows.filter(r => r.image_id === data.cases[index].id && M.complete(r)).length;
    $('progress').textContent = `完整评分 ${p.complete} / ${p.total} · 当前图片 ${count} / 4`;
  }
  data.cases.forEach((c, i) => {
    const option = document.createElement('option');option.value = i;option.textContent = `${i + 1} / ${data.cases.length} · ${c.id} · ${c.source_name}`;$('case').appendChild(option);
  });
  for (const id of ['A', 'B', 'C', 'D']) {
    const b = document.createElement('button');b.textContent = id;b.dataset.id = id;
    b.title = `两栏查看候选 ${id}`;b.addEventListener('click', () => {focus = id;pair = true;setLayout();});$('focus').appendChild(b);
  }
  function addPane(label, src, id) {
    const pane = document.createElement('section');pane.className = 'pane';pane.dataset.id = id;
    const header = document.createElement('div');header.className = 'pane-head';
    const title = document.createElement('span');title.textContent = label;header.appendChild(title);
    const link = document.createElement('a');link.href = src;link.target = '_blank';link.rel = 'noopener';link.textContent = id === 'source' ? '打开原图' : '打开 SVG';header.appendChild(link);
    const viewport = document.createElement('div');viewport.className = 'viewport';viewport.setAttribute('aria-label', label + '，可滚轮缩放和拖动');
    const img = new Image();img.alt = label;img.draggable = false;
    const status = document.createElement('span');status.className = 'load-status';status.textContent = '加载中…';
    img.addEventListener('load', () => {status.textContent = '';updateView();});
    img.addEventListener('error', () => {status.textContent = '文件未能加载，请打开 SVG 单独查看';status.classList.add('error');});
    viewport.append(img, status);pane.append(header, viewport);$('viewers').appendChild(pane);
    viewport.addEventListener('wheel', event => {
      event.preventDefault();const rect = viewport.getBoundingClientRect();
      changeZoom(zoom * Math.exp(-event.deltaY * 0.0018), viewport, event.clientX - rect.left, event.clientY - rect.top);
    }, {passive: false});
    viewport.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      const c = data.cases[index], scale = Math.min(viewport.clientWidth / c.width, viewport.clientHeight / c.height) * zoom;
      dragging = {id: event.pointerId, x: event.clientX, y: event.clientY, cx: centerX, cy: centerY, scale};viewport.setPointerCapture(event.pointerId);
    });
    viewport.addEventListener('pointermove', event => {
      if (!dragging || dragging.id !== event.pointerId) return;const c = data.cases[index];
      centerX = Math.max(0, Math.min(1, dragging.cx - (event.clientX - dragging.x) / (c.width * dragging.scale)));
      centerY = Math.max(0, Math.min(1, dragging.cy - (event.clientY - dragging.y) / (c.height * dragging.scale)));updateView();
    });
    const end = () => {dragging = null;};viewport.addEventListener('pointerup', end);viewport.addEventListener('pointercancel', end);viewport.addEventListener('lostpointercapture', end);
    viewport.addEventListener('dblclick', resetView);
    panes.push({pane, viewport, img, id});img.src = src;
  }
  function renderScores() {
    $('scores').replaceChildren();const c = data.cases[index];
    for (const candidate of c.candidates) {
      const row = model.rows.find(r => r.image_id === c.id && r.candidate === candidate.id);
      const card = document.createElement('article');card.className = 'score-card';
      const heading = document.createElement('h3');heading.textContent = c.id + ' · 候选 ' + candidate.id;card.appendChild(heading);
      for (const [field, text] of M.dimensions) {
        const label = document.createElement('label');label.className = 'score-row';label.append(document.createTextNode(text));
        const select = document.createElement('select');select.setAttribute('aria-label', candidate.id + ' ' + text);
        for (const [value, text] of [['', '未评分'], ['1', '1 · 严重失真'], ['2', '2 · 明显较差'], ['3', '3 · 基本可用'], ['4', '4 · 比较接近'], ['5', '5 · 非常接近']]) {
          const option = document.createElement('option');option.value = value;option.textContent = text;select.appendChild(option);
        }
        select.value = row[field] == null ? '' : String(row[field]);select.addEventListener('change', () => {row[field] = select.value === '' ? null : Number(select.value);save();});label.appendChild(select);card.appendChild(label);
      }
      const notes = document.createElement('textarea');notes.placeholder = '备注：缺失位置、断线、颜色问题等（可选）';notes.setAttribute('aria-label', candidate.id + ' 备注');notes.value = row.notes;
      notes.addEventListener('input', () => {row.notes = notes.value;save();});card.appendChild(notes);$('scores').appendChild(card);
    }
  }
  function setLayout() {
    $('viewers').classList.toggle('pair', pair);$('pair').classList.toggle('active', pair);$('all').classList.toggle('active', !pair);
    for (const p of panes) p.pane.classList.toggle('hidden', pair && p.id !== 'source' && p.id !== focus);
    for (const b of $('focus').children) b.classList.toggle('active', pair && b.dataset.id === focus);
    updateView();
  }
  function updateView() {
    const c = data.cases[index];
    for (const p of panes) {
      if (p.pane.classList.contains('hidden')) continue;
      const w = p.viewport.clientWidth, h = p.viewport.clientHeight, scale = Math.min(w / c.width, h / c.height) * zoom;
      Object.assign(p.img.style, {width: c.width * scale + 'px', height: c.height * scale + 'px', left: w / 2 - centerX * c.width * scale + 'px', top: h / 2 - centerY * c.height * scale + 'px'});
    }
    $('zoom').value = Math.log2(zoom);$('zoom-label').textContent = zoom.toFixed(1) + '×';
  }
  function changeZoom(value, viewport, px, py) {
    const next = Math.max(1, Math.min(32, value));
    if (viewport) {
      const c = data.cases[index], w = viewport.clientWidth, h = viewport.clientHeight, fit = Math.min(w / c.width, h / c.height);
      centerX = Math.max(0, Math.min(1, centerX + (px - w / 2) / (c.width * fit) * (1 / zoom - 1 / next)));
      centerY = Math.max(0, Math.min(1, centerY + (py - h / 2) / (c.height * fit) * (1 / zoom - 1 / next)));
    }
    zoom = next;updateView();
  }
  function resetView() {zoom = 1;centerX = centerY = 0.5;updateView();}
  function renderCase() {
    const c = data.cases[index];$('case').value = index;$('viewers').replaceChildren();panes = [];dragging = null;zoom = 1;centerX = centerY = 0.5;
    addPane('原图', c.original, 'source');for (const v of c.candidates) addPane('候选 ' + v.id, v.svg, v.id);
    $('image-info').textContent = `${c.id} · ${c.source_name} · ${c.width} × ${c.height} · 所有画面保持相同取景位置与倍率。`;
    $('previous').disabled = index === 0;$('next').disabled = index === data.cases.length - 1;
    $('next-bottom').textContent = index === data.cases.length - 1 ? '导出评分 JSON' : '保存并看下一张 →';
    renderScores();setLayout();updateProgress();message('');
  }
  function move(delta) {save();index = Math.max(0, Math.min(data.cases.length - 1, index + delta));renderCase();}
  function download(kind) {
    save();const json = kind === 'json', text = json ? JSON.stringify(model, null, 2) : M.csv(model);
    const blob = new Blob([text], {type: json ? 'application/json;charset=utf-8' : 'text/csv;charset=utf-8'});
    const url = URL.createObjectURL(blob), a = document.createElement('a');a.href = url;a.download = '评分_' + data.experiment_id + '_' + new Date().toISOString().replace(/[:.]/g, '-') + '.' + kind;
    document.body.appendChild(a);a.click();a.remove();setTimeout(() => URL.revokeObjectURL(url), 10000);message('已请求下载评分文件。请保留它，评分后交回本对话。');
  }
  $('case').addEventListener('change', () => {save();index = Number($('case').value);renderCase();});
  $('previous').addEventListener('click', () => move(-1));$('next').addEventListener('click', () => move(1));
  $('next-bottom').addEventListener('click', () => index === data.cases.length - 1 ? download('json') : move(1));
  $('fit').addEventListener('click', resetView);$('zoom').addEventListener('input', () => changeZoom(2 ** Number($('zoom').value)));
  $('native').addEventListener('click', () => {const p = panes.find(p => !p.pane.classList.contains('hidden')), c = data.cases[index];changeZoom(1 / Math.min(p.viewport.clientWidth / c.width, p.viewport.clientHeight / c.height));});
  $('all').addEventListener('click', () => {pair = false;setLayout();});$('pair').addEventListener('click', () => {pair = true;setLayout();});
  $('reviewer').addEventListener('input', save);$('export-json').addEventListener('click', () => download('json'));$('export-csv').addEventListener('click', () => download('csv'));
  $('import').addEventListener('click', () => $('import-file').click());
  $('import-file').addEventListener('change', async event => {
    const file = event.target.files[0];if (!file) return;
    try {const next = M.validate(data, JSON.parse(await file.text()));model = next;$('reviewer').value = model.reviewer;save();renderScores();message('已导入评分，可继续填写。');}
    catch (error) {message('未导入：' + error.message);}finally {event.target.value = '';}
  });
  document.addEventListener('keydown', event => {
    if (event.ctrlKey || event.altKey || event.metaKey || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    if (/^[a-d]$/i.test(event.key)) {focus = event.key.toUpperCase();pair = true;setLayout();}
    if (event.key === 'ArrowRight') {event.preventDefault();move(1);}if (event.key === 'ArrowLeft') {event.preventDefault();move(-1);}
  });
  new ResizeObserver(updateView).observe($('viewers'));
  renderCase();
})();
