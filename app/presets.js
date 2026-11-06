'use strict';

// User-facing starting points derive from the server's versioned profiles.
// They are parameter choices, not quality scores or image-specific tuning.
const presetEditor=(()=>{
  const el=id=>document.getElementById(id);
  const definitions=[
    {id:'balanced',title:'均衡插画',profile:'edge_clean',description:'兼顾轮廓、色彩与文件体积，适合先看整体效果。',values:{path_limit:2000,potrace_palette_colors:100,curve_tolerance:.3}},
    {id:'detail',title:'细节优先',profile:'edge_clean',description:'为发丝、装饰和小色块留出更多空间；耗时与文件体积可能增加。',values:{path_limit:4000,potrace_palette_colors:160,curve_tolerance:.2}},
    {id:'compact',title:'轻量简洁',profile:'edge_clean',description:'减少路径和配色，方便轻量使用；细小花纹可能被简化。',values:{path_limit:800,potrace_palette_colors:64,curve_tolerance:.5}},
    {id:'gradient',title:'柔和渐变',profile:'gradient_layers',description:'用渐变衔接大色面明暗；复杂纹理和细小图案需要放大检查。',values:{}},
    {id:'line_art',title:'线稿',profile:'edge_clean',description:'较少分色搭配保守的曲线简化，适合浅底线稿；不会自动转黑白。',values:{path_limit:1500,potrace_palette_colors:64,curve_tolerance:.2}}
  ];
  let hooks,entries=[],active=null,lastConfig={},disabled=false;
  function pill(text){const span=document.createElement('span');span.textContent=text;return span;}
  function preservedKey(key){return key==='output_directory'||hooks.schema[key]?.section==='crop';}
  function sync(config,{editing=false}={}){
    if(!hooks)return;
    lastConfig={...config};
    active=editing?null:entries.find(entry=>Object.keys(entry.config).filter(key=>!preservedKey(key)).every(key=>config[key]===entry.config[key]))||null;
    for(const card of el('preset-grid').querySelectorAll('[data-preset]')){
      const selected=card.dataset.preset===active?.id;card.setAttribute('aria-pressed',String(selected));
    }
    const summary=el('preset-summary');summary.dataset.preset=active?.id||'custom';summary.replaceChildren();
    const title=document.createElement('strong');title.textContent=active?active.title:'自定义';summary.append(title);
    const text=document.createElement('span');text.className='preset-summary-description';text.textContent=editing?'参数正在编辑，请检查数值后转换。':active?'当前预设 · 裁剪与保存位置可单独设置。':'当前参数与预设不同；可保留设置直接转换，或展开高级模式调整。';summary.append(text);
    const pills=document.createElement('div');pills.className='preset-pills';
    if(Number.isFinite(config.path_limit))pills.append(pill(`${config.path_limit.toLocaleString()} 路径`));
    if(Number.isFinite(config.potrace_palette_colors))pills.append(pill(`${config.potrace_palette_colors} 色分区`));
    if(config.curve_simplify&&Number.isFinite(config.curve_tolerance))pills.append(pill(`曲线容差 ${config.curve_tolerance}`));
    if(config.sr_enabled)pills.append(pill(`超分 ${config.sr_scale}×`));
    if(config.diffvg_optimize||config.highres_refine)pills.append(pill('增强优化已开'));
    if(!config.sr_enabled&&!config.diffvg_optimize&&!config.highres_refine)pills.append(pill('增强关闭'));
    summary.append(pills);
    if(!active){const button=document.createElement('button');button.type='button';button.dataset.openAdvanced='';button.textContent='查看高级设置';button.disabled=disabled;button.setAttribute('aria-controls','advanced-settings');button.onclick=()=>setAdvanced(true);summary.append(button);}
  }
  function setAdvanced(value){
    if(disabled)return;
    el('advanced-mode').checked=value;el('advanced-settings').hidden=!value;
    hooks.onAdvancedChange?.(value);
  }
  function choose(id){
    if(disabled)return;
    const entry=entries.find(item=>item.id===id);if(!entry)return;
    try{
      hooks.apply({...entry.config,...hooks.getPreserved()});
      hooks.status(`已采用「${entry.title}」。裁剪与保存位置保留，超分及增强优化已关闭。`);
    }catch(error){hooks.onError(error);}
  }
  function setBusy(value){
    disabled=value;if(!hooks)return;
    el('advanced-mode').disabled=value;
    for(const button of el('preset-grid').querySelectorAll('button'))button.disabled=value;
    for(const button of el('preset-summary').querySelectorAll('button'))button.disabled=value;
  }
  function init(callbacks){
    hooks=callbacks;
    entries=definitions.map(definition=>({...definition,config:{...hooks.defaults,...hooks.profilePresets[definition.profile],...definition.values,
      sr_enabled:false,sr_scale:hooks.defaults.sr_scale,diffvg_optimize:false,highres_refine:false,
      detail_region:'',simplify_target_paths:0}}));
    const grid=el('preset-grid');grid.replaceChildren();
    for(const entry of entries){
      const button=document.createElement('button');button.type='button';button.className='preset-card';button.dataset.preset=entry.id;button.setAttribute('aria-pressed','false');
      const title=document.createElement('span');title.className='preset-title';title.textContent=entry.title;
      const description=document.createElement('span');description.className='preset-description';description.textContent=entry.description;
      button.append(title,description);button.onclick=()=>choose(entry.id);grid.append(button);
    }
    el('advanced-mode').onchange=()=>setAdvanced(el('advanced-mode').checked);
    setAdvanced(false);sync(hooks.getConfig());setBusy(false);
  }
  return {init,sync,choose,setBusy,setAdvanced,markCustom:()=>sync(lastConfig,{editing:true})};
})();
