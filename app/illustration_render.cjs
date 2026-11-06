'use strict';
// All dependencies are shipped with the project; no user cache or system Node.
const path = require('path');
const sharp = require(path.join(__dirname, '../runtime/potrace/node_modules/sharp'));
const [input, output] = process.argv.slice(2);
sharp(input).ensureAlpha().png().toFile(output).catch(error => {
  console.error(error);
  process.exitCode = 1;
});
