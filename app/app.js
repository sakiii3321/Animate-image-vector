'use strict';
const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.search).get('token');
const headers = {'X-App-Token':token};
const tips = {
 potrace_trace_threads:'并行描摹多个已分好的色块，适用于初始 Potrace 转换及目标色块合并后的重新描摹。\n0 为自动：较大任务最多使用 4 个线程，小任务使用 1 个；1 为单线程，2–16 为希望使用的线程数。实际数量受 CPU、可用内存及色块数量限制，进度中会显示。\n线程共享区域标签图，按统一绘制顺序组合 SVG；不会改变路径预算或描摹参数。此项只控制描摹，不会让有先后依赖的相邻色块合并同时执行。线程越多不一定越快。',
 path_limit:'限制最终绘制路径总数，包含色块和分层补线。\n较低上限会合并更多相邻区域，可能损失眼部、花纹和细线；增加上限允许更多细节，也会增加耗时和文件大小。\n这是上限，简单图片通常不需要用满。',
 detail_region:'填写经 EXIF 方向规范化后的原图坐标：x,y,宽,高。\n启用裁剪时仍使用原图坐标，只处理与裁剪框重叠的部分。\n区域内会分配部分初始颜色、使用细节区域权重，并把小色块合并面积阈值减半。留空时全图采用统一规则。\n启用超分后坐标会自动按倍数映射；高权重也不能恢复初始分区已经漏掉的细节。',
 potrace_alpha_max:'控制 Potrace 对尖角与平滑曲线的取舍。\n调小会保留更多尖角；0 表示不做平滑，生成多边形。调大更容易把转角平滑化，超过约 1.33 时会抑制全部角点。\n发尖或衣褶被磨圆时可适当调小，但可能产生更多折角；默认 1。',
 potrace_opt_tolerance:'控制 Potrace 内部相邻曲线段合并时允许的轮廓偏差，按原图像素计。\n调大通常能合并更多曲线段，代价是局部轮廓偏差增大；调小更严格，可能保留更多段。默认 0.4。\n只有启用内部曲线优化时生效。超分后自动按倍数缩放；与生成 SVG 后的“曲线简化容差”属于不同处理阶段。',
 potrace_opt_curve:'在 Potrace 描摹内部合并可兼容的相邻曲线段。\n开启时使用曲线合并容差减少冗余段；关闭后保留更多原始拟合片段，文件往往更大。\n这不控制色块合并，也不影响是否选择后处理的“曲线简化”。关闭时容差设置会保留。',
 potrace_turn_policy:'决定黑白像素对角接触等歧义位置的边界连接方式。\nminority 优先连接局部较少的颜色，majority 优先连接较多的颜色；black / white 偏向连接黑色前景 / 白色背景；left / right 固定向左 / 右处理。\n它可能影响细线连接与小孔洞。当前按每个色块的黑白蒙版描摹，默认 minority，并非直接选择彩色图中的某个颜色。',
 potrace_turd_size:'在 Potrace 描摹阶段删除面积不超过此值的小轮廓，按原图像素面积计。\n调大可能去掉小斑点，也可能删除小色块或孔洞，在彩色拼接中留下空隙。默认 0，保留已分配的区域。\n需要减少碎块时优先调整“近色小块清理”；超分后此面积值自动乘以倍数的平方。',
 potrace_palette_colors:'设置分区前的初始颜色聚类数量，不是最终 SVG 色块数量。\n调大允许区分更多近似颜色，通常保留更多色彩细节，也可能产生更多碎片并增加聚类、合并耗时；调小会加强颜色归并。\n有细节区域时约 2/3 分配全图、1/3 分配局部，默认总数 48。最终填充路径仍受数量上限约束。',
 potrace_preserve_structure:'识别并优先保留封闭的小图案，适合眼白、圆点和装饰纹样。\n根据多个颜色阈值、局部对比和形状筛选候选，初始分色及后续合并都保留其边界；同时加强大区域的颜色误差约束，减少阴影被过度合并。启用超分时从裁剪后的原图识别。\n这是几何规则，不是眼睛或服装识别模型，可能漏检，也可能保留不需要的纹理。最多保护 256 个候选，路径上限过低仍会合并；不会增加上限。默认关闭，便于与原方案比较。',
 potrace_smoothing:'控制分色前双边滤波的强度倍数，默认 1，0 完全跳过。\n调大扩大空间平滑并允许融合更多相近颜色，通常减少细碎纹理，但可能抹掉细发丝或眼部边缘；调小保留更多纹理和噪点。\n它处理的是分区输入，最终区域颜色仍取自图片。空间尺度会随超分倍数自动缩放。',
 potrace_min_region_area:'清理小于此面积且与邻区颜色非常接近的碎块，按原图像素面积计。\n高色差小块会保留到按路径预算合并的阶段。预算合并以感知色差为基础，使用减弱的面积权重保护小细节，并限制大色面失真；初次描摹和后处理都使用此策略。\n0 关闭小块清理。细节区域使用一半面积阈值；超分后面积阈值乘以倍数的平方。路径预算过低仍可能损失细节。',
 potrace_detail_weight:'提高细节优先区域在相邻色块合并误差中的权重，填写细节区域后生效。\n调大更倾向保留该区域的颜色差异，其他位置可能承担更多简化；1 表示与全图相同权重。默认 15。\n它不会增加路径数量上限，也不能保证区域内所有细节都被保留；留空细节区域时保留设置但不使用。',
 potrace_stroke_width:'给每个填充色块增加同色描边，宽度按原图像素计，默认 1。\n适量描边可遮住独立色块边缘的细缝；调大也会扩张轮廓、加粗细线并覆盖附近细节。0 关闭描边。\n开启描边时先绘制大色块，再绘制小细节，以减少背景描边覆盖细线。超分后宽度自动按倍数缩放。透明图中的填充与描边作为整体应用一次透明度。',
 output_directory:'留空使用系统临时目录，该目录可能被系统清理。\n可填写绝对路径或相对启动目录的路径；不存在的目录会创建。每次保存使用唯一文件名，不覆盖已有文件。开启增强后还会保存同名阶段统计报告。',
 sr_enabled:'先通过 Real-ESRGAN 细化图片，再进行矢量化。\n超分可能改善轮廓与局部细节，也可能生成偏离原图的纹理，并增加处理耗时、内存和候选区域数量。\n开启时默认选择高分辨率补充优化，可手动取消；图片仍只在本机处理。',
 sr_scale:'选择宽和高的放大倍数：2× 对应 4 倍像素，4× 对应 16 倍像素。\n倍数越高，对内存和处理时间的要求越高，也不保证重构更准确。超分输出上限为 1.6 亿像素。\n最终 SVG 使用超分前的画布尺寸，启用裁剪时即选框尺寸；改变倍数不会覆盖你手动取消高分补充的选择。',
 curve_simplify:'在 SVG 生成后合并冗余曲线段，保留强转角。\nPotrace 可先按目标数量合并相邻色块，再简化曲线；目标设为 0 时仅简化曲线，保留色块数量。\n与 Potrace 内部曲线优化可分别控制；允许的几何误差可能改变局部轮廓。',
 simplify_target_paths:'开启曲线简化时可额外指定更小的绘制路径预算，0 表示沿用上限。\n边缘清理及分层方案从初始分区就使用两者中的较小值，包含补线，不重复简化。传统 Potrace 在初次描摹后继续合并相邻色块。\n降低预算会损失部分局部形状，建议结合放大预览比较。',
 curve_tolerance:'后处理曲线简化允许的几何误差尺度，按原图像素计，默认 0.3。\n调大更容易合并曲线段，也更容易改变发尖、弧线和窄区域；调小更保守，可能保留较多曲线。\n建议结合总段数与放大对比判断，不能仅依据 SVG 文件大小。',
 diffvg_optimize:'以参考图片为目标优化全图路径坐标和颜色。\n开启超分时拟合超分图，否则拟合原图；全画幅目标长边最高 1024，保持比例。\n优化保持路径结构，不能自行补出初始分区遗漏的色块；更多计算不保证更高画质。',
 diffvg_iterations:'设置 DiffVG 全画幅优化更新次数。\n调大通常增加耗时，可能进一步改善颜色和轮廓，也可能收益很小或出现局部偏移。\n这不是曲线简化次数，不会直接减少段数，也不控制高分辨率补充的分块数量。',
 highres_refine:'以超分图实际像素尺度分块覆盖整张图，共享同一组矢量参数。\n可单独启用，补充普通全画幅缩小目标看不清的细节；耗时随超分像素和曲线复杂度增加。\n只有开启超分辨率后可选；关闭超分会取消并禁用它。'
};
let schema,defaults,legacyDefaults,retiredEngineFields=[],profileLabels={},profilePresets={},originalURL,processedURL,vectorURL,svgBlob,inputFile,busy=false,progressTimer=null,progressGeneration=0,processedScale=1,conversionActive=false,stopRequested=false;
let recommendation=null,analysisGeneration=0,analysisTimer=null,analysisRequest=null,resultGeneration=0;
tips.illustration_profile='边缘清理：先保边平滑，再清理抗锯齿混色碎片、连接相近细线，最后合并色块与拟合曲线。通用默认。\n渐变分层：先重建大色面，再按重构误差补线和补色；仅为通过独立像素检验的区域添加线性渐变。适合柔和上色。\n平涂分层：同样分层补线，但不使用渐变，保留为实验对比。\n传统 Potrace 保留旧配置行为。切换方案会加载参数预设，可继续调整；超分、裁剪和保存位置不变。';
tips.potrace_smoothing+='\n边缘清理及分层方案内部已有两次固定的轻度保边滤波；此项为额外的预平滑，预设为 0，避免重复平滑吞掉细线。传统路线仍按本项控制预平滑。';
function fileBase64(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=()=>reject(new Error('无法读取图片。'));r.readAsDataURL(file);});}
function isLayered(){return ['flat_layers','gradient_layers'].includes($('opt-illustration_profile')?.value);}
function applyProfile(profile,extra={}){
 const preset=profilePresets[profile];if(!preset)return;
 const c={...getConfig(),...preset,...extra};setConfig(c);
 $('status').textContent=`已载入「${profileLabels[profile]}」参数，可继续微调。`;
}
function scheduleAnalysis(){
 ++analysisGeneration;clearTimeout(analysisTimer);analysisRequest?.abort();analysisRequest=null;recommendation=null;
 $('apply-recommendation').disabled=true;$('apply-recommendation').hidden=true;$('recommendation-reasons').hidden=true;
 $('analyze-image').disabled=busy||!inputFile;
 $('recommendation-summary').textContent=inputFile?'正在分析当前图片范围…':'选图后分析清晰度、线条、色彩与构图。可一键采用建议。';
 if(inputFile&&!busy)analysisTimer=setTimeout(analyzeSelectedImage,400);
}
async function analyzeSelectedImage(){
 if(!inputFile||busy)return;
 const generation=analysisGeneration,file=inputFile,controller=new AbortController();analysisRequest=controller;
 $('analyze-image').disabled=true;
 try{
  const config=cropEditor.getConfig(),image=await fileBase64(file);
  if(generation!==analysisGeneration||controller.signal.aborted)return;
  const response=await fetch('/api/analyze',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({image,config}),signal:controller.signal});
  const r=await response.json();if(!response.ok)throw new Error(r.error||'分析未完成。');
  if(generation!==analysisGeneration)return;recommendation=r;
  $('recommendation-summary').textContent=`${r.type_label} · 复杂度${r.complexity.label} · ${r.clarity.label} · ${r.composition.orientation_label} / ${r.composition.layout_label}。建议「${profileLabels[r.recommended_profile]}」，路径上限 ${r.suggested_params.path_limit}。`;
  const list=$('recommendation-reasons');list.replaceChildren();for(const text of r.reasons){const li=document.createElement('li');li.textContent=text;list.append(li);}list.hidden=false;
  $('apply-recommendation').hidden=false;$('apply-recommendation').disabled=busy;
 }catch(error){if(generation===analysisGeneration&&error.name!=='AbortError')$('recommendation-summary').textContent='分析未完成：'+error.message;}
 finally{if(generation===analysisGeneration){analysisRequest=null;$('analyze-image').disabled=busy||!inputFile;}}
}
$('analyze-image').onclick=scheduleAnalysis;
$('apply-recommendation').onclick=()=>{if(recommendation&&!busy)applyProfile(recommendation.recommended_profile,recommendation.suggested_params);};
document.addEventListener('crop-change',scheduleAnalysis);
function showError(error){$('error').textContent=error.message||String(error);$('error').hidden=false;}
function clearError(){$('error').hidden=true;$('error').textContent='';}
const isBoolean=s=>s.type==='boolean'||typeof s.default==='boolean';
const tooltip=document.createElement('aside');tooltip.id='parameter-tooltip';tooltip.className='parameter-tooltip';tooltip.setAttribute('role','tooltip');tooltip.hidden=true;document.body.append(tooltip);
let helpAnchor=null,helpKey=null,helpPinned=false,helpTimer=null;
function hideHelp(){clearTimeout(helpTimer);tooltip.hidden=true;helpAnchor=null;helpKey=null;helpPinned=false;}
function placeHelp(){
 if(!helpAnchor||tooltip.hidden)return;const rect=helpAnchor.getBoundingClientRect(),margin=12,gap=12;
 tooltip.style.left='0px';tooltip.style.top='0px';const width=tooltip.offsetWidth,height=tooltip.offsetHeight;
 let left=rect.right+gap,top=rect.top;
 if(left+width>innerWidth-margin){left=Math.max(margin,Math.min(rect.left,innerWidth-width-margin));top=rect.bottom+gap;}
 tooltip.style.left=Math.max(margin,Math.min(left,innerWidth-width-margin))+'px';tooltip.style.top=Math.max(margin,Math.min(top,innerHeight-height-margin))+'px';
}
function showHelp(anchor,key){
 clearTimeout(helpTimer);if(helpPinned&&helpKey!==key)return;
 helpAnchor=anchor;helpKey=key;tooltip.replaceChildren();const title=document.createElement('strong');title.textContent=schema[key].label;tooltip.append(title);
 for(const text of (tips[key]||schema[key].label).split('\n')){const p=document.createElement('p');p.textContent=text;tooltip.append(p);}
 tooltip.hidden=false;placeHelp();
}
function scheduleHideHelp(){if(!helpPinned)helpTimer=setTimeout(hideHelp,180);}
function makeFieldLabel(key,s,boolean){
 const wrapper=document.createElement('div');wrapper.className='field-label';
 const heading=document.createElement('div');heading.className='field-heading';
 const label=document.createElement('label');label.htmlFor='opt-'+key;label.textContent=s.label;label.tabIndex=0;
 const help=document.createElement('button');help.type='button';help.className='parameter-help';help.textContent='?';help.setAttribute('aria-label',s.label+'：查看参数说明');
 const desc=document.createElement('span');desc.id='help-'+key;desc.className='sr-only';desc.textContent=tips[key]||s.label;
 label.setAttribute('aria-describedby',desc.id);help.setAttribute('aria-describedby',desc.id);
 for(const anchor of [label,help]){anchor.addEventListener('mouseenter',()=>showHelp(anchor,key));anchor.addEventListener('mouseleave',scheduleHideHelp);anchor.addEventListener('focus',()=>showHelp(anchor,key));anchor.addEventListener('blur',scheduleHideHelp);}
 help.addEventListener('click',()=>{if(helpPinned&&helpKey===key){hideHelp();return;}helpPinned=false;showHelp(help,key);helpPinned=true;});
 heading.append(label,help);const small=document.createElement('small');small.textContent=boolean?(tips[key]||'').split('\n')[0]:key+(s.min!==undefined?` · ${s.min}–${s.max}`:'');
 wrapper.append(heading,small,desc);return wrapper;
}
tooltip.addEventListener('mouseenter',()=>clearTimeout(helpTimer));tooltip.addEventListener('mouseleave',scheduleHideHelp);
document.addEventListener('keydown',e=>{if(e.key==='Escape')hideHelp();});
document.addEventListener('pointerdown',e=>{if(!e.target.closest('.field-heading')&&!tooltip.contains(e.target))hideHelp();});
window.addEventListener('resize',placeHelp);window.addEventListener('scroll',()=>{if(!helpAnchor)return;const r=helpAnchor.getBoundingClientRect();if(r.bottom<0||r.top>innerHeight)hideHelp();else placeHelp();},true);
function validateConfig(c){
 if(!c||Array.isArray(c)||typeof c!=='object')throw new Error('配置必须是 JSON 对象。');
 for(const[k,v]of Object.entries(c)){
  const s=schema[k];if(!s)throw new Error('未知配置项：'+k);
  if(k==='crop_ratio'){if(v!=='')cropEditor.terms(v);}
  else if(k==='crop_rect'){if(typeof v!=='string')throw new Error('裁剪选框必须为字符串。');if(cropEditor.validateRect)cropEditor.validateRect(v);}
  else if(isBoolean(s)){if(typeof v!=='boolean')throw new Error(s.label+' 必须为布尔值。');}
  else if(s.choices&&!s.choices.includes(v))throw new Error(s.label+' 的选项无效。');
  else if('min'in s&&(typeof v!=='number'||!Number.isFinite(v)||v<s.min||v>s.max||Math.abs(v/s.step-Math.round(v/s.step))>1e-7))throw new Error(s.label+' 超出范围或不符合步长。');
  else if((k==='output_directory'||k==='detail_region')&&typeof v!=='string')throw new Error(s.label+' 必须为字符串。');
 }
}
function normalizeImportedConfig(c){
 if(!c||Array.isArray(c)||typeof c!=='object')throw new Error('配置必须是 JSON 对象。');
 const own=key=>Object.prototype.hasOwnProperty.call(c,key);
 const retired=retiredEngineFields.some(own);
 if(c.engine==='vtracer'||(!own('engine')&&!own('illustration_profile')&&retired))throw new Error('VTracer 支持已移除，无法导入该配置。请使用 Potrace 插画方案重新设置。');
 const result={...c};
 if(c.engine==='potrace'||own('illustration_profile'))for(const key of retiredEngineFields)delete result[key];
 return result;
}
function getConfig(){
 const c={};for(const[key,s]of Object.entries(schema)){
  if(s.section==='crop')continue;
  if(s.engine&&s.engine!==$('opt-engine').value)continue;
  const el=$('opt-'+key);c[key]=isBoolean(s)?el.checked:('min'in s||typeof s.default==='number')?Number(el.value):el.value;
 }
 Object.assign(c,cropEditor.getConfig());
 validateConfig(c);if(c.highres_refine&&!c.sr_enabled)throw new Error('高分辨率补充优化需要先启用超分辨率预处理。');return c;
}
function setConfig(c){
 c=normalizeImportedConfig(c);
 validateConfig(c);
 const old=!Object.prototype.hasOwnProperty.call(c,'illustration_profile')&&('engine'in c||Object.keys(c).some(k=>schema[k].engine));
 const merged={...(old?legacyDefaults:defaults),...(!old?profilePresets[c.illustration_profile]:{}),...c};
 merged.engine='potrace';
 const layered=merged.engine==='potrace'&&['flat_layers','gradient_layers'].includes(merged.illustration_profile);
 if(merged.sr_enabled&&!Object.prototype.hasOwnProperty.call(c,'highres_refine'))merged.highres_refine=!layered;
 if(merged.highres_refine&&!merged.sr_enabled)throw new Error('高分辨率补充优化需要先启用超分辨率预处理。');
 if(layered&&(merged.diffvg_optimize||merged.highres_refine))throw new Error('分层方案暂不支持 DiffVG 或高分辨率补充优化，请关闭这两项。超分辨率预处理可用。');
 cropEditor.validateConfig(merged);
 const cropSnapshot=()=>JSON.stringify(['crop_ratio','crop_x','crop_y','crop_rect'].map(key=>$('opt-'+key).value));
 const previousCrop=cropSnapshot();
 for(const[k,v]of Object.entries(merged)){const el=$('opt-'+k);if(isBoolean(schema[k]))el.checked=v;else el.value=v;}
 cropEditor.syncPreset();
 warn();
 presetEditor.sync(merged);
 if(previousCrop!==cropSnapshot())scheduleAnalysis();
}
function updatePresetState(){try{presetEditor.sync(getConfig());}catch{presetEditor.markCustom();}}
function warn(){
 if(!schema)return;const sr=$('opt-sr_enabled')?.checked||false;
 const dependency={simplify_target_paths:$('opt-curve_simplify')?.checked||false,sr_scale:sr,curve_tolerance:$('opt-curve_simplify')?.checked||false,diffvg_optimize:!isLayered(),diffvg_iterations:!isLayered()&&($('opt-diffvg_optimize')?.checked||false),highres_refine:sr&&!isLayered(),potrace_opt_tolerance:$('opt-potrace_opt_curve')?.checked||false,potrace_detail_weight:!!$('opt-detail_region')?.value.trim()};
 for(const[k,s]of Object.entries(schema)){
  if(s.section==='crop'||k==='engine')continue;
  const el=$('opt-'+k),dependent=Object.prototype.hasOwnProperty.call(dependency,k)&&!dependency[k];
  el.disabled=busy||dependent;el.parentElement.classList.toggle('is-dependent-disabled',dependent);
 }
 if(!sr&&$('opt-highres_refine'))$('opt-highres_refine').checked=false;

 if(helpAnchor?.closest('.field')?.hidden||helpAnchor?.closest('.parameter-subgroup')?.hidden)hideHelp();

}
function setBusy(value){
 busy=value;document.querySelectorAll('#config input,#config select,#reset,#load-config,#save-config,#self-test').forEach(el=>el.disabled=value);
 $('stop').hidden=!conversionActive;$('stop').disabled=true;$('stop').textContent='停止';
 $('file').disabled=value;$('change-image').disabled=value;$('convert').disabled=value||!inputFile;$('preview-reference').disabled=value||!processedURL||!view.ready;warn();
 cropEditor.setBusy(value);presetEditor.setBusy(value);
 $('analyze-image').disabled=value||!inputFile||!!analysisRequest;$('apply-recommendation').disabled=value||!recommendation;
 if(value&&!analysisRequest&&!recommendation&&inputFile){clearTimeout(analysisTimer);$('recommendation-summary').textContent='转换完成后将分析图片，也可手动重新分析。';}
 if(!value&&!analysisRequest&&!recommendation&&inputFile)scheduleAnalysis();
 refineEditor.render();
}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}
function clearResult(){
 ++resultGeneration;refineEditor.reset();
 svgBlob=null;if(vectorURL)URL.revokeObjectURL(vectorURL);vectorURL=null;if(processedURL)URL.revokeObjectURL(processedURL);processedURL=null;processedScale=1;
 $('preview-reference').value='original';$('preview-reference').disabled=true;$('original-tag').textContent='原图';if(originalURL)$('original').src=originalURL;
 $('vector').hidden=true;$('vector').removeAttribute('src');$('download').disabled=true;$('download-preview').disabled=true;$('split').hidden=true;$('split').tabIndex=-1;$('split').setAttribute('aria-disabled','true');$('vector-tag').hidden=true;view.ready=false;renderView();$('result-stats').textContent='';$('pipeline-stats').textContent='';$('output-path').textContent='转换成功后自动保存，不覆盖已有文件。';
}
async function checkCapabilities(){
 try{const res=await fetch('/api/capabilities',{headers});if(!res.ok)throw new Error();const c=await res.json();
  $('enhancement-status').textContent=[['sr','超分辨率'],['diffvg','DiffVG / 高分补充']].map(([key,label])=>{
   const capability=c[key];if(!capability?.available)return `${label}：${capability?.reason||'运行环境未就绪'}`;
   if(key==='sr')return capability.backend==='cuda'?`${label}：GPU 优先（${capability.device}），不可用时自动回退 CPU`:`${label}：CPU（GPU 不可用时自动回退）`;
   return `${label}：已就绪（${capability.device||'CPU'}）`;
  }).join('\n');
 }catch{$('enhancement-status').textContent='暂时无法获取增强功能状态；Potrace 矢量化仍可使用。';}
}
async function start(){
 const res=await fetch('/api/schema',{headers});if(!res.ok)throw new Error('连接失败，请重新启动程序并使用完整地址。');({schema,defaults,legacy_defaults:legacyDefaults,profile_labels:profileLabels,profile_presets:profilePresets,retired_engine_fields:retiredEngineFields}=await res.json());
 const groups={};for(const[key,title,description]of [['preprocess','预处理','先处理输入图片，再生成矢量轮廓。'],['conversion','矢量化','选择插画重构方案并调整参数；悬停参数名称查看影响。'],['postprocess','后处理','可分别选择曲线简化、全图优化和高分辨率补充。'],['output','保存位置','']]){
  const group=document.createElement('fieldset');group.className='config-section';group.id='section-'+key;const legend=document.createElement('legend');legend.textContent=title;group.append(legend);
  if(description){const p=document.createElement('p');p.className='section-description';p.textContent=description;group.append(p);}groups[key]=group;$(key==='output'?'output-settings':'config').append(group);
 }
 const subgroups={};for(const[key,title]of [['potrace_trace','曲线描摹'],['potrace_regions','色块分区与边界']]){
  const group=document.createElement('div');group.id='group-'+key;group.className='parameter-subgroup';const heading=document.createElement('h3');heading.textContent=title;group.append(heading);subgroups[key]=group;
 }
 for(const[key,s]of Object.entries(schema)){
  if(s.section==='crop')continue;
  if(key==='engine'){const engine=document.createElement('input');engine.type='hidden';engine.id='opt-engine';engine.value='potrace';$('config').append(engine);continue;}
  const boolean=isBoolean(s),box=document.createElement('div');box.className='field'+(boolean||['engine','illustration_profile','output_directory','detail_region'].includes(key)?' wide':'')+(boolean?' boolean-field':'');
  const label=makeFieldLabel(key,s,boolean);
  const el=document.createElement(s.choices?'select':'input');el.id='opt-'+key;
  el.setAttribute('aria-describedby','help-'+key);
  if(boolean){el.type='checkbox';el.checked=s.default;}
  else if(s.choices){for(const v of s.choices){const op=document.createElement('option');op.value=v;op.textContent=key==='illustration_profile'?profileLabels[v]:key==='sr_scale'?v+'×':key==='potrace_turn_policy'?({minority:'minority · 少数优先',majority:'majority · 多数优先',black:'black · 前景优先',white:'white · 背景优先',left:'left · 左转',right:'right · 右转'}[v]):v;el.append(op);}}
  else if('min'in s){el.type='number';el.min=s.min;el.max=s.max;el.step=s.step;el.required=true;}
  else{el.type='text';el.placeholder=key==='detail_region'?'x,y,宽,高；留空表示全图均等':'留空使用系统临时目录';}
  if(!boolean)el.value=s.default;
  el.addEventListener('input',()=>{if(key==='illustration_profile'){try{applyProfile(el.value);}catch(e){showError(e);}}if(key==='sr_enabled'&&$('opt-highres_refine'))$('opt-highres_refine').checked=el.checked&&!isLayered();warn();updatePresetState();});
  if(boolean)box.append(el,label);else box.append(label,el);
  if(key==='illustration_profile')groups.conversion.insertBefore(box,groups.conversion.querySelector('.field'));
  else (subgroups[s.group]||groups[key==='output_directory'?'output':s.section]||groups.conversion).append(box);
 }
 for(const group of Object.values(subgroups))if(group.querySelector('.field'))groups.conversion.append(group);
 for(const group of Object.values(groups))if(!group.querySelector('.field'))group.hidden=true;
 cropEditor.init();warn();
 presetEditor.init({schema,defaults,profilePresets,getConfig,apply:setConfig,
  getPreserved:()=>({...cropEditor.getConfig(),output_directory:$('opt-output_directory').value}),
  status:text=>{$('status').textContent=text;},onError:showError,onAdvancedChange:()=>hideHelp()});
 checkCapabilities();
}
const stageNames={normalizing:'规范化输入图片',import_engine:'准备转换引擎',super_resolution:'超分辨率预处理',sr_start:'载入超分辨率模型',sr_inference:'超分辨率处理',sr_tiles:'超分辨率处理',convert:'矢量化',potrace_structure:'识别插画小图案',potrace_palette:'生成颜色分区',potrace_merge:'合并相邻色块',potrace_trace:'拟合矢量曲线',normalize_svg:'整理矢量坐标',curve_simplify:'简化曲线',postprocess_prepare:'准备全图优化',diffvg_prepare:'准备全图优化',optimization_start:'准备全图优化',diffvg_global:'DiffVG 全图优化',highres_refine:'高分辨率补充优化',enhancement_complete:'增强阶段完成',saving:'保存结果',complete:'转换完成'};
stageNames.sr_cpu_fallback='GPU 不可用，已回退 CPU 进行超分';
stageNames.region_simplify='简化相邻色块';stageNames.cancelling='正在停止计算进程…';
Object.assign(stageNames,{illustration_texture:'保边纹理平滑',illustration_regions:'构建插画色块',illustration_gradients:'检验并拟合渐变色面',illustration_lines:'检查重构误差并连接线条',illustration_residuals:'补充遗漏色块'});
Object.assign(stageNames,{refine_prepare:'准备局部精修',local_refine_prepare:'读取圈选区域',local_refine_regions:'重建局部颜色分区',local_refine_trace:'拟合局部矢量曲线',local_refine_complete:'合成局部候选',refine_complete:'局部候选完成'});
function progressDevice(p){
 if(p.stage==='potrace_trace'&&p.threads)return ` · ${p.threads} 线程`;
 if(!p.stage?.startsWith('sr_'))return '';
 return p.device==='cuda'?' · GPU':p.device==='cpu'?` · CPU${p.fallback_reason?'（已自动回退）':''}`:'';
}
function stopProgress(){progressGeneration++;if(progressTimer)clearTimeout(progressTimer);progressTimer=null;$('conversion-progress').hidden=true;}
function startProgress(){
 stopProgress();const generation=progressGeneration;$('conversion-progress').hidden=false;$('conversion-progress').removeAttribute('value');
 const poll=async()=>{try{const r=await fetch('/api/progress',{headers});if(r.ok){const p=await r.json();if(generation!==progressGeneration||!busy)return;if(conversionActive&&p.running&&!stopRequested)$('stop').disabled=false;if(!stopRequested&&p.running&&p.stage){let label=stageNames[p.stage]||'正在本机处理';const current=p.current??p.done,total=p.total;let suffix='';if(Number.isFinite(current)&&Number.isFinite(total)&&total>0){suffix=` · ${current.toLocaleString()} / ${total.toLocaleString()}`;$('conversion-progress').value=Math.max(0,Math.min(100,current/total*100));}else{$('conversion-progress').removeAttribute('value');if(p.regions&&p.limit)suffix=` · ${p.regions.toLocaleString()} 个区域 → 上限 ${p.limit.toLocaleString()}`;}$('status').textContent=label+progressDevice(p)+suffix+(typeof p.detail==='string'?' · '+p.detail:'');}}}catch{/* Conversion response retains the authoritative failure. */}if(generation===progressGeneration&&busy)progressTimer=setTimeout(poll,1000);};poll();
}
$('file').addEventListener('change',async()=>{if(!$('file').files[0])return;clearError();clearResult();inputFile=$('file').files[0];$('convert').disabled=!inputFile||busy;if(originalURL)URL.revokeObjectURL(originalURL);$('original').hidden=true;$('preview-empty').hidden=false;$('original-tag').hidden=true;enablePreview(false);if(inputFile.size>20*1024*1024){inputFile=null;cropEditor.setFile(null);scheduleAnalysis();$('convert').disabled=true;showError(new Error('文件超过 20 MiB。'));return;}cropEditor.setFile(inputFile);scheduleAnalysis();originalURL=URL.createObjectURL(inputFile);$('filename').textContent=`${inputFile.name} · ${(inputFile.size/1024).toFixed(1)} KiB`;$('status').textContent='已选择图片，可调整配置后转换。';try{await loadImage($('original'),originalURL);view.width=$('original').naturalWidth;view.height=$('original').naturalHeight;$('original').hidden=false;$('preview-empty').hidden=true;$('original-tag').hidden=false;enablePreview(true);fitView();}catch(e){showError(new Error('无法预览此格式，仍可尝试转换；转换成功后将显示标准化原图。'));}});
$('reset').onclick=()=>{clearError();setConfig(defaults);};
$('save-config').onclick=()=>{try{download(new Blob([JSON.stringify(getConfig(),null,2)],{type:'application/json'}),'image-vector-config.json');}catch(e){showError(e);}};
$('load-config').onclick=()=>$('config-file').click();
$('config-file').onchange=async()=>{clearError();try{const f=$('config-file').files[0];if(!f)return;if(f.size>65536)throw new Error('配置文件过大。');setConfig(JSON.parse((await f.text()).replace(/^\uFEFF/,'')));$('status').textContent='配置已导入。';}catch(e){showError(e);}finally{$('config-file').value='';}};
$('download-preview').onclick=()=>$('download').click();$('change-image').onclick=()=>$('file').click();
$('download').onclick=()=>{if(svgBlob)download(svgBlob,(inputFile?.name.replace(/\.[^.]+$/,'')||'image')+'.svg');};
$('preview-reference').onchange=async()=>{const processed=$('preview-reference').value==='processed';const url=processed?processedURL:originalURL;if(!url)return;try{await loadImage($('original'),url);$('original-tag').textContent=processed?`超分 ${processedScale}×`:'原图';$('original').alt=processed?'超分辨率预处理图':'原始位图';renderView();}catch(e){showError(e);}};
async function showVectorPreview(url,label,isCurrent=()=>true){
 const image=new Image();await loadImage(image,url);
 if(!isCurrent())return false;
 $('vector').src=url;$('vector-tag').textContent=label;renderView();return true;
}
function updateResultMetadata(result){
  $('output-path').textContent=result.path;
  if(result.stats){const s=result.stats,segments=s.total_segments??s.segments;$('result-stats').textContent=`Potrace · 绘制路径 ${(s.drawing_paths??s.paths).toLocaleString()}${result.refinement_count?'':` / 上限 ${result.config.path_limit.toLocaleString()}`} · 轮廓 ${(s.subpaths??s.contours).toLocaleString()}（含孔洞） · 总段数 ${segments.toLocaleString()}${s.curve_segments!==undefined?' · 曲线段 '+s.curve_segments.toLocaleString():''}${s.nodes!==undefined?' · 控制节点 '+s.nodes.toLocaleString():''}`;}
  const srReport=result.pipeline?.stages?.find(s=>s.stage==='super_resolution')?.report;
  const srDevice=srReport?.backend==='cuda'?`GPU · ${srReport.device}`:srReport?.backend==='cpu'?`CPU${srReport.fallback_reason?' · 已自动回退':''}`:'';
  const stages=[];if(result.config.crop_ratio||result.config.crop_rect)stages.push(`裁剪 ${result.config.crop_ratio||'自由比例'}（${result.width} × ${result.height}）`);if(result.config.sr_enabled)stages.push(`超分 ${result.config.sr_scale}×${srDevice?'（'+srDevice+'）':''}`);stages.push(profileLabels[result.config.illustration_profile]||'Potrace');if(result.stats?.gradient_count)stages.push(`${result.stats.gradient_count} 个渐变色面`);const reduced=result.pipeline?.stages?.find(s=>s.stage==='region_simplify')?.report;if(reduced)stages.push(`色块 ${reduced.before.fill_paths} → ${reduced.after.fill_paths}（目标上限 ${reduced.target}）`);if(result.config.curve_simplify)stages.push('曲线简化');if(result.config.diffvg_optimize)stages.push(`DiffVG ${result.config.diffvg_iterations} 轮`);if(result.config.highres_refine)stages.push('高分辨率补充');if(result.refinement_count)stages.push(`局部精修 ${result.refinement_count} 次`);$('pipeline-stats').textContent='已执行：'+stages.join(' → ');$('pipeline-stats').title=srReport?.fallback_reason||'';
}
function invalidateResultPreview(result){
 updateResultMetadata(result);
 svgBlob=null;if(vectorURL)URL.revokeObjectURL(vectorURL);vectorURL=null;
 $('vector').hidden=true;$('vector').removeAttribute('src');$('vector-tag').hidden=true;
 $('download').disabled=true;$('download-preview').disabled=true;
 view.ready=false;$('split').hidden=true;$('split').tabIndex=-1;renderView();
}
async function loadReturnedResult(result,{preserveView=false,isCurrent=()=>true}={}){
 const created=[];let committed=false;
 try{
  const svg=await fetch('/api/svg',{headers});if(!svg.ok)throw new Error('文件已保存，但读取预览失败。');
  const nextBlob=await svg.blob(),nextVector=URL.createObjectURL(nextBlob);created.push(nextVector);
  let nextOriginal=originalURL,nextProcessed=processedURL;
  if(!preserveView){
   const original=await fetch('/api/original',{headers});if(!original.ok)throw new Error('SVG 已保存，但标准化原图读取失败。');
   nextOriginal=URL.createObjectURL(await original.blob());created.push(nextOriginal);nextProcessed=null;
   if(result.processed_available){const processed=await fetch('/api/processed',{headers});if(!processed.ok)throw new Error('SVG 已保存，但预处理图读取失败。');nextProcessed=URL.createObjectURL(await processed.blob());created.push(nextProcessed);}
  }
  const readyVector=new Image(),readyReference=new Image();
  await Promise.all([loadImage(readyVector,nextVector),...(!preserveView?[loadImage(readyReference,nextProcessed||nextOriginal)]:[])]);
  if(!isCurrent())return false;
  if(vectorURL)URL.revokeObjectURL(vectorURL);vectorURL=nextVector;svgBlob=nextBlob;$('vector').src=nextVector;
  if(!preserveView){
   if(originalURL)URL.revokeObjectURL(originalURL);if(processedURL)URL.revokeObjectURL(processedURL);
   originalURL=nextOriginal;processedURL=nextProcessed;processedScale=result.config.sr_scale||1;
   $('preview-reference').value=processedURL?'processed':'original';$('original').src=processedURL||originalURL;
   $('original-tag').textContent=processedURL?`超分 ${processedScale}×`:'原图';$('original').alt=processedURL?'超分辨率预处理图':'原始位图';view.split=.5;
  }
  committed=true;view.width=result.width||readyVector.naturalWidth;view.height=result.height||readyVector.naturalHeight;view.ready=true;
  $('original').hidden=false;$('vector').hidden=false;$('preview-empty').hidden=true;$('original-tag').hidden=false;
  $('vector-tag').hidden=false;$('vector-tag').textContent='矢量';$('split').hidden=false;$('split').tabIndex=0;$('split').setAttribute('aria-disabled','false');
  $('download').disabled=false;$('download-preview').disabled=false;enablePreview(true);
  updateResultMetadata(result);
  if(preserveView)renderView();else fitView();return true;
 }finally{if(!committed)for(const url of created)URL.revokeObjectURL(url);}
}
$('convert').onclick=async()=>{
 if(!inputFile||busy)return;clearError();let config;try{config=getConfig();}catch(e){showError(e);return;}
 conversionActive=true;stopRequested=false;setBusy(true);clearResult();$('convert').textContent='正在转换…';const epoch=resultGeneration;$('status').textContent='正在本机处理，请稍候。超分辨率与优化可能需要较长时间。';startProgress();
 try{
  const file=inputFile,image=await fileBase64(file);
  const res=await fetch('/api/convert',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({image,name:file.name,config})});const result=await res.json();if(!res.ok)throw new Error(result.error||'转换失败。');stopProgress();
  if(result.cancelled){$('status').textContent='已停止当前任务。配置已保留，可修改参数后重新生成。';return;}
  if(await loadReturnedResult(result,{isCurrent:()=>epoch===resultGeneration})){refineEditor.setResult(result);$('status').textContent=`转换成功 · ${(result.bytes/1024).toFixed(1)} KiB · 文件已保存。`;}
 }catch(e){showError(e);$('status').textContent='本次转换未完成，请查看错误信息。';}
 finally{stopProgress();conversionActive=false;setBusy(false);$('convert').textContent='转换为 SVG';}
};

