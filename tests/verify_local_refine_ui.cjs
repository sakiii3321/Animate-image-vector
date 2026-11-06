// Actual freehand pointer gestures and local refinement HTTP lifecycle.
const {chromium}=require('./node_test_dependencies.cjs')('playwright', __filename);
const sharp=require('./node_test_dependencies.cjs')('sharp', __filename);
const {spawn}=require('child_process');
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..'),out=path.join(root,'outputs/local-refinement-study');
const previewFailuresOnly=process.argv.includes('--preview-failures');
fs.mkdirSync(out,{recursive:true});
process.env.TEMP=path.join(root,'.diagnostic-temp');process.env.TMP=process.env.TEMP;
(async()=>{
 const source=path.join(out,'refine-input.png');
 const shapes=Array.from({length:20},(_,i)=>`<circle cx="${80+i*5}" cy="${65+(i%4)*15}" r="${4+i%3}" fill="hsl(${i*13},65%,45%)"/>`).join('');
 await sharp(Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="256" height="192"><rect width="256" height="192" fill="#ece7de"/><path d="M35 150Q100 10 215 140" fill="#b2cfc5" stroke="#234e51" stroke-width="3"/>${shapes}<path d="M80 98Q130 75 175 110" fill="none" stroke="#303438" stroke-width="2"/></svg>`)).png().toFile(source);
 const child=spawn(path.join(root,'runtime/python.exe'),['-u','app/main.py','--no-browser'],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
 let browser,stderr='';const errors=[],checks=[],requests=[];child.stderr.on('data',b=>stderr+=b);
 try{
  const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(new Error('startup timeout: '+stderr)),20000);child.stdout.on('data',b=>{text+=b;const m=text.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[\w-]+/);if(m){clearTimeout(timer);resolve(m[0]);}});child.on('error',reject);});
  browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu'],downloadsPath:process.env.TEMP});
  const page=await browser.newPage({viewport:{width:1600,height:1200},acceptDownloads:true});page.on('pageerror',e=>errors.push(e.message));
  page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/api/refine'))requests.push(request.postDataJSON());});
  await page.goto(url);await page.waitForSelector('#opt-illustration_profile',{state:'attached'});await page.check('#advanced-mode');assert(!(await page.isVisible('#refine-panel')));
  await page.selectOption('#opt-illustration_profile','edge_clean');await page.fill('#opt-path_limit','12');await page.fill('#opt-potrace_palette_colors','12');await page.fill('#opt-output_directory',path.join(out,'conversions'));
  await page.setInputFiles('#file',source);
  const converted=page.waitForResponse(r=>r.url().endsWith('/api/convert')&&r.request().method()==='POST',{timeout:120000});await page.click('#convert');
  const initialResponse=await converted,initial=await initialResponse.json();assert(initialResponse.ok(),JSON.stringify(initial));assert(initial.result_id);
  await page.waitForSelector('#refine-panel:not([hidden])');await page.waitForFunction(()=>!document.getElementById('refine-draw').disabled);
  const initialBytes=fs.readFileSync(initial.path);assert(await page.isDisabled('#refine-generate'));assert(await page.isDisabled('#refine-undo'));
  await page.click('#zoom-in');await page.click('#refine-draw');assert(await page.isDisabled('#zoom-in'));
  await page.locator('#viewport').scrollIntoViewIfNeeded();
  const beforeDraw=await page.evaluate(()=>({x:view.x,y:view.y,scale:view.scale,split:view.split}));
  const polygon=[[90,58],[170,58],[175,118],[90,120],[90,58]];
  const screen=await page.evaluate(points=>{const r=document.getElementById('viewport').getBoundingClientRect();return points.map(([x,y])=>[r.left+view.x+x*view.scale,r.top+view.y+y*view.scale]);},polygon);
  await page.mouse.move(...screen[0]);await page.mouse.down();for(const p of screen.slice(1))await page.mouse.move(...p,{steps:12});await page.mouse.up();
  assert.deepStrictEqual(await page.evaluate(()=>({x:view.x,y:view.y,scale:view.scale,split:view.split})),beforeDraw,'drawing must not pan or move divider');
  assert.equal(await page.getAttribute('#refine-draw','aria-pressed'),'false');assert(!(await page.isDisabled('#refine-generate')));
  const outline=await page.getAttribute('#refine-outline','d');assert(outline.endsWith(' Z'));
  await page.click('#zoom-out');assert.notEqual(await page.getAttribute('#refine-outline','d'),outline,'outline follows zoom');
  await page.locator('#viewport').scrollIntoViewIfNeeded();const box=await page.locator('#viewport').boundingBox();
  await page.mouse.move(box.x+box.width*.8,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.8+18,box.y+box.height*.5+10,{steps:5});await page.mouse.up();
  const preserved=await page.evaluate(()=>({x:view.x,y:view.y,scale:view.scale,split:view.split}));checks.push('freehand closure and image coordinates survive zoom/pan without divider conflict');
  await page.fill('#refine-budget','80');await page.selectOption('#refine-detail','fine');
  async function generate(){const pending=page.waitForResponse(r=>r.url().endsWith('/api/refine')&&r.request().method()==='POST',{timeout:180000});await page.click('#refine-generate');const response=await pending,data=await response.json();assert(response.ok(),JSON.stringify(data));await page.waitForSelector('#refine-candidate-actions:not([hidden])');await page.waitForFunction(()=>!document.getElementById('refine-accept').disabled);return data;}
  const first=await generate();assert.equal(first.original_result_id,initial.result_id);assert.equal(requests[0].options.detail,'fine');assert.equal(requests[0].options.path_limit,80);
  if(previewFailuresOnly){
   const currentPreview=await page.evaluate(()=>vectorURL);
   await page.route('**/api/refine-preview?*',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"Injected candidate preview failure"}'}),{times:1});
   const replacing=page.waitForResponse(r=>r.url().endsWith('/api/refine')&&r.request().method()==='POST');await page.click('#refine-generate');
   const replacement=await (await replacing).json();assert(replacement.candidate_id);
   await page.waitForFunction(()=>document.getElementById('refine-status').textContent.includes('候选预览加载失败')&&!document.getElementById('refine-generate').disabled);
   assert(!(await page.isVisible('#refine-candidate-actions')));assert(!(await page.isVisible('#refine-candidate-badge')));assert(await page.isDisabled('#refine-accept'));
   assert.equal(await page.getAttribute('#vector','src'),currentPreview);assert.equal(await page.innerText('#output-path'),initial.path);assert(!(await page.isDisabled('#download')));
   const removedStatus=await page.evaluate(async candidate=>{const response=await fetch('/api/refine-preview?candidate_id='+encodeURIComponent(candidate),{headers:{'X-App-Token':new URLSearchParams(location.search).get('token')}});return response.status;},replacement.candidate_id);
   assert(removedStatus>=400,'unseen replacement candidate should be discarded');checks.push('candidate GET failure clears invalid old/new candidate and restores saved preview');
   await generate();
   async function failCurrentPreview(action,expectedMessage,expectedPath){
    await page.route('**/api/svg',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"Injected saved preview failure"}'}),{times:1});
    const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/refine-'+action));await page.click(action==='accept'?'#refine-accept':'#refine-undo');
    const response=await responsePromise,next=await response.json();assert(response.ok(),JSON.stringify(next));
    await page.waitForFunction(text=>document.getElementById('refine-status').textContent.includes(text)&&!document.getElementById('refine-retry-preview').disabled,expectedMessage);
    assert.equal(await page.innerText('#output-path'),expectedPath||next.path);assert(fs.existsSync(next.path));
    assert(await page.isDisabled('#download'));assert(await page.isDisabled('#download-preview'));assert(await page.isDisabled('#refine-generate'));assert(!(await page.isVisible('#vector')));
    assert(await page.evaluate(()=>svgBlob===null&&vectorURL===null),'old SVG must not remain downloadable as new result');
    assert(await page.isVisible('#refine-retry-preview'));assert(!(await page.isVisible('#refine-candidate-actions')));
    await page.screenshot({path:path.join(out,'preview-failure-'+action+'.png')});
    await page.click('#refine-retry-preview');await page.waitForFunction(()=>document.getElementById('refine-status').textContent.includes('预览已恢复'));
    assert(!(await page.isDisabled('#download')));assert(await page.isVisible('#vector'));assert(!(await page.isVisible('#refine-retry-preview')));
    assert.deepStrictEqual(await page.evaluate(()=>({x:view.x,y:view.y,scale:view.scale,split:view.split})),preserved,'retry preserves canvas coordinates');
    return next;
   }
   const accepted=await failCurrentPreview('accept','已保存新 SVG，但预览加载失败');assert.notEqual(accepted.path,initial.path);
   checks.push('accept POST commits new metadata, disables stale download and allows retry after SVG GET failure');
   // Undo is also a version switch. Its success proves the accepted result ID
   // was synchronized even when the first preview request failed.
   const undone=await failCurrentPreview('undo','已撤销，但预览加载失败',initial.path);assert.notEqual(undone.result_id,initial.result_id);
   checks.push('undo uses new result ID and recovers from its own SVG GET failure');
   assert.deepStrictEqual(errors,[]);const report={ok:true,checks,errors,replacement_candidate:replacement.candidate_id,accepted:accepted.path,restored:undone.path};
   fs.writeFileSync(path.join(out,'ui-preview-failures.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));return;
  }
  assert(Math.abs(requests[0].polygon[0][0]-90)<.5&&Math.abs(requests[0].polygon[0][1]-58)<.5,'request coordinates stay in source image space');
  assert(await page.isVisible('#refine-candidate-badge'));assert((await page.innerText('#vector-tag')).includes('未采用'));assert.equal(await page.innerText('#output-path'),initial.path);
  const candidateSrc=await page.getAttribute('#vector','src');await page.click('#refine-current');await page.waitForFunction(()=>document.getElementById('refine-current').getAttribute('aria-pressed')==='true');assert.notEqual(await page.getAttribute('#vector','src'),candidateSrc);
  await page.click('#refine-candidate');await page.waitForFunction(()=>document.getElementById('refine-candidate').getAttribute('aria-pressed')==='true');assert.equal(await page.getAttribute('#vector','src'),candidateSrc);
  const downloading=page.waitForEvent('download');await page.click('#download-preview');const downloaded=await downloading;assert.deepStrictEqual(fs.readFileSync(await downloaded.path()),initialBytes,'candidate preview must not replace saved download');
  await page.screenshot({path:path.join(out,'candidate-preview.png')});checks.push('real candidate, explicit preview toggles and unchanged current/download before accept');
  const accepting=page.waitForResponse(r=>r.url().endsWith('/api/refine-accept'));await page.click('#refine-accept');const acceptedResponse=await accepting,accepted=await acceptedResponse.json();assert(acceptedResponse.ok(),JSON.stringify(accepted));
  await page.waitForFunction(()=>document.getElementById('refine-status').textContent.startsWith('已采用'));assert.notEqual(accepted.path,initial.path);assert(fs.existsSync(accepted.path));assert(!(await page.isVisible('#refine-candidate-badge')));assert(!(await page.isDisabled('#refine-undo')));
  assert.deepStrictEqual(await page.evaluate(()=>({x:view.x,y:view.y,scale:view.scale,split:view.split})),preserved);assert.deepStrictEqual(fs.readFileSync(initial.path),initialBytes);
  checks.push('accept saves separate SVG and preserves canvas position');
  const undoing=page.waitForResponse(r=>r.url().endsWith('/api/refine-undo'));await page.click('#refine-undo');const undoResponse=await undoing,undone=await undoResponse.json();assert(undoResponse.ok(),JSON.stringify(undone));
  await page.waitForFunction(()=>document.getElementById('refine-status').textContent.startsWith('已撤销'));assert.equal(await page.innerText('#output-path'),initial.path);assert.notEqual(undone.result_id,initial.result_id);
  const second=await generate();assert.equal(second.original_result_id,undone.result_id);
  const retainedCandidate=await page.getAttribute('#vector','src');
  const cancelling=page.waitForResponse(r=>r.url().endsWith('/api/refine')&&r.request().method()==='POST',{timeout:120000});await page.click('#refine-generate');
  await page.waitForFunction(()=>!document.getElementById('stop').hidden&&!document.getElementById('stop').disabled);await page.click('#stop');
  const cancelledResponse=await cancelling,cancelled=await cancelledResponse.json();assert(cancelledResponse.ok(),JSON.stringify(cancelled));assert(cancelled.cancelled,JSON.stringify(cancelled));
  await page.waitForFunction(()=>!document.getElementById('refine-discard').disabled);assert.equal(await page.getAttribute('#vector','src'),retainedCandidate);assert(await page.isVisible('#refine-candidate-actions'));assert.equal(await page.innerText('#output-path'),initial.path);checks.push('cancel replacement generation retains prior candidate and saved result');
  const discarding=page.waitForResponse(r=>r.url().endsWith('/api/refine-discard'));await page.click('#refine-discard');const discarded=await discarding;assert(discarded.ok(),await discarded.text());await page.waitForSelector('#refine-candidate-actions',{state:'hidden'});assert.equal(await page.innerText('#output-path'),initial.path);checks.push('undo, fresh result ID, repeated refinement and discard');
  await page.setViewportSize({width:760,height:1100});assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)));await page.screenshot({path:path.join(out,'refine-narrow.png')});
  await page.setInputFiles('#file',path.join(root,'examples/sample.png'));assert(!(await page.isVisible('#refine-panel')));assert.equal(await page.getAttribute('#refine-outline','d'),'');checks.push('new image clears selection/candidate and narrow layout fits');
  assert.deepStrictEqual(errors,[]);const report={ok:true,checks,errors,initial:initial.path,accepted:accepted.path,request:requests[0],candidate:first.report,stats:accepted.stats};fs.writeFileSync(path.join(out,'ui-results.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }catch(error){if(browser){const page=browser.contexts()[0]?.pages()[0];if(page){await page.screenshot({path:path.join(out,'ui-failure.png')});console.error(await page.evaluate(()=>({status:document.getElementById('refine-status').textContent,outline:document.getElementById('refine-outline').getAttribute('d'),view})));}}console.error(stderr.slice(-1600));throw error;}finally{if(browser)await browser.close();child.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
