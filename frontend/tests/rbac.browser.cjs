// RBAC browser smoke: real local dashboard HTML/JS, simulated accounts and APIs.
// Temporary Chrome profile; no real login, database writes or external services.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { setTimeout: delay } = require('node:timers/promises');

async function main() {
  const root = path.resolve(__dirname, '..');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'resqnet-rbac-'));
  const chrome = process.env.CHROME_BINARY || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  const server = http.createServer((request, response) => {
    const file = path.resolve(root, '.' + decodeURIComponent(new URL(request.url, 'http://local').pathname));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      response.writeHead(404); response.end(); return;
    }
    response.setHeader('Content-Type', { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css' }[path.extname(file)] || 'application/octet-stream');
    fs.createReadStream(file).pipe(response);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const origin = `http://127.0.0.1:${server.address().port}`;
  const child = spawn(chrome, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
  let ws, send, nextId = 0, currentRole = 'reporter';
  const pending = new Map();
  try {
    const activePort = path.join(profile, 'DevToolsActivePort');
    let port;
    for (let n = 0; n < 100; n++) {
      try { port = fs.readFileSync(activePort, 'utf8').split('\n')[0]; } catch (error) {
        if (!['ENOENT', 'EBUSY'].includes(error.code)) throw error;
      }
      if (/^\d+$/.test(port || '')) break;
      await delay(100);
    }
    assert.match(port || '', /^\d+$/, 'Chrome debugging endpoint did not start');
    const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    ws = new WebSocket(pages.find(target => target.type === 'page').webSocketDebuggerUrl);
    await once(ws, 'open');
    send = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++nextId;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error('CDP timed out: '+method)); }, 8000);
      pending.set(id, { resolve: value => {clearTimeout(timer);resolve(value);}, reject: error => {clearTimeout(timer);reject(error);} });
      ws.send(JSON.stringify({ id, method, params }));
    });
    ws.addEventListener('message', ({ data }) => {
      const message = JSON.parse(data);
      if (message.id) {
        const task = pending.get(message.id);
        pending.delete(message.id);
        if (message.error) task?.reject(new Error(message.error.message)); else task?.resolve(message.result);
      } else if (message.method === 'Fetch.requestPaused') {
        const { requestId, request } = message.params;
        let body, type;
        const apiPath = new URL(request.url).pathname;
        if (request.url.startsWith('http://127.0.0.1:5000/')) {
          const user = {user_id: 1, name: 'Simulated account', role: currentRole, email: 'test@test.invalid'};
          const payload = apiPath === '/profile' ? {success: true, user}
            : apiPath === '/volunteer/tasks' ? {success:true,tasks:[{task_id:1,request_id:1,status:'Proof Submitted',verification_status:'Pending'}]}
            : {success:true,requests:[],reports:[],alerts:[],pings:[],verifications:[],resources:[],locations:[],zones:[],volunteers:[],stats:{}};
          body = JSON.stringify(payload); type = 'application/json';
        } else { body = ''; type = request.url.includes('.css') ? 'text/css' : 'application/javascript'; }
        const action = send('Fetch.fulfillRequest', { requestId, responseCode: 200,
          responseHeaders: [{name:'Content-Type',value:type},{name:'Access-Control-Allow-Origin',value:'*'},
            {name:'Access-Control-Allow-Headers',value:'Content-Type, Authorization'},
            {name:'Access-Control-Allow-Methods',value:'GET, PUT, POST, OPTIONS'}],
          body: Buffer.from(body).toString('base64') });
        action.catch(() => {});
      }
    });
    console.log('Browser connected; testing simulated accounts');
    await send('Page.enable');
    await send('Fetch.enable', {patterns:[{urlPattern:'http://127.0.0.1:5000/*'},{urlPattern:'https://*'}]});
    await send('Emulation.setDeviceMetricsOverride', {width:1280,height:900,deviceScaleFactor:1,mobile:false});
    await send('Browser.setPermission', {permission:{name:'geolocation'},setting:'denied',origin});
    const simulatedToken = 'test.' + Buffer.from(JSON.stringify({exp:Math.floor(Date.now()/1000)+3600})).toString('base64') + '.test';
    await send('Page.addScriptToEvaluateOnNewDocument', {source:
      `window.RESQNET_API_BASE='http://127.0.0.1:5000';localStorage.setItem('resqnet_user',JSON.stringify({user_id:1,name:'Stale account',role:'reporter'}));localStorage.setItem('resqnet_token',${JSON.stringify(simulatedToken)});localStorage.setItem('resqnet_role','reporter');`});
    const evaluate = async expression => {
      const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    for (const [role, page, label] of [['reporter','user','Disaster Reporter'],['volunteer','volunteer','Volunteer'],['ngo','ngo','NGO / Organization'],['admin','admin','Administrator']]) {
      currentRole=role; console.log('Checking browser role: '+role);
      await send('Page.navigate',{url:`${origin}/${page}-dashboard.html`});
      let verified=false;
      for (let n=0;n<100;n++) {
        verified=await evaluate(`typeof Session !== 'undefined' && Session.role() === '${role}' && document.querySelector('.sidebar-user-role')?.textContent === '${label}'`);
        if (verified) break;
        await delay(50);
      }
      assert.equal(verified,true,role+' dashboard did not verify its server role');
      if (role==='volunteer') {
        for (let n=0;n<100;n++) {
          if ((await evaluate(`document.getElementById('tasks-tbody').textContent`)).includes('Pending Admin')) break;
          await delay(50);
        }
        assert.match(await evaluate(`document.getElementById('tasks-tbody').textContent`), /Pending Admin/);
      }
      console.log('PASS browser: '+role+' dashboard uses authenticated role'+(role==='volunteer'?' and displays assigned proof task':''));
    }
    currentRole='volunteer';
    await send('Page.navigate',{url:origin+'/user-dashboard.html'});
    for (let n=0;n<100;n++) {
      if (await evaluate(`location.pathname.endsWith('/volunteer-dashboard.html') && typeof Session !== 'undefined' && Session.role()==='volunteer'`)) break;
      await delay(50);
    }
    assert.equal(await evaluate(`location.pathname.endsWith('/volunteer-dashboard.html')`),true);
    console.log('PASS browser: volunteer visiting citizen dashboard redirects to volunteer dashboard');
  } finally {
    if (send && ws?.readyState === WebSocket.OPEN) await send('Browser.close').catch(() => {});
    ws?.close();
    if (child.exitCode === null) child.kill();
    await new Promise(resolve => server.close(resolve));
    // Remove only the generated browser profile inside the intended temp directory.
    if (path.dirname(path.resolve(profile)) === path.resolve(os.tmpdir()) && path.basename(profile).startsWith('resqnet-location-')) {
      for (let n = 0; n < 20; n++) {
        try { fs.rmSync(profile, { recursive: true, force: true }); break; } catch (_) { await delay(100); }
      }
    }
  }
}
const watchdog = setTimeout(() => { console.error('RBAC browser smoke timed out'); process.exit(1); }, 55000);
main().then(() => clearTimeout(watchdog), error => { clearTimeout(watchdog); console.error(error); process.exitCode = 1; });