$('stop').onclick=async()=>{
 if(!conversionActive||stopRequested)return;
 stopRequested=true;$('stop').disabled=true;$('stop').textContent='正在停止…';$('status').textContent='正在停止计算进程，请稍候…';
 try{
  const res=await fetch('/api/cancel',{method:'POST',headers});const result=await res.json();
  if(!res.ok)throw new Error(result.error||'停止请求失败。');
  if(conversionActive&&!result.accepted)$('status').textContent='任务已进入保存阶段或已经结束，请等待结果。';
 }catch(e){if(conversionActive){stopRequested=false;$('stop').disabled=false;$('stop').textContent='停止';showError(e);}}
};

// Image coordinates are mapped once to the viewport; the split only clips layers.
const view={width:0,height:0,scale:1,x:0,y:0,split:.5,ready:false};
const clamp=(v,min,max)=>Math.min(max,Math.max(min,v));
const viewport=$('viewport');
function loadImage(el,url){return new Promise((resolve,reject)=>{el.onload=()=>resolve(el);el.onerror=()=>reject(new Error('预览图片加载失败。'));el.src=url;});}
function enablePreview(enabled){document.querySelectorAll('[data-preview]').forEach(el=>el.disabled=!enabled);}
function renderView(){const transform=`translate(${view.x}px,${view.y}px) scale(${view.scale})`;for(const id of ['original','vector']){const el=$(id);el.style.width=view.width+'px';el.style.height=view.height+'px';el.style.transform=transform;}$('original-layer').style.clipPath=view.ready?`inset(0 ${(1-view.split)*100}% 0 0)`:'none';$('vector-layer').style.clipPath=`inset(0 0 0 ${view.split*100}%)`;$('split').style.left=(view.split*100)+'%';$('split').setAttribute('aria-valuenow',Math.round(view.split*100));const label=$('preview-reference').value==='processed'?'预处理图':'原图';$('split').setAttribute('aria-valuetext',`${label} ${Math.round(view.split*100)}%，矢量 ${100-Math.round(view.split*100)}%`);$('zoom-value').textContent=(view.scale*100).toFixed(view.scale<.1?1:0)+'%';$('dimensions').textContent=view.width?`${view.width} × ${view.height} px`:'等待图片';refineEditor.render();}
function fitView(){if(!view.width||refineEditor.isDrawing())return;view.scale=Math.min(viewport.clientWidth/view.width,viewport.clientHeight/view.height)*.96;view.x=(viewport.clientWidth-view.width*view.scale)/2;view.y=(viewport.clientHeight-view.height*view.scale)/2;renderView();}
function zoomAt(next,px=viewport.clientWidth/2,py=viewport.clientHeight/2){if(!view.width||refineEditor.isDrawing())return;next=clamp(next,.001,64);const ratio=next/view.scale;view.x=px-(px-view.x)*ratio;view.y=py-(py-view.y)*ratio;view.scale=next;renderView();}
$('zoom-in').onclick=()=>zoomAt(view.scale*1.25);$('zoom-out').onclick=()=>zoomAt(view.scale/1.25);$('fit').onclick=fitView;$('actual').onclick=()=>zoomAt(1);
$('background').onchange=()=>{viewport.dataset.background=$('background').value;};
$('fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await $('comparison-card').requestFullscreen();}catch(e){showError(new Error('当前浏览器不允许全屏；可使用浏览器窗口最大化。'));}};
document.addEventListener('fullscreenchange',()=>{$('fullscreen').textContent=document.fullscreenElement?'⛶ 退出全屏':'⛶ 全屏';});
viewport.addEventListener('wheel',e=>{if(!view.width)return;e.preventDefault();const rect=viewport.getBoundingClientRect();zoomAt(view.scale*Math.exp(-e.deltaY*.002),e.clientX-rect.left,e.clientY-rect.top);},{passive:false});
let splitPointer=null;
function setSplitAt(clientX){const r=viewport.getBoundingClientRect();view.split=clamp((clientX-r.left)/r.width,0,1);renderView();}
$('split').addEventListener('pointerdown',e=>{if(!view.ready||refineEditor.isDrawing())return;e.preventDefault();e.stopPropagation();splitPointer=e.pointerId;$('split').setPointerCapture(e.pointerId);$('split').focus();setSplitAt(e.clientX);});
$('split').addEventListener('pointermove',e=>{if(e.pointerId===splitPointer)setSplitAt(e.clientX);});
for(const type of ['pointerup','pointercancel','lostpointercapture'])$('split').addEventListener(type,()=>{splitPointer=null;});
$('split').addEventListener('keydown',e=>{if(refineEditor.isDrawing())return;let next=view.split;const step=e.shiftKey?.1:.01;if(e.key==='ArrowLeft'||e.key==='ArrowDown')next-=step;else if(e.key==='ArrowRight'||e.key==='ArrowUp')next+=step;else if(e.key==='Home')next=0;else if(e.key==='End')next=1;else return;e.preventDefault();e.stopPropagation();view.split=clamp(next,0,1);renderView();});
const pointers=new Map();let gesture=null;
function pointerSnapshot(){const p=[...pointers.values()];if(p.length>=2)return{x:(p[0].x+p[1].x)/2,y:(p[0].y+p[1].y)/2,distance:Math.hypot(p[1].x-p[0].x,p[1].y-p[0].y)};return p.length?{...p[0],distance:0}:null;}
viewport.addEventListener('pointerdown',e=>{if(!view.width||refineEditor.isDrawing()||e.button!==0||e.target.closest('#split'))return;e.preventDefault();viewport.setPointerCapture(e.pointerId);pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});gesture=pointerSnapshot();viewport.classList.add('panning');});
viewport.addEventListener('pointermove',e=>{if(!pointers.has(e.pointerId))return;pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});const next=pointerSnapshot();if(gesture){view.x+=next.x-gesture.x;view.y+=next.y-gesture.y;if(next.distance&&gesture.distance){const rect=viewport.getBoundingClientRect();zoomAt(view.scale*next.distance/gesture.distance,next.x-rect.left,next.y-rect.top);}else renderView();}gesture=next;});
for(const type of ['pointerup','pointercancel','lostpointercapture'])viewport.addEventListener(type,e=>{pointers.delete(e.pointerId);gesture=pointerSnapshot();if(!pointers.size)viewport.classList.remove('panning');});
viewport.addEventListener('keydown',e=>{if(e.target!==viewport||!view.width)return;if(e.key==='+'||e.key==='=')zoomAt(view.scale*1.25);else if(e.key==='-')zoomAt(view.scale/1.25);else if(e.key==='0')fitView();else if(e.key==='1')zoomAt(1);else return;e.preventDefault();});
let previousSize=null;new ResizeObserver(()=>{const size={w:viewport.clientWidth,h:viewport.clientHeight};if(previousSize&&view.width){view.x+=(size.w-previousSize.w)/2;view.y+=(size.h-previousSize.h)/2;renderView();}previousSize=size;}).observe(viewport);
refineEditor.init({loadResult:loadReturnedResult,showVector:showVectorPreview,invalidatePreview:invalidateResultPreview,beginTask(cancellable){conversionActive=cancellable;stopRequested=false;setBusy(true);if(cancellable)startProgress();},endTask(){stopProgress();conversionActive=false;setBusy(false);}});
start().catch(showError);

$('self-test').onclick=async()=>{if(busy)return;clearError();setBusy(true);$('status').textContent='正在检查 Potrace 转换与路径约束…';try{const response=await fetch('/api/self-test',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:'{}'});const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||'本机引擎检查未通过。');$('status').textContent='引擎检查通过 · Potrace 转换正常。';}catch(e){showError(e);$('status').textContent='引擎检查未通过；请复制上方错误信息。';}finally{setBusy(false);}};
