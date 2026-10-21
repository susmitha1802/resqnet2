// Build a static copy; never rewrite the tracked frontend source.
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const frontend = path.join(root, 'frontend');
const output = process.env.RESQNET_BUILD_OUTPUT ? path.resolve(process.env.RESQNET_BUILD_OUTPUT) : path.join(root, 'dist');
if (output === root || output === frontend || output.startsWith(frontend + path.sep)) {
  throw new Error('Build output cannot overwrite the project or frontend source.');
}
const configured = process.env.RESQNET_API_BASE;
let api;
try { api = new URL(configured); }
catch (_) { throw new Error('RESQNET_API_BASE must be an HTTPS backend origin.'); }
if (api.protocol !== 'https:' || api.username || api.password || api.pathname !== '/' || api.search || api.hash) {
  throw new Error('RESQNET_API_BASE must be an HTTPS backend origin.');
}
if (fs.existsSync(output)) throw new Error('dist already exists; review it before rebuilding.');
fs.cpSync(frontend, output, { recursive: true });
const target = path.join(output, 'js', 'api.js');
const source = fs.readFileSync(target, 'utf8');
const marker = "'__RESQNET_API_BASE__'";
if (!source.includes(marker)) throw new Error('Frontend API placeholder is missing.');
fs.writeFileSync(target, source.replace(marker, JSON.stringify(api.origin)), 'utf8');
console.log('Static frontend built with an HTTPS API origin.');
