const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const sharp=require('../../tests/node_test_dependencies.cjs')('sharp', __filename);
const root=path.resolve(__dirname,'../..'),publicDir=path.join(root,'outputs/illustration-blind-review-round2');
const sandbox={window:{}};vm.runInNewContext(fs.readFileSync(path.join(publicDir,'data.js'),'utf8'),sandbox);
(async()=>{
  const results=[];
  for(const c of sandbox.window.REVIEW_DATA.cases){
    for(const v of c.candidates){
      const actual=await sharp(path.join(publicDir,v.svg)).resize({width:720,withoutEnlargement:true}).flatten({background:'#ffffff'}).ensureAlpha().raw().toBuffer({resolveWithObject:true});
      const expected=await sharp(path.join(publicDir,v.preview)).ensureAlpha().raw().toBuffer({resolveWithObject:true});
      if(actual.info.width!==expected.info.width || actual.info.height!==expected.info.height || !actual.data.equals(expected.data))throw new Error('Rendering mismatch '+c.id+'-'+v.id);
      results.push(c.id+'-'+v.id);
    }
    console.log('Render verified: '+c.id);
  }
  fs.writeFileSync(path.join(root,'outputs/illustration-round2-study/render-validation.json'),JSON.stringify({verified:results.length,identical_to_original_previews:true,candidates:results},null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
