const sharp=require('../../tests/node_test_dependencies.cjs')('sharp', __filename);
const [input,output]=process.argv.slice(2);
sharp(input).png().toFile(output).catch(error=>{console.error(error);process.exitCode=1;});
