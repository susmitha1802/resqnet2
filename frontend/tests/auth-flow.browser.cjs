// Real auth.html registration/login against a temporary in-memory Flask API.
// No existing accounts or databases are touched. External CDNs are disabled.
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
  const warmCache = process.argv.includes('--warm-cache');
  let warming = warmCache;
  let legacyRequests = 0;
  // Reproduce the pre-fix handler retained under the old, unversioned URL.
  const legacyAuth = fs.readFileSync(path.join(root, 'js/auth.js'), 'utf8')
    .replace("window.selectedRole = 'reporter';", "let selectedRole = 'reporter';")
    .replaceAll('role: window.selectedRole', 'role: selectedRole')
    .replaceAll('if (window.selectedRole', 'if (selectedRole');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'resqnet-auth-flow-'));
  const chrome = process.env.CHROME_BINARY || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  const apiProcess = spawn(process.env.PYTHON_BINARY || path.resolve(root, '../.venv/Scripts/python.exe'),
    [path.resolve(root, '../backend/tests/auth_browser_server.py')],
    {windowsHide:true, stdio:['pipe','pipe','ignore']});
  let startupTimer;
  const apiOrigin = await new Promise((resolve,reject) => {
    let output='';
    startupTimer=setTimeout(()=>{apiProcess.kill();reject(new Error('Temporary API startup timed out'));},10000);
    apiProcess.once('error',reject);
    apiProcess.stdout.on('data', data=>{ output+=data.toString(); if(output.includes('\n')) {
      clearTimeout(startupTimer);resolve(JSON.parse(output.split('\n')[0]).origin);
    }});
  });
  const server = http.createServer((request, response) => {
    const url = new URL(request.url, 'http://local');
    const file = path.resolve(root, '.' + decodeURIComponent(url.pathname));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      response.writeHead(404); response.end(); return;
    }
    response.setHeader('Content-Type', { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css' }[path.extname(file)] || 'application/octet-stream');
    if (warming && url.pathname === '/auth.html') {
      response.setHeader('Cache-Control', 'no-store');
      response.end(fs.readFileSync(file, 'utf8').replace(/src="js\/auth\.js[^\"]*"/, 'src="js/auth.js"'));
      return;
    }
    if (warming && url.pathname === '/js/auth.js' && !url.search) {
      legacyRequests++;
      response.setHeader('Cache-Control', 'public, max-age=31536000');
      response.end(legacyAuth);
      return;
    }
    fs.createReadStream(file).pipe(response);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const origin = `http://127.0.0.1:${server.address().port}`;
  const child = spawn(chrome, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
  let ws, send, nextId = 0;
  const registrationRoles = [];
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
      } else if (message.method === 'Network.requestWillBeSent' && message.params.request.url === apiOrigin+'/register') {
        const payload = message.params.request.postData;
        if (payload) registrationRoles.push(JSON.parse(payload).role);
      } else if (message.method === 'Fetch.requestPaused') {
        const { requestId, request } = message.params;
        let body, type;
        body=''; type=request.url.includes('.css')?'text/css':'application/javascript';
        const action = send('Fetch.fulfillRequest', { requestId, responseCode: 200,
          responseHeaders: [{name:'Content-Type',value:type},{name:'Access-Control-Allow-Origin',value:'*'},
            {name:'Access-Control-Allow-Headers',value:'Content-Type, Authorization'},
            {name:'Access-Control-Allow-Methods',value:'GET, PUT, POST, OPTIONS'}],
          body: Buffer.from(body).toString('base64') });
        action.catch(() => {});
      }
    });
    console.log('Browser connected to temporary real auth API');
    await send('Page.enable');
    await send('Fetch.enable', {patterns:[{urlPattern:'https://*'}]});
    await send('Emulation.setDeviceMetricsOverride', {width:1280,height:900,deviceScaleFactor:1,mobile:false});
    await send('Browser.setPermission', {permission:{name:'geolocation'},setting:'denied',origin});
    await send('Page.addScriptToEvaluateOnNewDocument', {source:
      `window.RESQNET_API_BASE=${JSON.stringify(apiOrigin)};`});
    const evaluate = async expression => {
      const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    const waitFor = async (expression, message) => {
      for (let n=0;n<120;n++) {
        try { if (await evaluate(expression)) return; } catch (_) { /* navigation in progress */ }
        await delay(50);
      }
      const trace = await evaluate(`(async()=>{const p=typeof Api==='undefined'?null:await Api.get('/profile');return {page:location.pathname,profileRole:p?.user?.role};})()`);
      throw new Error(message + '; ' + JSON.stringify(trace));
    };
    const logout = async () => {
      await evaluate('Session.logout()');
      await waitFor(`location.pathname.endsWith('/auth.html') && document.readyState==='complete' && typeof handleLogin==='function'`, 'Logout did not return to auth');
      assert.equal(await evaluate(`['resqnet_user','resqnet_token','resqnet_role'].every(k=>localStorage.getItem(k)===null)`),true);
    };
    if (warmCache) {
      await send('Network.enable');
      await send('Network.setCacheDisabled', {cacheDisabled:false});
      await send('Page.navigate', {url:origin+'/auth.html?warm-cache=1'});
      await waitFor(`document.readyState==='complete' && typeof handleRegister==='function'`, 'Cache warmup failed');
      assert.equal(legacyRequests,1);
      warming=false;
      console.log('Warm cache contains the pre-fix auth.js under its original URL');
    }
    const roles=warmCache ? [['volunteer','volunteer','Volunteer']] : [['reporter','user','Disaster Reporter'],['volunteer','volunteer','Volunteer'],['ngo','ngo','NGO / Organization'],['admin','admin','Administrator']];
    for (const [role,page,label] of roles) {
      await send('Page.navigate',{url:origin+'/auth.html'});
      await waitFor(`document.readyState==='complete' && typeof handleRegister==='function'`, 'Auth page not ready');
      await evaluate(`(() => {
        document.getElementById('tab-register').click();document.getElementById('role-${role}').click();
        const values={'reg-name':'Browser fixture','reg-email':'${role}@test.invalid','reg-phone':'0000000000',
          'reg-password':'isolated-browser-password','reg-confirm':'isolated-browser-password',
          'reg-org-name':'Fixture organization','admin-secret-code':'isolated-browser-registration-only'};
        for(const [id,value] of Object.entries(values))document.getElementById(id).value=value;
        document.getElementById('register-form').requestSubmit();
      })()`);
      await waitFor(`location.pathname.endsWith('/${page}-dashboard.html') && typeof Session!=='undefined' && Session.role()==='${role}' && document.querySelector('.sidebar-user-role')?.textContent==='${label}'`, role+' registration did not reach correct dashboard');
      const registered=await evaluate(`(async()=>{const p=await Api.get('/profile');return {role:p.user.role,volunteer:!!p.user.volunteer};})()`);
      assert.equal(registered.role,role);
      if(role==='volunteer') {
        assert.equal(await evaluate(`(async()=>{const d=await Api.get('/volunteer/tasks');return d.success && Array.isArray(d.tasks);})()`),true);
      }
      await logout();
      // A stale role key alone must not influence a fresh login response.
      await evaluate(`localStorage.setItem('resqnet_role','reporter');document.getElementById('login-email').value='${role}@test.invalid';document.getElementById('login-password').value='isolated-browser-password';document.getElementById('login-form').requestSubmit();`);
      await waitFor(`location.pathname.endsWith('/${page}-dashboard.html') && typeof Session!=='undefined' && Session.role()==='${role}' && document.querySelector('.sidebar-user-role')?.textContent==='${label}'`, role+' login did not reach correct dashboard');
      assert.equal(await evaluate(`(async()=>{const p=await Api.get('/profile');return p.user.role;})()`),role);
      if(role==='volunteer') {
        await send('Page.navigate',{url:origin+'/user-dashboard.html'});
        await waitFor(`location.pathname.endsWith('/volunteer-dashboard.html') && typeof Session!=='undefined' && Session.role()==='volunteer'`, 'Wrong-dashboard guard failed');
      }
      if (role === 'reporter') {
        // The reported manual-URL redirect is correct for a reporter, even if
        // its cached user object is modified to claim volunteer privileges.
        await evaluate(`const cached=Session.get();cached.role='volunteer';localStorage.setItem('resqnet_user',JSON.stringify(cached));localStorage.setItem('resqnet_role','volunteer');`);
        await send('Page.navigate', {url:origin+'/volunteer-dashboard.html'});
        await waitFor(`location.pathname.endsWith('/user-dashboard.html') && typeof Session!=='undefined' && Session.role()==='reporter'`, 'Reporter entered the volunteer page despite the database role');
      }
      await logout();
      console.log('PASS real auth browser: '+role+' registration, database profile, login redirect, dashboard and logout');
    }
    if (warmCache) {
      assert.deepEqual(registrationRoles, ['volunteer']);
      assert.equal(legacyRequests,1,'The old cached asset should not need to be overwritten');
      console.log('PASS warm cache: submitted/stored/profile role=volunteer; cached legacy URL remains unused');
    }
  } finally {
    if (send && ws?.readyState === WebSocket.OPEN) await send('Browser.close').catch(() => {});
    ws?.close();
    if (child.exitCode === null) child.kill();
    await new Promise(resolve => server.close(resolve));
    apiProcess.stdin.end('stop\n');
    await Promise.race([once(apiProcess,'exit'),delay(3000)]);
    if (apiProcess.exitCode===null) apiProcess.kill();
    // Remove only the generated browser profile inside the intended temp directory.
    if (path.dirname(path.resolve(profile)) === path.resolve(os.tmpdir()) && path.basename(profile).startsWith('resqnet-auth-flow-')) {
      for (let n = 0; n < 20; n++) {
        try { fs.rmSync(profile, { recursive: true, force: true }); break; } catch (_) { await delay(100); }
      }
    }
  }
}
const watchdog = setTimeout(() => { console.error('Auth flow browser test timed out'); process.exit(1); }, 55000);
main().then(() => clearTimeout(watchdog), error => { clearTimeout(watchdog); console.error(error); process.exitCode = 1; });
