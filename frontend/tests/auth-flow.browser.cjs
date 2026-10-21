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
  let demoRequestId, demoTaskId;
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
        if ('${role}' === 'volunteer') document.getElementById('reg-availability').value='unavailable';
        document.getElementById('register-form').requestSubmit();
      })()`);
      await waitFor(`location.pathname.endsWith('/${page}-dashboard.html') && typeof Session!=='undefined' && Session.role()==='${role}' && document.querySelector('.sidebar-user-role')?.textContent==='${label}'`, role+' registration did not reach correct dashboard');
      const registered=await evaluate(`(async()=>{const p=await Api.get('/profile');return {role:p.user.role,volunteer:!!p.user.volunteer};})()`);
      assert.equal(registered.role,role);
      if(role==='volunteer') {
        assert.equal(await evaluate(`(async()=>{const p=await Api.get('/profile');return p.user.volunteer?.availability_status==='unavailable' && document.getElementById('vol-status-select').value==='unavailable';})()`),true);
        assert.equal(await evaluate(`(async()=>{const d=await Api.get('/volunteer/tasks');return d.success && Array.isArray(d.tasks);})()`),true);
        assert.equal(await evaluate(`(async()=>{const d=await Api.put('/volunteer/update-location',{latitude:0,longitude:0});return d.success && d.volunteer.last_location_lat===0 && d.volunteer.last_location_lng===0;})()`),true);
        await send('Page.navigate',{url:origin+'/volunteer-dashboard.html'});
        await waitFor(`document.readyState==='complete' && typeof volunteerLat!=='undefined' && volunteerLat===0 && volunteerLng===0 && document.getElementById('vol-status-select')?.value==='unavailable'`, 'Saved volunteer GPS/readiness did not survive reload with permission denied');
      }
      if(role==='ngo') {
        assert.equal(await evaluate(`(async()=>{const s=document.getElementById('ngo-status-select');s.value='unavailable';await updateNGOStatusSelect(s);const p=await Api.get('/profile');return p.user.availability==='unavailable';})()`),true);
        await send('Page.navigate',{url:origin+'/ngo-dashboard.html'});
        await waitFor(`document.readyState==='complete' && document.getElementById('ngo-status-select')?.value==='unavailable'`, 'NGO readiness did not survive reload');
      }
      await logout();
      // A stale role key alone must not influence a fresh login response.
      await evaluate(`localStorage.setItem('resqnet_role','reporter');document.getElementById('login-email').value='${role}@test.invalid';document.getElementById('login-password').value='isolated-browser-password';document.getElementById('login-form').requestSubmit();`);
      await waitFor(`location.pathname.endsWith('/${page}-dashboard.html') && typeof Session!=='undefined' && Session.role()==='${role}' && document.querySelector('.sidebar-user-role')?.textContent==='${label}'`, role+' login did not reach correct dashboard');
      assert.equal(await evaluate(`(async()=>{const p=await Api.get('/profile');return p.user.role;})()`),role);
      if(role==='volunteer') {
        assert.equal(await evaluate(`(async()=>{const p=await Api.get('/profile');return p.user.volunteer?.availability_status==='unavailable' && p.user.volunteer?.last_location_lat===0 && document.getElementById('vol-status-select').value==='unavailable';})()`),true);
        await send('Page.navigate',{url:origin+'/user-dashboard.html'});
        await waitFor(`location.pathname.endsWith('/volunteer-dashboard.html') && typeof Session!=='undefined' && Session.role()==='volunteer'`, 'Wrong-dashboard guard failed');
        if (!warmCache) {
          assert.equal(await evaluate(`(async()=>{
            const select=document.getElementById('vol-status-select');select.value='available';
            await updateVolunteerStatusSelect(select);
            const location=await Api.put('/volunteer/update-location',{latitude:12.9716,longitude:77.5946});
            return select.value==='available' && location.success;
          })()`),true);
          await send('Page.reload');
          await waitFor(`document.querySelector('.request-card button[onclick="acceptTask(${demoRequestId})"]')`, 'Nearby SOS was not offered to volunteer');
          await evaluate(`document.querySelector('.request-card button[onclick="acceptTask(${demoRequestId})"]').click()`);
          await waitFor(`document.getElementById('tasks-tbody')?.textContent.includes('Mark En Route')`, 'Volunteer acceptance did not create assignment');
          demoTaskId = await evaluate(`(async()=>{const data=await Api.get('/volunteer/tasks');return data.tasks[0].task_id;})()`);
          assert.ok(Number.isInteger(demoTaskId));
          await evaluate(`document.querySelector('#tasks-tbody button').click()`);
          await waitFor(`document.getElementById('tasks-tbody')?.textContent.includes('Mark On Site')`, 'En Route transition did not render');
          await evaluate(`document.querySelector('#tasks-tbody button').click()`);
          await waitFor(`document.getElementById('tasks-tbody')?.textContent.includes('On Site')`, 'On Site transition did not render');
          await evaluate(`(async () => {
            const canvas=document.createElement('canvas');canvas.width=2;canvas.height=2;
            const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
            const transfer=new DataTransfer();transfer.items.add(new File([blob],'proof.png',{type:'image/png'}));
            document.getElementById('proof_img_${demoTaskId}').files=transfer.files;
            document.getElementById('proof_notes_${demoTaskId}').value='Synthetic browser completion';
            document.querySelector('#tasks-tbody form').requestSubmit();
          })()`);
          await delay(300);
          const proofState = await evaluate(`(async()=>{
            const data=await Api.get('/volunteer/tasks');
            return {status:data.tasks[0]?.status,
              notices:[...document.querySelectorAll('.toast-msg')].map(t=>t.textContent)};
          })()`);
          assert.equal(proofState.status,'Proof Submitted',JSON.stringify(proofState));
          await waitFor(`document.getElementById('tasks-tbody')?.textContent.includes('Pending Admin')`, 'Proof submission did not await admin');
          console.log('PASS real browser/API: volunteer accepted, progressed and submitted proof');
        }
      }
      if (role === 'ngo') {
        assert.equal(await evaluate(`(async()=>{const p=await Api.get('/profile');return p.user.availability==='unavailable' && document.getElementById('ngo-status-select').value==='unavailable';})()`),true);
        if (!warmCache) {
          assert.ok(await evaluate(`document.getElementById('alloc-request').innerHTML.includes('value="${demoRequestId}"')`),
            'Active assigned SOS should remain available for NGO allocation');
          await evaluate(`(async()=>{
            document.getElementById('res-name').value='Synthetic water';
            document.getElementById('res-category').value='Food';
            document.getElementById('res-quantity').value='4';
            document.getElementById('res-unit').value='cases';
            document.getElementById('res-location').value='Fixture store';
            await addResource();
          })()`);
          const resourceId = await evaluate(`(async()=>{const data=await Api.get('/ngo/resources');return data.resources[0].resource_id;})()`);
          await evaluate(`(async()=>{
            editResource(${resourceId});
            document.getElementById('edit-resource-quantity').value='6';
            document.getElementById('edit-resource-location').value='Updated fixture store';
            await saveResourceEdit();
            document.getElementById('alloc-resource').value='${resourceId}';
            document.getElementById('alloc-request').value='${demoRequestId}';
            await allocateResource();
          })()`);
          assert.equal(await evaluate(`(async()=>{const d=await Api.get('/ngo/resources');return d.resources[0].quantity===6 && d.resources[0].allocated_to===${demoRequestId};})()`),true);
          await send('Page.reload');
          await waitFor(`document.getElementById('inventory-tbody')?.textContent.includes('Updated fixture store')`, 'NGO inventory did not survive reload');
          console.log('PASS real browser/API: NGO created, edited, allocated and reloaded inventory');
        }
      }
      if (role === 'reporter') {
        // The reported manual-URL redirect is correct for a reporter, even if
        // its cached user object is modified to claim volunteer privileges.
        await evaluate(`const cached=Session.get();cached.role='volunteer';localStorage.setItem('resqnet_user',JSON.stringify(cached));localStorage.setItem('resqnet_role','volunteer');`);
        await send('Page.navigate', {url:origin+'/volunteer-dashboard.html'});
        await waitFor(`location.pathname.endsWith('/user-dashboard.html') && typeof Session!=='undefined' && Session.role()==='reporter'`, 'Reporter entered the volunteer page despite the database role');
        if (!warmCache) {
          await send('Page.navigate', {url:origin+'/help-request.html'});
          await waitFor(`document.readyState==='complete' && typeof setLocationFields==='function'`, 'SOS form did not load');
          await evaluate(`(() => {
            document.getElementById('req-name').value='Browser fixture';
            document.getElementById('req-contact').value='0000000000';
            document.getElementById('request-type').value='Rescue';
            document.getElementById('people-count').value='2';
            document.getElementById('req-description').value='Synthetic browser rescue';
            setLocationFields(12.9716, 77.5946, 'Synthetic browser location');
            document.getElementById('help-form').requestSubmit();
          })()`);
          await waitFor(`document.getElementById('success-state')?.style.display==='flex'`, 'Real SOS form did not submit');
          demoRequestId = await evaluate(`(async()=>{const data=await Api.get('/help-requests');return data.requests[0].request_id;})()`);
          assert.ok(Number.isInteger(demoRequestId));
          console.log('PASS real browser/API: citizen SOS form created a private request');
        }
      }
      if (role === 'admin' && !warmCache) {
        await waitFor(`document.getElementById('verifications-tbody')?.textContent.includes('Synthetic browser completion')`, 'Admin did not see pending proof');
        await waitFor(`document.getElementById('admin-users-tbody')?.textContent.includes('Browser fixture')`, 'Admin users did not load');
        await waitFor(`document.getElementById('admin-resources-tbody')?.textContent.includes('Synthetic water')`, 'Admin resources did not load');
        await evaluate(`document.querySelector('#verifications-tbody button[onclick^="viewTaskProof"]').click()`);
        await waitFor(`!!document.querySelector('dialog[open] img')`, 'Admin could not open protected proof');
        await evaluate(`document.querySelector('dialog[open] button').click();window.confirm=()=>true;
          document.querySelector('#verifications-tbody button[onclick*="Approve"]').click()`);
        await waitFor(`document.getElementById('verifications-tbody')?.textContent.includes('No pending verifications')`, 'Admin approval did not clear pending proof');
        assert.equal(await evaluate(`(async()=>{const d=await Api.get('/admin/requests');return d.requests.find(r=>r.request_id===${demoRequestId})?.status;})()`),'Completed');
        console.log('PASS real browser/API: admin viewed private proof and approved completion');
      }
      await logout();
      console.log('PASS real auth browser: '+role+' registration, database profile, login redirect, dashboard and logout');
    }
    if (!warmCache) {
      await evaluate(`(() => {
        document.getElementById('login-email').value='reporter@test.invalid';
        document.getElementById('login-password').value='isolated-browser-password';
        document.getElementById('login-form').requestSubmit();
      })()`);
      await waitFor(`location.pathname.endsWith('/user-dashboard.html') && document.getElementById('requests-tbody')?.textContent.includes('Completed')`,
        'Citizen dashboard did not show approved completion');
      assert.equal(await evaluate(`(async()=>{const d=await Api.get('/help-request/${demoRequestId}');return d.request.status;})()`),'Completed');
      await logout();
      console.log('PASS real browser/API: citizen re-login shows completed rescue');
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
