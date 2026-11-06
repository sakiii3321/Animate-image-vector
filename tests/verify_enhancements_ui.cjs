// Actual browser + actual local HTTP conversion. No mocked conversion results.
const {chromium}=require('./node_test_dependencies.cjs')('playwright', __filename);
const sharp=require('../runtime/potrace/node_modules/sharp');
const {spawn}=require('child_process');const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..'),controlsOnly=process.argv.includes('--controls-only'),out=path.join(root,'outputs/code-review-20261107/ui-legacy/enhancements');
fs.mkdirSync(out,{recursive:true});const work=fs.mkdtempSync(path.join(out,'run-'));
process.env.TEMP=work;process.env.TMP=work;
(async()=>{
 const source=path.join(work,'enhancements-input.png');
 await sharp(Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="32" viewBox="0 0 80 64"><rect width="80" height="64" fill="#e4ece4"/><path d="M8 49L19 10L37 24L46 8L69 51Z" fill="#27637a"/><circle cx="41" cy="36" r="12" fill="#e9b768"/><circle cx="44" cy="32" r="3" fill="white"/></svg>')).png().toFile(source);
 const child=spawn(path.join(root,'runtime/python.exe'),['-u','app/main.py','--no-browser'],{cwd:root,windowsHide:true,env:{...process.env,TEMP:work,TMP:work,PYTHONUTF8:'1'}});
 let browser;const errors=[],progressStages=new Set(),conversions=[];let stderr='';child.stderr.on('data',b=>stderr+=b.toString());
 try{
  const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(new Error('Server startup timed out: '+stderr)),20000);child.stdout.on('data',buf=>{text+=buf.toString();const m=text.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[\w-]+/);if(m){clearTimeout(timer);resolve(m[0]);}});child.on('error',reject);child.on('exit',code=>{if(code)reject(new Error('Server exit '+code+': '+stderr));});});
  browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu'],downloadsPath:work});
  const page=await browser.newPage({viewport:{width:1500,height:1100},acceptDownloads:true});page.on('pageerror',e=>errors.push(e.message));
  page.on('response',async r=>{if(r.url().endsWith('/api/progress')&&r.ok()){try{const p=await r.json();if(p.running)progressStages.add(p.stage);}catch{}}});
  await page.goto(url);await page.waitForSelector('#opt-sr_enabled',{state:'attached'});await page.check('#advanced-mode');
  const checked=id=>page.locator('#opt-'+id).isChecked(),disabled=id=>page.locator('#opt-'+id).isDisabled();
  assert.equal(await checked('sr_enabled'),false);assert.equal(await disabled('sr_scale'),true);assert.equal(await disabled('highres_refine'),true);assert.equal(await checked('highres_refine'),false);
  await page.check('#opt-sr_enabled');assert.equal(await checked('highres_refine'),true);assert.equal(await disabled('highres_refine'),false);assert.equal(await disabled('sr_scale'),false);
  assert.equal(await checked('diffvg_optimize'),false,'SR refinement must not force full-frame DiffVG');
  await page.uncheck('#opt-highres_refine');await page.selectOption('#opt-sr_scale','4');assert.equal(await checked('highres_refine'),false,'Scale change preserves manual opt-out');
  await page.uncheck('#opt-sr_enabled');assert.equal(await disabled('highres_refine'),true);assert.equal(await checked('highres_refine'),false);
  await page.check('#opt-sr_enabled');assert.equal(await checked('highres_refine'),true);
  await page.check('#opt-curve_simplify');await page.locator('#opt-curve_tolerance').fill('0.6');await page.check('#opt-diffvg_optimize');await page.locator('#opt-diffvg_iterations').fill('1');
  await page.uncheck('#opt-sr_enabled');assert.equal(await checked('curve_simplify'),true);assert.equal(await checked('diffvg_optimize'),true);assert.equal(await disabled('curve_tolerance'),false);assert.equal(await disabled('diffvg_iterations'),false);
  assert.equal(await page.inputValue('#opt-engine'),'potrace');const downloadPromise=page.waitForEvent('download');await page.click('#save-config');const download=await downloadPromise;const exported=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
  assert.equal(exported.sr_enabled,false);assert.equal(exported.sr_scale,4);assert.equal(exported.curve_simplify,true);assert.equal(exported.curve_tolerance,.6);assert.equal(exported.diffvg_optimize,true);assert.equal(exported.diffvg_iterations,1);assert.equal(exported.highres_refine,false);assert.equal(exported.colormode,undefined);
  async function importConfig(config){await page.evaluate(()=>document.getElementById('status').textContent='importing');await page.locator('#config-file').setInputFiles({name:'enhancement.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});await page.waitForFunction(()=>document.getElementById('status').textContent==='配置已导入。');}
  await importConfig({sr_enabled:true,sr_scale:2});assert.equal(await checked('highres_refine'),true);
  await importConfig({sr_enabled:true,sr_scale:4,highres_refine:false});assert.equal(await checked('highres_refine'),false);assert.equal(await page.locator('#opt-sr_scale').inputValue(),'4');
  await importConfig({engine:'potrace'});assert.equal(await checked('sr_enabled'),false);assert.equal(await disabled('highres_refine'),true);assert.equal(await checked('curve_simplify'),false);assert.equal(await checked('diffvg_optimize'),false);assert.equal(await page.locator('#opt-mode').count(),0);
  await page.locator('#config-file').setInputFiles({name:'invalid.json',mimeType:'application/json',buffer:Buffer.from('{"sr_enabled":"true"}')});await page.waitForSelector('#error:not([hidden])');assert((await page.locator('#error').innerText()).includes('布尔'));assert.equal(await checked('sr_enabled'),false);
  await page.locator('#file').setInputFiles(source);
  async function convert(config){await importConfig(config);const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/convert')&&r.request().method()==='POST',{timeout:180000});await page.click('#convert');const response=await responsePromise,result=await response.json();assert(response.ok(),JSON.stringify(result));await page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('转换成功'),{},{timeout:30000});await page.locator('#vector').evaluate(i=>i.decode());assert(fs.existsSync(result.path));conversions.push({config:result.config,width:result.width,height:result.height,stats:result.stats,processed_available:result.processed_available});return result;}
  const basic={engine:'potrace',path_limit:12,output_directory:work};
  let result=await convert(basic);assert.equal(result.processed_available,false);assert.equal(await page.locator('#preview-reference').isDisabled(),true);assert(result.stats.paths<=12);
  if(!controlsOnly){
   const capabilities=await page.evaluate(async()=>{const r=await fetch('/api/capabilities',{headers:{'X-App-Token':new URLSearchParams(location.search).get('token')}});return r.json();});assert(capabilities.sr.available,JSON.stringify(capabilities.sr));assert(capabilities.diffvg.available,JSON.stringify(capabilities.diffvg));
   result=await convert({...basic,sr_enabled:true,sr_scale:2,highres_refine:false});assert.equal(result.processed_available,true);assert.equal(await page.locator('#preview-reference').inputValue(),'processed');assert.equal(await page.locator('#preview-reference').isDisabled(),false);
   let state=await page.locator('#original').evaluate(i=>({natural:i.naturalWidth,css:i.style.width,transform:i.style.transform}));assert.equal(state.natural,80);assert.equal(state.css,'40px');
   await page.selectOption('#preview-reference','original');await page.waitForFunction(()=>document.getElementById('original').naturalWidth===40);assert.equal(await page.locator('#original').evaluate(i=>i.style.transform),state.transform);
   await page.selectOption('#preview-reference','processed');await page.waitForFunction(()=>document.getElementById('original').naturalWidth===80);
   result=await convert({...basic,sr_enabled:true,sr_scale:2,curve_simplify:true,curve_tolerance:.3,diffvg_optimize:true,diffvg_iterations:1,highres_refine:true});assert.equal(result.processed_available,true);assert(result.stats.paths<=12);assert(result.stats.total_segments>=0);assert((await page.locator('#pipeline-stats').innerText()).includes('高分辨率补充'));
   await page.screenshot({path:path.join(out,'enhancements-ui.png'),fullPage:true});
   await page.click('#reset');assert.equal(await checked('sr_enabled'),false);assert.equal(await disabled('highres_refine'),true);
   result=await convert({output_directory:basic.output_directory});assert.equal(result.config.engine,'potrace');assert.equal(result.config.illustration_profile,'edge_clean');assert.equal(result.processed_available,false);assert.equal(await page.locator('#preview-reference').isDisabled(),true);assert.equal(await page.locator('#original').evaluate(i=>i.naturalWidth),40);
  }else await page.screenshot({path:path.join(out,'enhancements-controls.png'),fullPage:true});
  await page.setViewportSize({width:760,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.deepEqual(errors,[]);assert(progressStages.size>0,'Expected actual progress polling');
  const report={ok:true,controlsOnly,errors,progressStages:[...progressStages],conversions,checks:['SR dependent defaults','manual opt-out persists when scale changes','disable SR clears refinement','non-SR postprocessing remains selectable','typed config import/export','legacy config','invalid boolean','real conversion',...(!controlsOnly?['preview coordinates']:[]),'progress polling','mobile layout']};
  fs.writeFileSync(path.join(out,controlsOnly?'controls-results.json':'results.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{if(browser)await browser.close();if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.kill();});const target=path.resolve(work);assert.equal(path.dirname(target),path.resolve(out));assert(path.basename(target).startsWith('run-'));fs.rmSync(target,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
