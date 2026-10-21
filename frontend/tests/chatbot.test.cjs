const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
  const nodes = [];
  const make = tag => {
    const node = { tag, children: [], attributes: {}, listeners: {}, textContent: '',
      hidden: false, value: '', disabled: false, scrollHeight: 0, focus() { this.focused = true; },
      setAttribute(k, v) { this.attributes[k] = v; },
      addEventListener(k, fn) { this.listeners[k] = fn; },
      append(...items) { this.children.push(...items); },
      appendChild(item) { this.children.push(item); } };
    nodes.push(node); return node;
  };
  const body = make('body');
  const document = { readyState: 'complete', body, createElement: make,
    getElementById: id => nodes.find(n => n.id === id) };
  const calls = [];
  const Api = { BASE: 'https://api.example.invalid', async fetchWithTimeout(url, options) {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ success: true, reply: 'Use the confirmed SOS form.' }) };
  } };
  const context = { document, Api };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../js/chatbot.js'), 'utf8'), context);
  return { nodes, calls, Api, find: id => document.getElementById(id) };
}

test('floating guidance chat opens, sends bounded history and closes accessibly', async () => {
  const s = setup();
  const toggle = s.find('resq-chat-toggle'), panel = s.find('resq-chat-panel');
  const input = s.find('resq-chat-input');
  const form = s.nodes.find(n => n.tag === 'form');
  assert.equal(panel.hidden, true);
  toggle.listeners.click();
  assert.equal(panel.hidden, false);
  assert.equal(toggle.attributes['aria-expanded'], 'true');
  assert.equal(input.focused, true);
  input.value = '<script>alert(1)</script>';
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(s.calls[0].url, 'https://api.example.invalid/api/chat');
  assert.equal(JSON.parse(s.calls[0].options.body).message, '<script>alert(1)</script>');
  const log = s.nodes.find(n => n.attributes.role === 'log');
  assert.equal(log.children[0].children[0].textContent, '<script>alert(1)</script>');
  assert.equal(log.children[0].children[0].innerHTML, undefined);
  assert.equal(log.children[1].children[0].textContent, 'Use the confirmed SOS form.');
  assert.ok(log.children[0].children[1].dateTime);
  assert.equal(s.nodes.find(n => n.className === 'resq-chat-empty').hidden, true);
  for (let i = 0; i < 5; i++) {
    input.value = `Question ${i}`;
    await form.listeners.submit({ preventDefault() {} });
  }
  assert.equal(JSON.parse(s.calls.at(-1).options.body).history.length, 8);
  panel.listeners.keydown({ key: 'Escape' });
  assert.equal(panel.hidden, true);
  assert.equal(toggle.attributes['aria-expanded'], 'false');
  assert.equal(toggle.focused, true);
});

test('suggested questions prefill without sending and typing is visible only while pending', async () => {
  const s = setup();
  const suggestion = s.nodes.find(n => n.className === 'resq-chat-suggestions').children[0];
  suggestion.listeners.click();
  assert.equal(s.find('resq-chat-input').value, 'How do I submit an SOS?');
  assert.equal(s.calls.length, 0);
  let resolveRequest;
  s.Api.fetchWithTimeout = () => new Promise(resolve => { resolveRequest = resolve; });
  const pending = s.nodes.find(n => n.tag === 'form').listeners.submit({ preventDefault() {} });
  const typing = s.nodes.find(n => n.className === 'resq-chat-typing');
  assert.equal(typing.hidden, false);
  assert.equal(s.nodes.find(n => n.attributes.role === 'log').attributes['aria-busy'], 'true');
  resolveRequest({ ok: true, json: async () => ({ success: true, reply: 'Open the SOS form.' }) });
  await pending;
  assert.equal(typing.hidden, true);
  assert.equal(s.nodes.find(n => n.attributes.role === 'log').attributes['aria-busy'], 'false');
});

test('failed chat keeps safety notice and clears loading state without a false reply', async () => {
  const s = setup();
  s.Api.fetchWithTimeout = async () => ({ ok: false, json: async () => ({ success: false, message: 'Busy' }) });
  const input = s.find('resq-chat-input');
  input.value = 'Is help dispatched?';
  const form = s.nodes.find(n => n.tag === 'form');
  await form.listeners.submit({ preventDefault() {} });
  assert.equal(s.nodes.find(n => n.tag === 'p' && n.attributes.role === 'status').textContent.includes('unavailable'), true);
  assert.equal(s.nodes.find(n => n.tag === 'div' && n.attributes.role === 'log').children.length, 1);
  assert.equal(s.nodes.find(n => n.tag === 'p' && n.className === 'resq-chat-notice').textContent.includes('only after'), true);
  assert.equal(input.disabled, false);
});

test('provider throttling is shown as busy without asserting emergency action', async () => {
  const s = setup();
  s.Api.fetchWithTimeout = async () => ({ ok: false, status: 429,
    json: async () => ({ success: false, message: 'Chat is busy.' }) });
  s.find('resq-chat-input').value = 'Send help';
  await s.nodes.find(n => n.tag === 'form').listeners.submit({ preventDefault() {} });
  assert.match(s.nodes.find(n => n.className === 'resq-chat-status').textContent, /busy/);
  assert.doesNotMatch(s.nodes.find(n => n.className === 'resq-chat-status').textContent, /submitted|dispatched/);
});

test('shared website script loads chat widget without editing individual pages', () => {
  const root = path.join(__dirname, '..');
  const main = fs.readFileSync(path.join(root, 'js/main.js'), 'utf8');
  assert.match(main, /chatbotScript\.src = 'js\/chatbot\.js'/);
  for (const page of fs.readdirSync(root).filter(x => x.endsWith('.html'))) {
    const html = fs.readFileSync(path.join(root, page), 'utf8');
    assert.match(html, /js\/main\.js/, `${page} is missing shared chat loader`);
  }
});
