// Real HTTP conversion on CUDA, then CPU with CUDA hidden from that app process.
const {chromium}=require('./node_test_dependencies.cjs')('playwright', __filename);
const sharp=require('../runtime/potrace/node_modules/sharp');
const {spawn}=require('child_process');
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..'),out=path.join(root,'outputs/code-review-20261107/ui-legacy/sr-gpu');
fs.mkdirSync(out,{recursive:true});const work=fs.mkdtempSync(path.join(out,'run-'));
process.env.TEMP=work;process.env.TMP=work;
(async()=>{
 const source=path.join(work,'sr-input.png');
 await sharp(Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="24"><rect width="32" height="24" fill="#edf2e0"/><path d="M3 21L10 3L19 13L27 4L30 21Z" fill="#39798e"/><circle cx="17" cy="15" r="5" fill="#e6ad62"/></svg>')).png().toFile(source);
 try{
 const reports=[];
 for(const device of ['cuda','cpu']){
  const env={...process.env,PYTHONUTF8:'1'};if(device==='cpu')env.CUDA_VISIBLE_DEVICES='-1';
  const child=spawn(path.join(root,'runtime/python.exe'),['-u','app/main.py','--no-browser'],{cwd:root,windowsHide:true,env});
  let browser,stderr='';child.stderr.on('data',b=>stderr+=b);
  try{
   const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(Error('Server timeout '+stderr)),20000);child.stdout.on('data',b=>{text+=b;const m=text.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[\w-]+/);if(m){clearTimeout(timer);resolve(m[0])}});child.on('error',reject);child.on('exit',code=>{if(code)reject(Error('Server exit '+code+stderr))})});
   browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu']});
   const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);await page.waitForSelector('#opt-sr_enabled',{state:'attached'});await page.check('#advanced-mode');
   await page.waitForFunction(()=>document.getElementById('enhancement-status').textContent.includes('超分辨率：'),{},{timeout:60000});
   const capabilityText=await page.locator('#enhancement-status').innerText();
   assert(capabilityText.includes(device==='cuda'?'GPU 优先':'超分辨率：CPU'),capabilityText);
    await page.locator('#file').setInputFiles(source);
   await page.check('#opt-sr_enabled');await page.uncheck('#opt-highres_refine');
    await page.locator('#opt-output_directory').fill(work);
   const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/convert')&&r.request().method()==='POST',{timeout:180000});
   await page.click('#convert');const response=await responsePromise,result=await response.json();
   assert(response.ok(),JSON.stringify(result));
   await page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('转换成功'),{},{timeout:30000});
   await page.locator('#vector').evaluate(i=>i.decode());
   const sr=result.pipeline.stages.find(s=>s.stage==='super_resolution').report;
    assert.equal(sr.backend,device);assert.equal(sr.device_policy,'prefer_cuda');assert.deepEqual(sr.output_size,[64,48]);
   const text=await page.locator('#pipeline-stats').innerText();
   assert(text.includes(device==='cuda'?'GPU':'CPU · 已自动回退'),text);
   if(device==='cpu'){assert(sr.fallback_reason);assert((await page.locator('#pipeline-stats').getAttribute('title')).includes('CPU'))}
   const saved=JSON.parse(fs.readFileSync(result.path.replace(/\.svg$/,'.pipeline.json'),'utf8'));
   assert.equal(saved.stages.find(s=>s.stage==='super_resolution').report.backend,device);
   assert.equal(await page.evaluate(()=>progressDevice({stage:'sr_inference',device:'cpu',fallback_reason:'GPU failed'})),' · CPU（已自动回退）');
   assert.deepEqual(errors,[]);await page.locator('#pipeline-stats').screenshot({path:path.join(out,device+'-result.png')});
   reports.push({device,capabilityText,resultText:text,sr,errors,output:result.path});
   }finally{if(browser)await browser.close();if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.kill();});}
 }
  fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({ok:true,reports},null,2));
 console.log(JSON.stringify({ok:true,reports}));
 }finally{const target=path.resolve(work);assert.equal(path.dirname(target),path.resolve(out));assert(path.basename(target).startsWith('run-'));fs.rmSync(target,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
