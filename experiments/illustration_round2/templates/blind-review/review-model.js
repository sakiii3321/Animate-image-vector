(function (root) {
  'use strict';
  const dimensions = [['overall', '整体还原'], ['detail', '细节保留'], ['line', '线条连续'], ['color', '色彩渐变']];
  function create(data) {
    return {version: 1, experiment_id: data.experiment_id, reviewer: '', saved_utc: null,
      rows: data.cases.flatMap(c => c.candidates.map(v => ({image_id: c.id, source_name: c.source_name, candidate: v.id,
        overall: null, detail: null, line: null, color: null, notes: ''})))};
  }
  function validate(data, input) {
    if (!input || input.version !== 1 || input.experiment_id !== data.experiment_id || !Array.isArray(input.rows)) {
      throw new Error('评分文件不属于本次盲评，或格式不正确。');
    }
    const result = create(data), allowed = new Map(result.rows.map(r => [r.image_id + '/' + r.candidate, r]));
    const seen = new Set();
    for (const row of input.rows) {
      if (!row || typeof row !== 'object') throw new Error('评分行格式不正确。');
      const id = row.image_id + '/' + row.candidate, target = allowed.get(id);
      if (!target || seen.has(id)) throw new Error('图片或候选编号无效，或有重复行。');
      seen.add(id);
      for (const [field] of dimensions) {
        const value = row[field] == null ? null : row[field];
        if (value !== null && (!Number.isInteger(value) || value < 1 || value > 5)) throw new Error('分数必须是 1～5 的整数或留空。');
        target[field] = value;
      }
      target.notes = typeof row.notes === 'string' ? row.notes : '';
    }
    result.reviewer = typeof input.reviewer === 'string' ? input.reviewer : '';
    result.saved_utc = typeof input.saved_utc === 'string' ? input.saved_utc : null;
    return result;
  }
  function complete(row) {return dimensions.every(([k]) => Number.isInteger(row[k]) && row[k] >= 1 && row[k] <= 5);}
  function progress(model) {return {complete: model.rows.filter(complete).length, total: model.rows.length};}
  function csv(model) {
    const escape = value => {
      let s = value == null ? '' : String(value);
      if (/^[=+@\-\t\r]/.test(s)) s = "'" + s;
      return '"' + s.replace(/"/g, '""') + '"';
    };
    const rows = [['批次', '图片编号', '原图文件', '候选', '整体还原_1到5', '细节保留_1到5', '线条连续_1到5', '色彩渐变_1到5', '备注', '评分人']];
    for (const row of model.rows) rows.push([model.experiment_id, row.image_id, row.source_name, row.candidate,
      ...dimensions.map(([k]) => row[k]), row.notes, model.reviewer]);
    return '\ufeff' + rows.map(row => row.map(escape).join(',')).join('\r\n') + '\r\n';
  }
  const api = {dimensions, create, validate, complete, progress, csv};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ReviewModel = api;
})(typeof window !== 'undefined' ? window : globalThis);
