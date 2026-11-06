// Exercise the actual browser-side migration function without a browser/server.
const assert=require('assert'),fs=require('fs'),path=require('path'),vm=require('vm');
const source=fs.readFileSync(path.join(__dirname,'../app/app.js'),'utf8');
const start=source.indexOf('function normalizeImportedConfig(');
const end=source.indexOf('function getConfig(',start);
assert(start>=0&&end>start,'configuration normalizer must be present');
const retiredEngineFields=['colormode','hierarchical','mode','filter_speckle','color_precision','layer_difference','corner_threshold','length_threshold','max_iterations','splice_threshold','path_precision'];
const context={retiredEngineFields};vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
const normalize=config=>context.normalizeImportedConfig(config);
const plain=value=>JSON.parse(JSON.stringify(value));
for(const config of [{engine:'vtracer'},{mode:'polygon'},{color_precision:7},{engine:'vtracer',illustration_profile:'edge_clean'}]){
 assert.throws(()=>normalize(config),/VTracer 支持已移除/);
}
for(const config of [null,[],false])assert.throws(()=>normalize(config),/JSON 对象/);
const mixed={engine:'potrace',path_limit:37,mode:'polygon',color_precision:'ignored retired value'};
assert.deepStrictEqual(plain(normalize(mixed)),{engine:'potrace',path_limit:37});
assert.equal(mixed.mode,'polygon','normalization must not mutate imported configuration');
assert.deepStrictEqual(plain(normalize({illustration_profile:'gradient_layers',path_limit:80,mode:'polygon'})),{illustration_profile:'gradient_layers',path_limit:80});
assert.deepStrictEqual(plain(normalize({engine:'unknown',path_limit:80})),{engine:'unknown',path_limit:80},'unknown engine remains for schema rejection');
assert.deepStrictEqual(plain(normalize({mystery:4})),{mystery:4},'unknown keys remain for schema rejection');
assert.deepStrictEqual(plain(normalize({})),{});
console.log('Configuration migration: retired routes rejected; valid Potrace settings preserved.');
