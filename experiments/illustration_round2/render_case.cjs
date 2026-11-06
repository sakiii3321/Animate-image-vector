const path=require('path');
const sharp=require(path.join(__dirname,'../../runtime/potrace/node_modules/sharp'));
const [input,work]=process.argv.slice(2);
(async()=>{
 await sharp(input).png().toFile(path.join(work,'raster.png'));
 await sharp(input).resize({width:720,withoutEnlargement:true}).flatten({background:'#ffffff'}).png().toFile(path.join(work,'preview.png'));
})();
