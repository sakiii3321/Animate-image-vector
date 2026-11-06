const {chromium}=require('./node_test_dependencies.cjs')('playwright', __filename);
const sharp=require('../runtime/potrace/node_modules/sharp');
const {spawn}=require('child_process');
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..'),out=path.join(root,'outputs/code-review-20261107/ui-legacy/simplify-cancel');
fs.mkdirSync(out,{recursive:true});const work=fs.mkdtempSync(path.join(out,'run-'));
process.env.TEMP=work;process.env.TMP=work;
(async()=>{
 const source=path.join(work,'simplify-input.png');
 const colors=['red','orange','yellow','green','blue','purple'];
 await sharp(Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60">${colors.map((fill,i)=>`<rect x="${i*20}" width="20" height="60" fill="${fill}"/>`).join('')}</svg>`)).png().toFile(source);
 const child=spawn(path.join(root,'runtime/python.exe'),['-u','app/main.py','--no-browser'],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
 let browser,stderr='';const errors=[],checks=[];child.stderr.on('data',b=>stderr+=b.toString());
 try{
  const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(new Error('Startup timeout: '+stderr)),20000);child.stdout.on('data',b=>{text+=b.toString();const m=text.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[\w-]+/);if(m){clearTimeout(timer);resolve(m[0]);}});child.on('error',reject);});
  browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu'],downloadsPath:process.env.TEMP});
  const page=await browser.newPage({viewport:{width:1500,height:1000},acceptDownloads:true});page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.waitForSelector('#opt-simplify_target_paths',{state:'attached'});await page.check('#advanced-mode');
  await page.selectOption('#opt-illustration_profile','legacy');
  assert(await page.locator('#opt-simplify_target_paths').isVisible());assert(!await page.locator('#stop').isVisible());
  assert(await page.locator('#opt-simplify_target_paths').isDisabled());
  await page.check('#opt-curve_simplify');assert(await page.locator('#opt-simplify_target_paths').isEnabled());
  await page.fill('#opt-simplify_target_paths','3');await page.fill('#opt-path_limit','12');await page.fill('#opt-potrace_palette_colors','6');await page.fill('#opt-potrace_smoothing','0');await page.fill('#opt-potrace_min_region_area','0');
  await page.fill('#opt-output_directory',work);
  await page.locator('label[for="opt-simplify_target_paths"]').hover();await page.locator('#parameter-tooltip').waitFor({state:'visible'});assert((await page.locator('#parameter-tooltip').innerText()).includes('较小值'));
  await page.keyboard.press('Escape');checks.push('Target count visibility, dependency and detailed tooltip');
  const downloadPromise=page.waitForEvent('download');await page.click('#save-config');const download=await downloadPromise;const exported=JSON.parse(fs.readFileSync(await download.path(),'utf8'));assert.strictEqual(exported.simplify_target_paths,3);
  await page.fill('#opt-simplify_target_paths','9');await page.locator('#config-file').setInputFiles({name:'config.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(exported))});await page.waitForFunction(()=>document.getElementById('status').textContent==='配置已导入。');assert.strictEqual(await page.inputValue('#opt-simplify_target_paths'),'3');checks.push('Target count config export/import');
  await page.locator('#file').setInputFiles(source);
  let responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/convert')&&r.request().method()==='POST',{timeout:120000});await page.click('#convert');let response=await responsePromise,result=await response.json();assert(response.ok(),JSON.stringify(result));assert.strictEqual(result.stats.paths,3);
  await page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('转换成功'));assert((await page.locator('#pipeline-stats').innerText()).includes('色块 6 → 3'));await page.locator('#vector').evaluate(el=>el.decode());checks.push('Real Potrace 6 → 3 with simplified SVG preview');
  await page.check('#opt-diffvg_optimize');await page.fill('#opt-diffvg_iterations','100');
  responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/convert')&&r.request().method()==='POST',{timeout:120000});await page.click('#convert');
  // Wait for the real nested DiffVG helper, then cancel it through the UI.
  await page.waitForFunction(()=>document.getElementById('status').textContent.includes('全图优化'),null,{timeout:90000});
  await page.waitForFunction(()=>!document.getElementById('stop').disabled);await page.click('#stop');
  response=await responsePromise;result=await response.json();assert.deepStrictEqual(result,{cancelled:true});
  await page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('已停止当前任务'));
  assert(await page.locator('#opt-simplify_target_paths').isEnabled());assert.strictEqual(await page.inputValue('#opt-simplify_target_paths'),'3');assert.strictEqual(await page.inputValue('#opt-diffvg_iterations'),'100');assert(!await page.locator('#stop').isVisible());checks.push('Cancel active DiffVG, preserve parameters and restore controls');
  await page.screenshot({path:path.join(out,'simplify-cancel-ui.png')});
  await page.uncheck('#opt-diffvg_optimize');await page.fill('#opt-simplify_target_paths','2');
  responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/convert')&&r.request().method()==='POST',{timeout:120000});await page.click('#convert');response=await responsePromise;result=await response.json();assert(response.ok(),JSON.stringify(result));assert.strictEqual(result.stats.paths,2);await page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('转换成功'));checks.push('Change target after cancellation and regenerate successfully');
  assert.deepStrictEqual(errors,[]);fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({ok:true,checks,errors,stats:result.stats},null,2));console.log(JSON.stringify({ok:true,checks,errors}));
 }finally{if(browser)await browser.close();if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.kill();});const target=path.resolve(work);assert.equal(path.dirname(target),path.resolve(out));assert(path.basename(target).startsWith('run-'));fs.rmSync(target,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
