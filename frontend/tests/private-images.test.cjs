const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('private image viewer sends JWT, rejects paths and revokes blob on close', async () => {
  const calls = [], revoked = [], dialogs = [];
  const document = {
    body: { append(dialog) { dialogs.push(dialog); } },
    createElement(tag) { return { tag, style: {}, children: [], listeners: {},
      append(...nodes) { this.children.push(...nodes); },
      addEventListener(name, fn) { this.listeners[name] = fn; },
      showModal() { this.open = true; }, close() { this.open = false; }, remove() { this.removed = true; } }; }
  };
  const ctx = { window: { RESQNET_API_BASE: 'http://local-api', location: { hostname: '127.0.0.1' } },
    localStorage: { getItem: key => key === 'resqnet_token' ? 'fixture-jwt' : null },
    document, AbortController, setTimeout, clearTimeout, console,
    URL: { createObjectURL: () => 'blob:fixture', revokeObjectURL: url => revoked.push(url) },
    fetch: async (url, options) => { calls.push({ url, options }); return { ok: true,
      blob: async () => ({ type: 'image/png' }) }; } };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../js/api.js'), 'utf8'), ctx);
  const api = vm.runInContext('Api', ctx);
  assert.equal(await api.viewPrivateImage('/help-request/../image'), false);
  assert.equal(calls.length, 0);
  assert.equal(await api.viewPrivateImage('/report/4/image'), true);
  assert.equal(calls[0].url, 'http://local-api/report/4/image');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer fixture-jwt');
  dialogs[0].children[0].listeners.click();
  assert.equal(dialogs[0].removed, true);
  assert.deepEqual(revoked, ['blob:fixture']);
});
