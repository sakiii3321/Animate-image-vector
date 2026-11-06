// Actual Chrome, real HTTP configuration and real non-default Potrace conversion.
const {chromium}=require('./node_test_dependencies.cjs')('playwright', __filename);
const sharp=require('../runtime/potrace/node_modules/sharp');
const {spawn}=require('child_process');
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..'),out=path.join(root,'outputs/code-review-20261107/ui-legacy/tooltips');
fs.mkdirSync(out,{recursive:true});const work=fs.mkdtempSync(path.join(out,'run-'));
process.env.TEMP=work;process.env.TMP=work;
(async()=>{
 const source=path.join(work,'parameters-input.png');
 await sharp(Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="64"><rect width="80" height="64" fill="#eee5d5"/><path d="M7 52L20 10L35 26L44 8L72 53Z" fill="#306a89"/><circle cx="42" cy="38" r="12" fill="#e9b458"/><circle cx="46" cy="34" r="3" fill="white"/></svg>')).png().toFile(source);
 const child=spawn(path.join(root,'runtime/python.exe'),['-u','app/main.py','--no-browser'],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
 let browser,stderr='';const errors=[],checks=[];child.stderr.on('data',b=>stderr+=b.toString());
 try{
  const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(new Error('Startup timeout: '+stderr)),20000);child.stdout.on('data',b=>{text+=b.toString();const m=text.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[\w-]+/);if(m){clearTimeout(timer);resolve(m[0]);}});child.on('error',reject);});
  browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu'],downloadsPath:process.env.TEMP});
  const page=await browser.newPage({viewport:{width:1500,height:1000},acceptDownloads:true});page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.waitForSelector('#opt-potrace_alpha_max',{state:'attached'});await page.check('#advanced-mode');
  const tooltip=page.locator('#parameter-tooltip');
  assert.equal(await page.locator('#opt-engine').isVisible(),false);
  const newKeys=['potrace_trace_threads','potrace_alpha_max','potrace_opt_tolerance','potrace_opt_curve','potrace_turn_policy','potrace_turd_size','potrace_palette_colors','potrace_smoothing','potrace_min_region_area','potrace_detail_weight','potrace_stroke_width'];
  for(const key of newKeys){
   assert(await page.locator('#opt-'+key).isVisible(),key);
   await page.locator(`label[for="opt-${key}"]`).hover();await tooltip.waitFor({state:'visible'});
   assert((await tooltip.innerText()).length>80,key+' should have detailed help');assert(await tooltip.locator('p').count()>=2);
  }
  checks.push('Detailed hover help for all Potrace parameters');
  await page.locator('label[for="opt-potrace_alpha_max"]').focus();await tooltip.waitFor({state:'visible'});assert((await tooltip.innerText()).includes('保留更多尖角'));
  await page.keyboard.press('Escape');await tooltip.waitFor({state:'hidden'});checks.push('Keyboard focus and Escape');
  assert.equal(await page.locator('#opt-corner_threshold').count(),0);assert.equal(await page.locator('#opt-potrace_detail_weight').isDisabled(),true);
  await page.uncheck('#opt-potrace_opt_curve');assert.equal(await page.locator('#opt-potrace_opt_tolerance').isDisabled(),true);
  await page.check('#opt-potrace_opt_curve');assert.equal(await page.locator('#opt-potrace_opt_tolerance').isDisabled(),false);
  await page.fill('#opt-detail_region','10,10,30,30');assert.equal(await page.locator('#opt-potrace_detail_weight').isDisabled(),false);
  checks.push('Potrace parameter sections and dependencies');
  await page.check('#opt-sr_enabled');assert(await page.isChecked('#opt-highres_refine'));
  await page.uncheck('#opt-highres_refine');await page.selectOption('#opt-sr_scale','4');assert.equal(await page.isChecked('#opt-highres_refine'),false);
  await page.uncheck('#opt-sr_enabled');assert.equal(await page.locator('#opt-highres_refine').isDisabled(),true);checks.push('Existing SR/refinement dependency preserved');
  async function importConfig(config){await page.evaluate(()=>document.getElementById('status').textContent='importing');await page.locator('#config-file').setInputFiles({name:'parameters.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});await page.waitForFunction(()=>document.getElementById('status').textContent==='配置已导入。');}
  const config={engine:'potrace',path_limit:12,potrace_trace_threads:4,detail_region:'10,10,30,30',potrace_alpha_max:.6,potrace_opt_tolerance:.15,potrace_opt_curve:true,potrace_turn_policy:'white',potrace_turd_size:0,potrace_palette_colors:16,potrace_smoothing:.5,potrace_min_region_area:2,potrace_detail_weight:8,potrace_stroke_width:.5,output_directory:work};
  await importConfig(config);for(const key of newKeys){const el=page.locator('#opt-'+key);assert.equal(typeof config[key]==='boolean'?await el.isChecked():await el.inputValue(),typeof config[key]==='boolean'?config[key]:String(config[key]));}
  const downloadPromise=page.waitForEvent('download');await page.click('#save-config');const download=await downloadPromise;const exported=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
  for(const key of Object.keys(config))assert.deepEqual(exported[key],config[key]);assert.equal(exported.colormode,undefined);checks.push('Typed new-parameter JSON import/export including 0.05 step');
  await page.locator('#file').setInputFiles(source);const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/convert')&&r.request().method()==='POST',{timeout:180000});await page.click('#convert');const response=await responsePromise,result=await response.json();assert(response.ok(),JSON.stringify(result));
  await page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('转换成功'));await page.locator('#vector').evaluate(el=>el.decode());assert(fs.existsSync(result.path));assert(result.stats.paths<=12);for(const key of Object.keys(config))assert.deepEqual(result.config[key],config[key]);checks.push('Real non-default Potrace conversion and SVG preview');
  await page.locator('label[for="opt-potrace_alpha_max"]').hover();await tooltip.waitFor({state:'visible'});await page.screenshot({path:path.join(out,'parameter-tooltip-potrace.png')});
  await importConfig({engine:'potrace',path_limit:8});assert.equal(await page.inputValue('#opt-potrace_trace_threads'),'0');assert.equal(await page.inputValue('#opt-potrace_alpha_max'),'1');assert.equal(await page.inputValue('#opt-potrace_opt_tolerance'),'0.4');assert.equal(await page.inputValue('#opt-potrace_palette_colors'),'48');assert(await page.isChecked('#opt-potrace_opt_curve'));checks.push('Old Potrace configuration receives original defaults');
  await page.setViewportSize({width:390,height:844});const help=page.locator('label[for="opt-potrace_turn_policy"]').locator('..').locator('button');await help.click();await tooltip.waitFor({state:'visible'});
  const bounds=await tooltip.boundingBox();assert(bounds.x>=0&&bounds.y>=0&&bounds.x+bounds.width<=391&&bounds.y+bounds.height<=845,JSON.stringify(bounds));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.join(out,'parameter-tooltip-mobile.png')});await page.keyboard.press('Escape');await tooltip.waitFor({state:'hidden'});checks.push('Click help on narrow viewport without overflow');
  assert.deepEqual(errors,[]);const report={ok:true,checks,errors,conversion:{config:result.config,stats:result.stats,path:result.path},mobileTooltip:bounds};fs.writeFileSync(path.join(out,'parameter-tooltips-ui-results.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{if(browser)await browser.close();if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.kill();});const target=path.resolve(work);assert.equal(path.dirname(target),path.resolve(out));assert(path.basename(target).startsWith('run-'));fs.rmSync(target,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
