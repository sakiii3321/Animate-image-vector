'use strict';
const path = require('node:path');

function tryResolve(name, options) {
  try { return require.resolve(name, options); }
  catch (error) {
    if (error.code !== 'MODULE_NOT_FOUND') throw error;
    return null;
  }
}

function resolveTestDependency(name, fromFile = __filename) {
  // Prefer the caller's own installation, then test and bundled app dependencies.
  const localDirectories = [path.dirname(path.resolve(fromFile)), __dirname,
    path.resolve(__dirname, '../runtime/potrace')];
  for (const directory of localDirectories) {
    const resolved = tryResolve(name, {paths: [directory]});
    if (resolved) return resolved;
  }

  const moduleDirectories = (process.env.IMAGEVECTOR_TEST_NODE_MODULES || '')
    .split(path.delimiter).map(value => value.trim()).filter(Boolean);
  const home = process.env.USERPROFILE || process.env.HOME;
  if (home) moduleDirectories.push(path.join(home,
    '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'));
  for (const directory of moduleDirectories) {
    const resolved = tryResolve(path.resolve(directory, name));
    if (resolved) return resolved;
  }
  throw new Error(`Missing test dependency "${name}". Install the application dependencies as described in README.md and run npm --prefix tests install, or set IMAGEVECTOR_TEST_NODE_MODULES to a node_modules directory.`);
}

function loadTestDependency(name, fromFile) {
  return require(resolveTestDependency(name, fromFile));
}
module.exports = loadTestDependency;
module.exports.resolve = resolveTestDependency;
