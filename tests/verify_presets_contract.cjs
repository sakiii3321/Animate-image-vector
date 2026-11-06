// Run actual preset/configuration functions against the current backend schema.
const assert=require('assert'),fs=require('fs'),path=require('path'),vm=require('vm'),{spawnSync}=require('child_process');
const root=path.resolve(__dirname,'..');
const metadata=spawnSync(path.join(root,'runtime/python.exe'),['-c',"import sys,json;sys.path.insert(0,'app');from core import SCHEMA,DEFAULTS,LEGACY_DEFAULTS,RETIRED_ENGINE_FIELDS;from illustration_profiles import PROFILE_PRESETS,PROFILE_LABELS;print(json.dumps(dict(schema=SCHEMA,defaults=DEFAULTS,legacyDefaults=LEGACY_DEFAULTS,retiredEngineFields=sorted(RETIRED_ENGINE_FIELDS),profilePresets=PROFILE_PRESETS,profileLabels=PROFILE_LABELS)))"],{cwd:root,encoding:'utf8'});
assert.equal(metadata.status,0,metadata.stderr);const data=JSON.parse(metadata.stdout);
class Element{
 constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};this.classList={toggle(){}};this.attributes={};this.value='';this.checked=false;}
 append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}setAttribute(key,value){this.attributes[key]=value;}
 querySelectorAll(selector){const all=this.children.flatMap(child=>[child,...child.querySelectorAll('*')]);return all.filter(child=>selector==='*'||selector==='button'&&child.tag==='button'||selector==='[data-preset]'&&child.dataset.preset);}
}
const elements={},el=id=>elements[id]??=new Element();
const document={getElementById:el,createElement:tag=>new Element(tag)};
for(const[key,value]of Object.entries(data.defaults)){el('opt-'+key).value=value;el('opt-'+key).checked=value;}
const isBoolean=spec=>spec.type==='boolean'||typeof spec.default==='boolean';
const cropEditor={getConfig:()=>Object.fromEntries(Object.entries(data.schema).filter(([,spec])=>spec.section==='crop').map(([key,spec])=>[key,typeof spec.default==='number'?Number(el('opt-'+key).value):el('opt-'+key).value])),terms(){},validateRect(){},validateConfig(config){return config;},syncPreset(){}};
const context={document,...data,$:el,cropEditor,isBoolean,warn(){},scheduleAnalysis(){},hideHelp(){},showError:error=>{throw error;}};vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,'app/presets.js'),'utf8')+'\nglobalThis.editor=presetEditor;',context);
const app=fs.readFileSync(path.join(root,'app/app.js'),'utf8');
vm.runInContext(app.slice(app.indexOf('function validateConfig('),app.indexOf('function warn(')),context);
vm.runInContext(app.slice(app.indexOf('function applyProfile('),app.indexOf('function scheduleAnalysis(')),context);
const editor=context.editor;
editor.init({...data,getConfig:context.getConfig,apply:context.setConfig,getPreserved:()=>({...cropEditor.getConfig(),output_directory:el('opt-output_directory').value}),status(){},onError:error=>{throw error;}});
assert.equal(el('preset-summary').dataset.preset,'balanced');assert(el('advanced-settings').hidden);assert.equal(el('preset-grid').children.length,5);
const crop={crop_ratio:'1:1',crop_x:20,crop_y:60,...('crop_rect'in data.schema?{crop_rect:'10,20,100,100'}:{})};
context.setConfig({...data.defaults,...crop,output_directory:'custom-output',sr_enabled:true,sr_scale:4,diffvg_optimize:true,highres_refine:true,detail_region:'20,20,10,10'});
for(const[id,budget,palette,tolerance]of [['balanced',2000,100,.3],['detail',4000,160,.2],['compact',800,64,.5],['gradient',2000,64,.3],['line_art',1500,64,.2]]){
 editor.choose(id);const c=context.getConfig();context.validateConfig(c);
 assert.equal(c.path_limit,budget);assert.equal(c.potrace_palette_colors,palette);assert.equal(c.curve_tolerance,tolerance);assert.equal(c.output_directory,'custom-output');
 for(const[key,value]of Object.entries(crop))assert.equal(c[key],value);
 assert.equal(c.sr_enabled,false);assert.equal(c.sr_scale,2);assert.equal(c.diffvg_optimize,false);assert.equal(c.highres_refine,false);assert.equal(c.detail_region,'');assert.equal(el('preset-summary').dataset.preset,id);
}
context.setConfig({engine:'potrace',path_limit:77,mode:'polygon',color_precision:7,...crop,output_directory:'import-output'});
assert.equal(context.getConfig().illustration_profile,'legacy');assert.equal(context.getConfig().path_limit,77);assert.equal(el('preset-summary').dataset.preset,'custom');
assert.equal(context.getConfig().mode,undefined);assert(el('advanced-settings').hidden,'custom import should not silently switch modes');
context.applyProfile('edge_clean',{path_limit:3000});assert.equal(el('preset-summary').dataset.preset,'custom');assert.equal(context.getConfig().output_directory,'import-output');
for(const[key,value]of Object.entries(crop))assert.equal(context.getConfig()[key],value,'recommendation retains crop');
editor.choose('balanced');el('opt-path_limit').value=2456;context.updatePresetState();assert.equal(el('preset-summary').dataset.preset,'custom');
el('opt-path_limit').value=0;context.updatePresetState();assert.equal(el('preset-summary').dataset.preset,'custom');
editor.setAdvanced(true);assert.equal(el('advanced-settings').hidden,false);
editor.setBusy(true);assert(el('preset-grid').children.every(button=>button.disabled));const before=el('opt-path_limit').value;editor.choose('detail');assert.equal(el('opt-path_limit').value,before);
assert.throws(()=>context.setConfig({engine:'vtracer'}),/VTracer 支持已移除/);
console.log('Preset contracts passed: backend-valid values, deterministic enhancements, crop/output preservation, legacy imports, recommendations, custom and busy states.');
