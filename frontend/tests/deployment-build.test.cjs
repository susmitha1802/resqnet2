const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '../..');
const script = path.join(root, 'scripts/build-netlify.cjs');
function cleanup(temp) {
  const target = path.resolve(temp);
  if (path.dirname(target) !== path.resolve(os.tmpdir()) || !path.basename(target).startsWith('resqnet-netlify-')) {
    throw new Error('Temporary test directory is outside the expected root.');
  }
  fs.rmSync(target, { recursive: true, force: true });
}

test('Netlify build inserts only the public HTTPS API origin into a copy', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'resqnet-netlify-'));
  try {
    const output = path.join(temp, 'dist');
    const env = { ...process.env, RESQNET_API_BASE: 'https://api.example.invalid', RESQNET_BUILD_OUTPUT: output };
    const built = spawnSync(process.execPath, [script], { cwd: root, env, encoding: 'utf8' });
    assert.equal(built.status, 0, built.stderr);
    const source = fs.readFileSync(path.join(root, 'frontend/js/api.js'), 'utf8');
    const result = fs.readFileSync(path.join(output, 'js/api.js'), 'utf8');
    assert.match(source, /__RESQNET_API_BASE__/);
    assert.doesNotMatch(result, /__RESQNET_API_BASE__/);
    assert.match(result, /https:\/\/api\.example\.invalid/);
    assert.ok(fs.existsSync(path.join(output, 'auth.html')));
  } finally { cleanup(temp); }
});

test('Netlify build refuses absent or non-HTTPS API configuration', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'resqnet-netlify-'));
  try {
    for (const bad of ['', 'http://api.example.invalid', 'https://api.example.invalid/path']) {
      const output = path.join(temp, 'unused');
      const built = spawnSync(process.execPath, [script], {
        cwd: root, env: { ...process.env, RESQNET_API_BASE: bad, RESQNET_BUILD_OUTPUT: output }, encoding: 'utf8'
      });
      assert.notEqual(built.status, 0);
      assert.equal(fs.existsSync(output), false);
    }
  } finally { cleanup(temp); }
});
