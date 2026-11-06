// Application UI regression against a real local server; no report-file preview.
const {chromium}=require('./node_test_dependencies.cjs')('playwright', __filename);
const {spawn}=require('child_process');
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..'),out=path.join(root,'outputs/ui-redesign-study/profile-regression');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const child=spawn(path.join(root,'runtime/python.exe'),['-u','app/main.py','--no-browser'],{cwd:root,windowsHide:true,env:{...process.env,TEMP:path.join(root,'.diagnostic-temp'),TMP:path.join(root,'.diagnostic-temp'),PYTHONUTF8:'1'}});
 let browser;const errors=[],checks=[];let stderr='';child.stderr.on('data',b=>stderr+=b);
 try{
  const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(new Error('startup timeout')),20000);child.stdout.on('data',b=>{text+=b;const m=text.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[\w-]+/);if(m){clearTimeout(timer);resolve(m[0]);}});child.on('error',reject);});
  browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu']});
  const page=await browser.newPage({viewport:{width:1500,height:1100}});page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.waitForSelector('#opt-illustration_profile',{state:'attached'});await page.check('#advanced-mode');
  assert.equal(await page.inputValue('#opt-engine'),'potrace');assert.equal(await page.inputValue('#opt-illustration_profile'),'edge_clean');assert.equal(await page.inputValue('#opt-path_limit'),'2000');assert.equal(await page.inputValue('#opt-potrace_smoothing'),'0');
  assert.equal(await page.locator('#opt-engine').isVisible(),false);assert.equal(await page.locator('#opt-colormode').count(),0);
  assert.equal(await page.locator('#opt-illustration_profile option').count(),4);checks.push('four Potrace profiles and no engine selector');
  await page.setInputFiles('#file',path.join(root,'examples/sample.png'));
  await page.waitForSelector('#apply-recommendation:not([hidden]):not([disabled])');
  assert(!(await page.innerText('#recommendation-summary')).includes('undefined'));
  await page.fill('#opt-output_directory',path.join(out,'ui-conversions'));
  await page.click('#crop-open');await page.waitForSelector('#crop-dialog[open]');await page.waitForSelector('#crop-stage:not([hidden])');
  await page.locator('#crop-source').evaluate(image=>image.decode());await page.selectOption('#crop-preset','1:1');await page.click('#crop-apply');await page.waitForSelector('#crop-dialog',{state:'hidden'});
  await page.waitForSelector('#apply-recommendation:not([hidden]):not([disabled])');
  await page.click('#apply-recommendation');assert.equal(await page.inputValue('#opt-crop_ratio'),'1:1');assert.equal(await page.inputValue('#opt-output_directory'),path.join(out,'ui-conversions'));
  checks.push('crop-aware recommendation and one-click apply preserves crop/output');
  await page.screenshot({path:path.join(out,'ui-recommendation.png')});
  await page.selectOption('#opt-illustration_profile','gradient_layers');assert.equal(await page.inputValue('#opt-potrace_palette_colors'),'64');assert(await page.isChecked('#opt-curve_simplify'));
  await page.check('#opt-sr_enabled');assert(!(await page.isChecked('#opt-highres_refine')));assert(await page.isDisabled('#opt-highres_refine'));
  assert(await page.isDisabled('#opt-diffvg_optimize'));
  await page.selectOption('#opt-illustration_profile','edge_clean');await page.check('#opt-diffvg_optimize');await page.check('#opt-highres_refine');await page.selectOption('#opt-illustration_profile','gradient_layers');assert(!(await page.isChecked('#opt-diffvg_optimize')));assert(!(await page.isChecked('#opt-highres_refine')));
  await page.uncheck('#opt-sr_enabled');checks.push('layered SR and profile switching dependencies');
  await page.fill('#opt-path_limit','32');await page.fill('#opt-simplify_target_paths','16');await page.click('#convert');
  await page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('转换成功'),{},{timeout:120000});
  await page.locator('#vector').evaluate(im=>im.decode());assert((await page.innerText('#pipeline-stats')).includes('渐变分层'));
  checks.push('actual gradient route conversion, path budget, SVG preview');
  const stats=await page.innerText('#result-stats');
  await page.setInputFiles('#config-file',{name:'old.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({engine:'potrace',path_limit:12}))});
  await page.waitForFunction(()=>document.getElementById('status').textContent==='配置已导入。');assert.equal(await page.inputValue('#opt-illustration_profile'),'legacy');assert.equal(await page.inputValue('#opt-potrace_palette_colors'),'48');assert(!(await page.isChecked('#opt-curve_simplify')));
  await page.setInputFiles('#config-file',{name:'vtracer.json',mimeType:'application/json',buffer:Buffer.from('{"mode":"polygon"}')});
  await page.waitForSelector('#error:not([hidden])');assert((await page.innerText('#error')).includes('VTracer 支持已移除'));assert.equal(await page.inputValue('#opt-illustration_profile'),'legacy');
  for(const config of [{engine:'vtracer'},{engine:'vtracer',illustration_profile:'edge_clean'}]){await page.setInputFiles('#config-file',{name:'removed.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});await page.waitForSelector('#error:not([hidden])');assert((await page.innerText('#error')).includes('VTracer 支持已移除'));}
  await page.evaluate(()=>document.getElementById('status').textContent='importing');
  await page.setInputFiles('#config-file',{name:'mixed.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({engine:'potrace',path_limit:37,mode:'polygon',color_precision:7}))});
  await page.waitForFunction(()=>document.getElementById('status').textContent==='配置已导入。');assert.equal(await page.inputValue('#opt-path_limit'),'37');assert.equal(await page.inputValue('#opt-illustration_profile'),'legacy');
  await page.click('#reset');assert.equal(await page.inputValue('#opt-illustration_profile'),'edge_clean');checks.push('legacy Potrace mixed import, retired-engine rejection and reset');
  await page.locator('#opt-illustration_profile').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'ui-presets.png')});
  assert.deepEqual(errors,[]);const result={ok:true,checks,errors,stats};fs.writeFileSync(path.join(out,'ui-validation.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(e){console.error(stderr.slice(-1500));throw e;}finally{if(browser)await browser.close();child.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
