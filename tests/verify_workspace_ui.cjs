// Real browser regression for preset-first controls and transactional crop editing.
const {chromium}=require('./node_test_dependencies.cjs')('playwright', __filename);
const sharp=require('./node_test_dependencies.cjs')('sharp', __filename);
const {spawn}=require('child_process');
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const out=path.join(root,'outputs/ui-redesign-study');
const temporaryRoot=path.join(root,'.diagnostic-temp');
const configRecoveryOnly=process.argv.includes('--config-recovery');
fs.mkdirSync(out,{recursive:true});fs.mkdirSync(temporaryRoot,{recursive:true});

const presets={
 balanced:{illustration_profile:'edge_clean',path_limit:2000,potrace_palette_colors:100,curve_tolerance:.3},
 detail:{illustration_profile:'edge_clean',path_limit:4000,potrace_palette_colors:160,curve_tolerance:.2},
 compact:{illustration_profile:'edge_clean',path_limit:800,potrace_palette_colors:64,curve_tolerance:.5},
 gradient:{illustration_profile:'gradient_layers',path_limit:2000,potrace_palette_colors:64,curve_tolerance:.3},
 line_art:{illustration_profile:'edge_clean',path_limit:1500,potrace_palette_colors:64,curve_tolerance:.2}
};

(async()=>{
 const work=fs.mkdtempSync(path.join(temporaryRoot,'workspace-ui-'));
 const outputDirectory=path.join(work,'conversions');
 const source=path.join(work,'landscape.png'),replacement=path.join(work,'replacement.png');
 const colors=['#234b59','#e5a886','#8fb7b2','#d9d3b2','#66768c'];
 const shapes=Array.from({length:15},(_,i)=>`<circle cx="${180+(i%5)*60}" cy="${125+Math.floor(i/5)*90}" r="${12+i%3*3}" fill="${colors[i%colors.length]}"/>`).join('');
 await sharp(Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#f0ede5"/><path d="M80 370Q140 30 320 80Q520 140 570 385Z" fill="#b7d1c4" stroke="#35566a" stroke-width="4"/>${shapes}<path d="M130 330Q270 240 520 345" fill="none" stroke="#473b53" stroke-width="4"/></svg>`)).png().toFile(source);
 await sharp({create:{width:360,height:240,channels:3,background:'#a5c5c7'}}).png().toFile(replacement);
 const child=spawn(path.join(root,'runtime/python.exe'),['-u','app/main.py','--no-browser'],{
  cwd:root,windowsHide:true,env:{...process.env,TEMP:temporaryRoot,TMP:temporaryRoot,PYTHONUTF8:'1'}
 });
 let browser,page,stderr='',passed=false;
 const errors=[],cspErrors=[],checks=[],conversions=[],cropChecks=[],screenshots=[];
 child.stderr.on('data',buffer=>stderr+=buffer);
 async function screenshot(name){await page.screenshot({path:path.join(out,name),animations:'disabled'});screenshots.push(name);}
 async function config(){return page.evaluate(()=>getConfig());}
 async function cropConfig(){const current=await config();return Object.fromEntries(['crop_ratio','crop_x','crop_y','crop_rect'].map(key=>[key,current[key]]));}
 function rect(value,width=640,height=480){return value?value.split(',').map(Number):[0,0,width,height];}
 async function openCrop(){
  await page.click('#crop-open');await page.waitForSelector('#crop-dialog[open]');
  await page.waitForSelector('#crop-stage',{state:'visible'});
  await page.locator('#crop-source').evaluate(image=>image.decode());
 }
 async function applyCrop(){await page.click('#crop-apply');await page.waitForSelector('#crop-dialog',{state:'hidden'});return cropConfig();}
 async function dragCorner(corner,dx,dy){
  const handle=page.locator(`[data-crop-handle="${corner}"]`);
  await handle.scrollIntoViewIfNeeded();const box=await handle.boundingBox();assert(box,corner+' handle visible');
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  await page.mouse.move(box.x+box.width/2+dx,box.y+box.height/2+dy,{steps:10});await page.mouse.up();
 }
 async function boundedFrame(label){
  const stage=await page.locator('#crop-stage').boundingBox(),frame=await page.locator('#crop-frame').boundingBox();
  assert(stage&&frame,label+' frame visible');
  assert(frame.width>0&&frame.height>0,label+' positive dimensions');
  assert(frame.x>=stage.x-2&&frame.y>=stage.y-2&&frame.x+frame.width<=stage.x+stage.width+2&&frame.y+frame.height<=stage.y+stage.height+2,label+' stays inside image');
  return frame;
 }
 async function noOverflow(label){
  const value=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth}));
  assert(value.scroll<=value.viewport+1,label+' horizontal overflow: '+JSON.stringify(value));return value;
 }
 async function selectRatio(value,custom){
  await openCrop();await page.click('#crop-reset');await page.selectOption('#crop-preset',value);
  if(custom){await page.fill('#crop-custom-ratio',custom);await page.locator('#crop-custom-ratio').press('Tab');}
  if(value==='9:16')await dragCorner('se',-30,-35);
  else if(value==='4:3')await dragCorner('nw',30,25);
  else if(value==='custom')await dragCorner('ne',-30,20);
  await boundedFrame(value);const committed=await applyCrop();
  const [x,y,w,h]=rect(committed.crop_rect),[a,b]=(custom||value).split(':').map(Number);
  assert(w>0&&h>0&&x>=0&&y>=0&&x+w<=640&&y+h<=480);
  assert.equal(w*b,h*a,value+' exact integer ratio');
  cropChecks.push({ratio:custom||value,rect:[x,y,w,h],config:committed});return committed;
 }
 async function illustrationPreviews({initial=false}={}){
  await page.setViewportSize({width:1600,height:1000});
  if(initial){
   await page.reload();await page.waitForSelector('#preset-grid [data-preset]');
   await page.evaluate(()=>{scrollTo(0,0);document.querySelector('.settings-scroll')?.scrollTo(0,0);});
   await noOverflow('refreshed initial desktop');await screenshot('workspace-initial-desktop.png');
  }
  await page.setInputFiles('#file',path.join(root,'test_pic/134948250_p0.png'));
  await page.waitForFunction(()=>document.getElementById('original').naturalWidth===2285);
  await page.waitForFunction(()=>document.getElementById('crop-summary-detail').textContent.includes('px'));
  await page.evaluate(()=>{scrollTo(0,0);document.querySelector('.settings-scroll')?.scrollTo(0,0);});
  await noOverflow('illustration desktop');await screenshot('workspace-illustration-desktop.png');
  await openCrop();await page.selectOption('#crop-preset','9:16');await boundedFrame('illustration crop');
  await page.locator('#crop-dialog').screenshot({path:path.join(out,'workspace-crop-dialog.png'),animations:'disabled'});screenshots.push('workspace-crop-dialog.png');
  await page.click('#crop-cancel');
  const viewports=[];
  for(const viewport of [{width:760,height:1000},{width:390,height:844}]){
   await page.setViewportSize(viewport);await page.evaluate(()=>scrollTo(0,0));viewports.push({...viewport,...await noOverflow(viewport.width+'px workspace')});
   await screenshot(viewport.width===760?'workspace-tablet.png':'workspace-mobile.png');
   await openCrop();await noOverflow(viewport.width+'px crop dialog');await boundedFrame(viewport.width+'px crop');
   const box=await page.locator('#crop-dialog').boundingBox();assert(box.x>=-1&&box.x+box.width<=viewport.width+1,'dialog fits viewport');
   await page.keyboard.press('Escape');await page.waitForSelector('#crop-dialog',{state:'hidden'});
  }
  return viewports;
 }
 try{
  const url=await new Promise((resolve,reject)=>{
   let text='';const timer=setTimeout(()=>reject(new Error('startup timeout: '+stderr)),20000);
   child.stdout.on('data',buffer=>{text+=buffer;const match=text.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[\w-]+/);if(match){clearTimeout(timer);resolve(match[0]);}});
   child.on('error',reject);child.once('exit',code=>{if(!text.includes('http://'))reject(new Error('server exited '+code+': '+stderr));});
  });
  browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-gpu']});
  page=await browser.newPage({viewport:{width:1600,height:1000}});
  page.on('pageerror',error=>errors.push(error.stack||error.message));
  page.on('console',message=>{if(message.type()==='error'&&/Content Security Policy|Refused to (load|execute|apply)/i.test(message.text()))cspErrors.push(message.text());});
  await page.goto(url);await page.waitForSelector('#preset-grid [data-preset]');
  assert.equal(await page.locator('#preset-grid [data-preset]').count(),5);
  assert(!(await page.isChecked('#advanced-mode')));assert(await page.locator('#advanced-settings').evaluate(element=>element.hidden));
  assert.equal(await page.getAttribute('#preset-summary','data-preset'),'balanced');
  assert.equal(await page.getAttribute('#preset-grid [data-preset="balanced"]','aria-pressed'),'true');
  await page.evaluate(()=>document.querySelector('.settings-scroll')?.scrollTo(0,0));
  await noOverflow('initial desktop');if(!configRecoveryOnly)await screenshot('workspace-initial-desktop.png');
  checks.push('five preset cards, balanced selected and advanced controls hidden initially');
  const schema=await page.evaluate(async()=>{const response=await fetch('/api/schema',{headers});return response.json();});

  await page.fill('#opt-output_directory',outputDirectory);
  await page.setInputFiles('#file',source);await page.waitForFunction(()=>!document.getElementById('crop-open').disabled);
  if(configRecoveryOnly){
   await openCrop();await page.selectOption('#crop-preset','free');
   await dragCorner('nw',65,50);await dragCorner('se',-85,-65);await applyCrop();
   await page.click('#preset-grid [data-preset="detail"]');await page.check('#advanced-mode');
   const before=await config(),beforePreset=await page.getAttribute('#preset-summary','data-preset');
   assert(before.crop_rect);assert.equal(beforePreset,'detail');
   const invalid=path.join(work,'out-of-bounds-config.json');
   fs.writeFileSync(invalid,JSON.stringify({...before,crop_rect:'630,0,30,100',path_limit:1234,potrace_palette_colors:32}));
   await page.setInputFiles('#config-file',invalid);
   await page.waitForFunction(()=>!document.getElementById('error').hidden&&document.getElementById('error').textContent.includes('超出'));
   const rejected=await page.innerText('#error');
   assert.deepStrictEqual(await config(),before,'invalid imported rectangle must not partially change any setting');
   assert.equal(await page.getAttribute('#preset-summary','data-preset'),beforePreset);
   assert(!(await page.isDisabled('#convert')),'valid prior configuration remains usable');
   checks.push('out-of-bounds imported rectangle rejects the whole configuration without changing preset/crop/output/advanced values');
   await page.evaluate(()=>{document.getElementById('opt-crop_rect').value='630,0,30,100';cropEditor.render();});
   assert(await page.isDisabled('#convert'),'simulated older invalid hidden rectangle is rejected');
   await page.click('#reset');
   assert.deepStrictEqual(await config(),schema.defaults,'reset recovers even when old hidden crop values are invalid');
   assert.equal(await page.getAttribute('#preset-summary','data-preset'),'balanced');
   assert(!(await page.isDisabled('#convert')));
   checks.push('Restore defaults clears a pre-existing invalid hidden rectangle and restores a valid balanced configuration');
   const recovered=await config(),viewports=await illustrationPreviews({initial:true});
   assert.deepStrictEqual(errors,[]);assert.deepStrictEqual(cspErrors,[]);
   const report={ok:true,mode:'config-recovery',checks,rejected_error:rejected,preset_before:beforePreset,
    valid_crop_before:before.crop_rect,config_after:recovered,viewports,screenshots,errors,cspErrors,generated_test_svgs:0};
   fs.writeFileSync(path.join(out,'workspace-config-recovery-results.json'),JSON.stringify(report,null,2));passed=true;
   console.log(JSON.stringify(report));return;
  }
  const untouchedCrop=await cropConfig();
  await openCrop();await page.selectOption('#crop-preset','9:16');await page.click('#crop-cancel');
  await page.waitForSelector('#crop-dialog',{state:'hidden'});assert.deepStrictEqual(await cropConfig(),untouchedCrop);
  await openCrop();await page.selectOption('#crop-preset','4:3');await page.keyboard.press('Escape');
  await page.waitForSelector('#crop-dialog',{state:'hidden'});assert.deepStrictEqual(await cropConfig(),untouchedCrop);
  checks.push('crop cancel and Escape leave committed values unchanged');

  await openCrop();await page.selectOption('#crop-preset','free');
  for(const [corner,dx,dy] of [['nw',65,50],['ne',-65,50],['sw',65,-50],['se',-65,-50]]){
   await page.click('#crop-reset');await page.selectOption('#crop-preset','free');
   const initial=await boundedFrame(corner+' initial');
   await dragCorner(corner,dx,dy);const resized=await boundedFrame(corner+' resized');
   assert(resized.width<initial.width-5&&resized.height<initial.height-5,corner+' resizes both free axes');
   await dragCorner(corner,-dx*20,-dy*20);await boundedFrame(corner+' clamped');
  }
  await page.click('#crop-reset');await page.selectOption('#crop-preset','free');
  await dragCorner('nw',65,50);await dragCorner('se',-85,-65);
  const free=await applyCrop();const freeRect=rect(free.crop_rect);assert(free.crop_rect&&freeRect[2]<640&&freeRect[3]<480);
  cropChecks.push({ratio:'free',rect:freeRect,config:free});
  checks.push('all four free-crop handles resize and clamp within the original image');
  await selectRatio('9:16');await selectRatio('4:3');await selectRatio('custom','5:2');
  const committedCrop=await selectRatio('9:16');
  checks.push('9:16, 4:3 and custom 5:2 crop ratios commit integer source coordinates');

  await page.waitForFunction(()=>!document.getElementById('analyze-image').disabled);
  const analyzing=page.waitForResponse(response=>response.url().endsWith('/api/analyze')&&response.request().method()==='POST'&&response.request().postDataJSON().config.crop_rect===committedCrop.crop_rect,{timeout:30000});
  await page.click('#analyze-image');const analysisResponse=await analyzing,analysis=await analysisResponse.json();
  assert(analysisResponse.ok(),JSON.stringify(analysis));
  const [cropX,cropY,cropW,cropH]=rect(committedCrop.crop_rect);
  assert.deepStrictEqual(analysis.source_size,[cropW,cropH]);assert.deepStrictEqual(analysis.crop_box,[cropX,cropY,cropX+cropW,cropY+cropH]);
  checks.push('image analysis submits the committed crop rectangle and analyzes that exact size');

  await page.check('#advanced-mode');assert(await page.isVisible('#advanced-settings'));
  await page.fill('#opt-path_limit','777');
  assert.equal(await page.getAttribute('#preset-summary','data-preset'),'custom');assert((await page.innerText('#preset-summary')).includes('自定义'));
  await page.uncheck('#advanced-mode');assert(!(await page.isVisible('#advanced-settings')));
  await page.click('#preset-summary [data-open-advanced]');assert(await page.isChecked('#advanced-mode'));
  await page.check('#opt-sr_enabled');await page.selectOption('#opt-sr_scale','4');
  await page.check('#opt-diffvg_optimize');await page.check('#opt-highres_refine');
  await page.fill('#opt-detail_region','1,1,20,20');
  await page.click('#preset-grid [data-preset="balanced"]');
  assert(await page.isChecked('#advanced-mode'),'preset does not unexpectedly close explicitly opened advanced controls');
  const reset=await config();
  assert.equal(reset.sr_enabled,false);assert.equal(reset.sr_scale,2);assert.equal(reset.diffvg_optimize,false);assert.equal(reset.highres_refine,false);assert.equal(reset.detail_region,'');
  assert.deepStrictEqual(await cropConfig(),committedCrop);assert.equal(reset.output_directory,outputDirectory);
  await page.uncheck('#advanced-mode');
  checks.push('manual edits show custom state; presets preserve crop/output and reset enhancement/ROI settings');

  for(const [id,settings] of Object.entries(presets)){
   await page.click(`#preset-grid [data-preset="${id}"]`);
   assert.equal(await page.getAttribute('#preset-summary','data-preset'),id);
   assert.equal(await page.getAttribute(`#preset-grid [data-preset="${id}"]`,'aria-pressed'),'true');
   assert(!(await page.isChecked('#advanced-mode')));
   const expected={...schema.defaults,...schema.profile_presets[settings.illustration_profile],...settings,...committedCrop,output_directory:outputDirectory};
   assert.deepStrictEqual(await config(),expected,id+' complete preset configuration');
   const pending=page.waitForResponse(response=>response.url().endsWith('/api/convert')&&response.request().method()==='POST',{timeout:180000});
   await page.click('#convert');const response=await pending,data=await response.json();
   assert(response.ok(),id+': '+JSON.stringify(data));assert.deepStrictEqual(response.request().postDataJSON().config,expected);
   assert.equal(data.width,cropW);assert.equal(data.height,cropH);assert.equal(data.config.crop_rect,committedCrop.crop_rect);
   assert(fs.existsSync(data.path));assert(data.stats.drawing_paths<=settings.path_limit);
   await page.waitForFunction(()=>!busy&&document.getElementById('status').textContent.startsWith('转换成功'),{},{timeout:30000});
   await page.locator('#vector').evaluate(image=>image.decode());
   await page.waitForSelector('#refine-panel:not([hidden])');
   conversions.push({preset:id,width:data.width,height:data.height,bytes:data.bytes,paths:data.stats.drawing_paths,profile:data.config.illustration_profile,submitted:response.request().postDataJSON().config});
  }
  checks.push('all five presets complete real conversion with exact submitted settings and committed crop dimensions');

  assert(!(await page.isDisabled('#refine-draw')));
  await page.locator('#viewport').scrollIntoViewIfNeeded();await page.click('#refine-draw');
  const polygon=[[cropW*.3,cropH*.3],[cropW*.7,cropH*.3],[cropW*.7,cropH*.7],[cropW*.3,cropH*.7],[cropW*.3,cropH*.3]];
  const points=await page.evaluate(polygon=>{const box=document.getElementById('viewport').getBoundingClientRect();return polygon.map(([x,y])=>[box.left+view.x+x*view.scale,box.top+view.y+y*view.scale]);},polygon);
  await page.mouse.move(...points[0]);await page.mouse.down();for(const point of points.slice(1))await page.mouse.move(...point,{steps:8});await page.mouse.up();
  assert(!(await page.isDisabled('#refine-generate')));await page.fill('#refine-budget','50');
  const generating=page.waitForResponse(response=>response.url().endsWith('/api/refine')&&response.request().method()==='POST',{timeout:180000});
  await page.click('#refine-generate');const candidateResponse=await generating,candidate=await candidateResponse.json();assert(candidateResponse.ok(),JSON.stringify(candidate));
  await page.waitForSelector('#refine-candidate-actions:not([hidden])');await page.waitForFunction(()=>!document.getElementById('refine-discard').disabled);
  const discard=page.waitForResponse(response=>response.url().endsWith('/api/refine-discard'));await page.click('#refine-discard');assert((await discard).ok());
  await page.waitForSelector('#refine-candidate-actions',{state:'hidden'});
  checks.push('after real preset conversion the existing local-refinement panel draws, generates and discards a candidate');

  await page.setInputFiles('#file',replacement);await page.waitForFunction(()=>document.getElementById('original').naturalWidth===360);
  assert.equal((await cropConfig()).crop_rect,'');assert.equal((await cropConfig()).crop_ratio,'');
  assert(!(await page.isVisible('#refine-panel')));checks.push('selecting a different source clears old crop coordinates and refinement result');

  const viewportChecks=await illustrationPreviews();
  checks.push('1600px, 760px and 390px workspaces and crop dialogs fit without horizontal overflow');
  assert.deepStrictEqual(errors,[]);
  assert.deepStrictEqual(cspErrors,[]);
  const report={ok:true,checks,crop:cropChecks,analysis:{source_size:analysis.source_size,crop_box:analysis.crop_box},conversions,
   refinement:{candidate:!!candidate.candidate_id,report:candidate.report},viewports:viewportChecks,screenshots,errors,cspErrors,
   generated_test_svgs:conversions.length,temporary_outputs_removed:true};
  fs.writeFileSync(path.join(out,'workspace-ui-results.json'),JSON.stringify(report,null,2));passed=true;
  console.log(JSON.stringify({ok:true,checks,conversions:conversions.map(({preset,width,height,bytes,paths})=>({preset,width,height,bytes,paths})),screenshots}));
 }catch(error){
  if(page){
   await page.screenshot({path:path.join(out,'workspace-ui-failure.png')}).catch(()=>{});
   const state=await page.evaluate(()=>({status:document.getElementById('status')?.textContent,error:document.getElementById('error')?.textContent,preset:document.getElementById('preset-summary')?.textContent,crop:document.getElementById('opt-crop_rect')?.value})).catch(()=>null);
   fs.writeFileSync(path.join(out,'workspace-ui-failure.json'),JSON.stringify({error:error.stack,checks,state,errors,cspErrors,stderr:stderr.slice(-2400)},null,2));
   await page.evaluate(async()=>{try{await fetch('/api/cancel',{method:'POST',headers});}catch{}}).catch(()=>{});
  }
  throw error;
 }finally{
  if(browser)await browser.close();child.kill();
  const resolved=path.resolve(work),allowed=path.resolve(temporaryRoot)+path.sep;
  assert(resolved.startsWith(allowed)&&path.basename(resolved).startsWith('workspace-ui-'));
  fs.rmSync(resolved,{recursive:true,force:true});
  if(!passed&&stderr)console.error(stderr.slice(-1600));
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
