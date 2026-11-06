'use strict';
const fs=require('fs'),path=require('path'),os=require('os');
const {Worker,isMainThread,parentPort,workerData}=require('worker_threads');
let engine;
function loadEngine(){
 if(!engine){
  // pnpm may use a project-local link; resolve Jimp from the same physical
  // Potrace package so its instanceof check sees the identical constructor.
  const moduleRoot=fs.realpathSync(path.join(__dirname,'../runtime/potrace/node_modules/potrace'));
  engine={Potrace:require(moduleRoot).Potrace,Jimp:require(require.resolve('jimp',{paths:[moduleRoot]}))};
 }
 return engine;
}
function settings(job){
 const o=job.trace_options||{},scale=job.scale||1;
 return {width:job.width,strokeWidth:(o.potrace_stroke_width??1)*scale,traceOptions:{threshold:128,
  turdSize:(o.potrace_turd_size??0)*scale*scale,alphaMax:o.potrace_alpha_max??1,
  optCurve:o.potrace_opt_curve??true,optTolerance:(o.potrace_opt_tolerance??0.4)*scale,
  turnPolicy:o.potrace_turn_policy??'minority'}};
}
async function traceOne(r,regions,config){
 const {Potrace,Jimp}=loadEngine();
 const [x,y,right,bottom]=r.bbox,w=right-x+2,h=bottom-y+2;
 const data=Buffer.alloc(w*h*4,255);
 for(let yy=y;yy<bottom;yy++)for(let xx=x;xx<right;xx++)if(regions[yy*config.width+xx]===r.id){const p=((yy-y+1)*w+xx-x+1)*4;data[p]=data[p+1]=data[p+2]=0;}
 const tracer=new Potrace(config.traceOptions);
 await new Promise((resolve,reject)=>tracer.loadImage(new Jimp({data,width:w,height:h}),e=>e?reject(e):resolve()));
 const color='#'+r.color.slice(0,3).map(c=>c.toString(16).padStart(2,'0')).join('');
 const alpha=r.color[3]/255,rawTag=tracer.getPathTag(color);
 const pathData=rawTag.match(/\bd="([^"]*)"/);
 if(!pathData||!/[LlHhVvCcSsQqTtAa]/.test(pathData[1]))return '';
 const stroke=config.strokeWidth>0?`stroke="${color}" stroke-width="${config.strokeWidth}" stroke-linejoin="round"`:'stroke="none"';
 const tag=rawTag.replace('<path',`<path id="region-${r.id}"`).replace(/\s+stroke="[^"]*"/g,'').replace(/\/>$/,` ${stroke}/>`);
 return `<g transform="translate(${x-1},${y-1})" opacity="${alpha.toFixed(5)}">${tag}</g>`;
}
function boxArea(r){return (r.bbox[2]-r.bbox[0]+2)*(r.bbox[3]-r.bbox[1]+2);}
function chooseWorkers(job,cores=os.availableParallelism(),free=os.freemem()){
 const requested=job.trace_threads??0;
 if(!Number.isInteger(requested)||requested<0||requested>16)throw new Error('Invalid tracing thread count');
 let largest=0,total=0;
 for(const r of job.regions){const area=boxArea(r);largest=Math.max(largest,area);total+=area;}
 // Small jobs finish sooner without worker startup. Bound simultaneous masks;
 // labels are shared once instead of copied per worker.
 if(requested===0&&(job.regions.length<64||total<8000000))return 1;
 const perWorker=96*1024*1024+largest*64;
 const memoryLimit=Math.max(1,Math.floor(Math.max(0,free*.4-job.width*job.height*2)/perWorker));
 return Math.max(1,Math.min(requested||4,cores,memoryLimit,job.regions.length));
}
async function traceParallel(job,regions,config,threads,progress){
 const shared=new SharedArrayBuffer(regions.byteLength);new Uint16Array(shared).set(regions);
 const order=job.regions.map((r,i)=>({i,r,area:boxArea(r)})).sort((a,b)=>b.area-a.area||a.i-b.i);
 const tags=new Array(order.length),pool=[];let next=0,completed=0,closing=false;
 try{
  await new Promise((resolve,reject)=>{
   function dispatch(worker){
    if(next===order.length)return;
    const batch=[];let pixels=0;
    do{const item=order[next++];batch.push({i:item.i,r:item.r});pixels+=item.area;}
    while(next<order.length&&batch.length<32&&pixels<500000);
    worker.postMessage(batch);
   }
   for(let i=0;i<threads;i++){
    const worker=new Worker(__filename,{workerData:{shared,config}});pool.push(worker);
    worker.on('error',reject);
    worker.on('exit',code=>{if(!closing&&completed<order.length)reject(new Error(`Potrace worker exited (${code})`));});
    worker.on('message',message=>{
     if(message.error){reject(new Error(message.error));return;}
     for(const item of message.results)tags[item.i]=item.tag;
     completed+=message.results.length;progress(completed);
     if(completed===order.length)resolve();else dispatch(worker);
    });
    dispatch(worker);
   }
  });
  return tags;
 }finally{closing=true;await Promise.all(pool.map(worker=>worker.terminate()));}
}
async function main(){
 const jobPath=process.argv[2],job=JSON.parse(fs.readFileSync(jobPath,'utf8'));
 if(job.regions.length>job.limit)throw new Error('Region budget exceeded');
 const buf=fs.readFileSync(path.join(path.dirname(jobPath),'regions.bin'));
 const regions=new Uint16Array(buf.buffer,buf.byteOffset,buf.byteLength/2);
 const config=settings(job),threads=chooseWorkers(job);let last=0;
 const progress=current=>{const now=Date.now();if(current===0||current===job.regions.length||now-last>=300){
  process.stdout.write(JSON.stringify({stage:'potrace_trace',current,total:job.regions.length,threads})+'\n');last=now;
 }};
 progress(0);let tags;
 if(threads>1)tags=await traceParallel(job,regions,config,threads,progress);
 else{tags=[];for(const r of job.regions){tags.push(await traceOne(r,regions,config));progress(tags.length);}}
 // Expanded background strokes can cover a narrow foreground completely.
 // Paint larger fills first, with deterministic ties across worker counts.
 const paintOrder=job.regions.map((r,i)=>({i,area:r.area??boxArea(r)}));
 if(config.strokeWidth>0)paintOrder.sort((a,b)=>b.area-a.area||a.i-b.i);
 const parts=[`<svg xmlns="http://www.w3.org/2000/svg" width="${job.width}" height="${job.height}" viewBox="0 0 ${job.width} ${job.height}">`,...paintOrder.map(item=>tags[item.i]).filter(Boolean),'</svg>'];
 const count=tags.reduce((n,tag)=>n+(tag.match(/<path\b/g)||[]).length,0);
 if(count>job.limit)throw new Error('Output path budget exceeded');
 fs.writeFileSync(job.output,parts.join('\n'));
}
if(!isMainThread){
 const regions=new Uint16Array(workerData.shared);
 parentPort.on('message',async batch=>{
  try{const results=[];for(const item of batch)results.push({i:item.i,tag:await traceOne(item.r,regions,workerData.config)});parentPort.postMessage({results});}
  catch(e){parentPort.postMessage({error:e.stack||String(e)});}
 });
}else if(require.main===module){main().catch(e=>{console.error(e);process.exitCode=1;});}
module.exports={chooseWorkers};
