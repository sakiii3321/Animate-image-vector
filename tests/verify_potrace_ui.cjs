// End-to-end desktop-browser check against the actual bundled application.
const {chromium}=require('./node_test_dependencies.cjs')('playwright', __filename);
const {spawn}=require('child_process');
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..'),out=path.join(root,'outputs/code-review-20261107/ui-legacy/potrace');
fs.mkdirSync(out,{recursive:true});const work=fs.mkdtempSync(path.join(out,'run-'));
(async()=>{
 const child=spawn(path.join(root,'runtime/python.exe'),['-u','app/main.py','--no-browser'],{cwd:root,windowsHide:true,env:{...process.env,TEMP:work,TMP:work,PYTHONUTF8:'1'}});
 let browser;const errors=[];
 try{
  const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(new Error('Server startup timed out')),20000);child.stdout.on('data',buf=>{text+=buf.toString();const m=text.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[\w-]+/);if(m){clearTimeout(timer);resolve(m[0]);}});child.on('error',reject);child.on('exit',code=>{if(code)reject(new Error('Server exit '+code));});});
  browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu'],downloadsPath:work});
  const page=await browser.newPage({viewport:{width:1440,height:1100},acceptDownloads:true});page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.waitForSelector('#opt-illustration_profile',{state:'attached'});await page.check('#advanced-mode');
  assert.equal(await page.inputValue('#opt-illustration_profile'),'edge_clean');
  assert.equal(await page.inputValue('#opt-engine'),'potrace');
  assert.equal(await page.locator('#opt-engine').isVisible(),false);
  assert.equal(await page.locator('#opt-path_limit').isVisible(),true);
  assert.equal(await page.locator('#opt-colormode').count(),0);
  await page.locator('#file').setInputFiles(path.join(root,'examples/sample.png'));
  await page.locator('#opt-path_limit').fill('0');await page.click('#convert');
  await page.waitForSelector('#error:not([hidden])');
  await page.locator('#config-file').setInputFiles({name:'config.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({engine:'potrace',path_limit:12,detail_region:'',output_directory:work}))});
  await page.waitForFunction(()=>document.getElementById('status').textContent==='配置已导入。');
  await page.click('#convert');
  await page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('转换成功'),{},{timeout:90000});
  const stats=await page.locator('#result-stats').innerText();assert(stats.includes('上限 12'));assert(stats.includes('Potrace'));
  await page.locator('#vector').evaluate(im=>im.decode());
  const downloaded=page.waitForEvent('download');await page.click('#save-config');
  const download=await downloaded;const config=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
  assert.equal(config.engine,'potrace');assert.equal(config.path_limit,12);
  assert.equal(config.colormode,undefined);
  await page.screenshot({path:path.join(out,'potrace-ui.png'),fullPage:true});
  await page.locator('#config-file').setInputFiles({name:'legacy.json',mimeType:'application/json',buffer:Buffer.from('{"mode":"polygon"}')});
  await page.waitForSelector('#error:not([hidden])');assert((await page.innerText('#error')).includes('VTracer 支持已移除'));assert.equal(await page.inputValue('#opt-engine'),'potrace');assert.equal(await page.inputValue('#opt-path_limit'),'12');
  assert.deepEqual(errors,[]);
  const result={ok:true,errors,stats,checks:['fixed Potrace engine and removed controls','invalid path limit','config import and export','real HTTP Potrace conversion','SVG preview','retired configuration rejected without changing settings']};
  fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(result,null,2));console.log(result);
 }finally{if(browser)await browser.close();if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.kill();});const target=path.resolve(work);assert.equal(path.dirname(target),path.resolve(out));assert(path.basename(target).startsWith('run-'));fs.rmSync(target,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
