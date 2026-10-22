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
  const pingStates = { volunteer: 'Sent', ngo: 'Sent' }, submittedResponses = [];
  let responseHttpStatus = 400, adminRecordsCreated = false;
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
        let body, type, responseCode = 200;
        const apiPath = new URL(request.url).pathname;
        if (request.url.startsWith('http://127.0.0.1:5000/')) {
          const user = {user_id: 1, name: 'Simulated account', role: currentRole, email: 'test@test.invalid'};
          let payload = apiPath === '/profile' ? {success: true, user}
            : apiPath === '/volunteer/tasks' ? {success:true,tasks:[{task_id:1,request_id:1,status:'Proof Submitted',verification_status:'Pending'}]}
            : {success:true,requests:[],reports:[],alerts:[],pings:[],verifications:[],resources:[],locations:[],zones:[],volunteers:[],stats:{}};
          if (apiPath === '/public/stats') payload = {success:true,stats:{total_requests:4,
            active_requests:2,active_volunteers:1,total_volunteers:2,completed:1}};
          if (apiPath === '/weather/live') payload = {success:true,current:{name:'Provider Place',
            sys:{country:'IN'},main:{temp:26,humidity:70},wind:{speed:3.5},
            rain:{'1h':0.6},weather:[{main:'Clouds',description:'scattered clouds'}]}};
          const pingId = currentRole === 'ngo' ? 8 : 7;
          if (apiPath === '/preparedness/my-pings' && currentRole in pingStates) {
            payload.pings = [{ping_id:pingId,status:pingStates[currentRole],alert_type:'Storm',severity:'Watch',description:'Unverified fixture advisory'}];
          } else if (apiPath.startsWith('/preparedness/ping/') && request.method === 'PUT') {
            const submitted = JSON.parse(request.postData || '{}');
            submittedResponses.push({role:currentRole,id:Number(apiPath.split('/').at(-1)),status:submitted.status});
            const valid = ['Acknowledged','Unavailable'].includes(submitted.status)
              && apiPath.endsWith('/'+pingId);
            responseCode = valid ? responseHttpStatus : 400;
            payload = {success:true,ping:{ping_id:pingId,status:submitted.status},message:'Fixture acknowledgement rejected'};
            if (responseCode === 200) pingStates[currentRole] = submitted.status;
          } else if (apiPath === '/alerts' && currentRole === 'admin') {
            payload.alerts = [1,2].map(alert_id=>({alert_id,alert_type:'Storm',severity:'Watch',description:'Unverified fixture advisory'}));
          } else if (/^\/alerts\/\d+\/notify$/.test(apiPath) && request.method === 'PUT') {
            const first = apiPath.includes('/1/');
            responseCode = first ? 200 : 503;
            const each = first ? (adminRecordsCreated ? 0 : 1) : 100;
            payload = {success:true,pings_created:each*2,by_role:{volunteer:each,ngo:each},
              already_recorded:adminRecordsCreated?2:0,message:'Fixture notification store unavailable'};
            if (first) adminRecordsCreated = true;
          }
          body = JSON.stringify(payload); type = 'application/json';
        } else { body = ''; type = request.url.includes('.css') ? 'text/css' : 'application/javascript'; }
        const action = send('Fetch.fulfillRequest', { requestId, responseCode,
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
    const waitFor = async expression => {
      for (let n=0;n<100;n++) { if (await evaluate(expression)) return true; await delay(50); }
      return false;
    };
    await send('Page.navigate',{url:origin+'/index.html'});
    assert.ok(await waitFor(`document.getElementById('hero-stat-requests')?.textContent === '2'`));
    assert.ok(await waitFor(`document.getElementById('weather-rainfall')?.textContent === '0.6 mm'`),
      'weather observation did not render');
    assert.ok(await waitFor(`!!document.getElementById('resq-chat-toggle')`));
    await evaluate(`document.getElementById('resq-chat-toggle').click()`);
    for (const width of [390, 1280]) {
      await send('Emulation.setDeviceMetricsOverride', {width,height:900,deviceScaleFactor:1,mobile:false});
      await delay(80);
      const layout = await evaluate(`(() => {
        const bounds = selector => { const r=document.querySelector(selector).getBoundingClientRect();
          return {left:r.left,right:r.right,top:r.top,width:r.width}; };
        return {viewport:innerWidth,pageWidth:document.documentElement.scrollWidth,
          chat:bounds('#resq-chat-panel'),
          weather:bounds('.weather-overview'),stats:bounds('.home-stats-grid'),
          first:bounds('.home-stat-card:first-child'),second:bounds('.home-stat-card:nth-child(2)')};
      })()`);
      for (const name of ['chat','weather','stats']) {
        assert.ok(layout[name].left >= -1 && layout[name].right <= width+1,
          name+' must fit '+width+'px viewport: '+JSON.stringify(layout));
      }
      assert.ok(layout.pageWidth <= width+1,
        'homepage must not scroll horizontally at '+width+'px: '+JSON.stringify(layout));
      assert.equal(width===390, layout.second.top > layout.first.top,
        'statistics cards should stack only on the phone viewport');
    }
    await evaluate(`document.querySelector('.resq-chat-close').click()`);
    console.log('PASS browser: homepage weather, database counts and chat fit phone and desktop');
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
      assert.ok(await waitFor(`!!document.getElementById('resq-chat-toggle')`), 'Shared guidance widget did not load');
      if (role === 'reporter') {
        await evaluate(`document.getElementById('resq-chat-toggle').click()`);
        assert.equal(await evaluate(`document.getElementById('resq-chat-panel').hidden`), false);
        assert.match(await evaluate(`document.querySelector('.resq-chat-notice').textContent`), /SOS is submitted only after/);
        await evaluate(`document.querySelector('.resq-chat-header button').click()`);
        assert.equal(await evaluate(`document.getElementById('resq-chat-panel').hidden`), true);
      }
      for (const width of [390, 768, 1280]) {
        await send('Emulation.setDeviceMetricsOverride', {width,height:900,deviceScaleFactor:1,mobile:false});
        const layout = await evaluate(`(() => {
          const content = document.querySelector('.dashboard-content').getBoundingClientRect();
          const toggle = document.getElementById('sidebar-toggle-btn');
          return {width: innerWidth, left: content.left, right: content.right,
            toggleVisible: getComputedStyle(toggle).display !== 'none'};
        })()`);
        assert.equal(layout.width,width,role+' viewport width');
        assert.ok(layout.left >= -1 && layout.right <= width+1,
          role+' content must fit '+width+'px viewport: '+JSON.stringify(layout));
        assert.equal(layout.toggleVisible,width<=768,role+' mobile navigation at '+width+'px');
        if (width===390) {
          await evaluate(`document.getElementById('sidebar-toggle-btn').click()`);
          assert.equal(await evaluate(`document.getElementById('resq-sidebar').classList.contains('open')`),true);
          await evaluate(`document.getElementById('sidebar-overlay').click()`);
          assert.equal(await evaluate(`document.getElementById('resq-sidebar').classList.contains('open')`),false);
        }
      }
      console.log('PASS browser: '+role+' dashboard fits phone, tablet and desktop; mobile menu opens/closes');
      if (role==='volunteer') {
        for (let n=0;n<100;n++) {
          if ((await evaluate(`document.getElementById('tasks-tbody').textContent`)).includes('Pending Admin')) break;
          await delay(50);
        }
        assert.match(await evaluate(`document.getElementById('tasks-tbody').textContent`), /Pending Admin/);
      }
      if (role==='volunteer' || role==='ngo') {
        const banner = role==='volunteer' ? 'ping-banner' : 'preparedness-banner';
        const pingId = role==='ngo' ? 8 : 7;
        responseHttpStatus = role==='volunteer' ? 400 : 503;
        assert.ok(await waitFor(`!!document.querySelector('[data-ping-id="${pingId}"]')`));
        await evaluate(`document.querySelector('[data-ping-id="${pingId}"]').click()`);
        assert.ok(await waitFor(`!![...document.querySelectorAll('.toast-msg')].find(t=>t.textContent.includes('Fixture acknowledgement rejected'))`));
        assert.match(await evaluate(`document.getElementById('${banner}').textContent`), /Awaiting your response/);
        assert.equal(await evaluate(`!!document.querySelector('.toast-msg.success')`),false);
        responseHttpStatus = 200;
        await evaluate(`document.querySelector('[data-ping-id="${pingId}"]').click()`);
        assert.ok(await waitFor(`document.getElementById('${banner}')?.textContent.includes('Response saved: Acknowledged')`));
        await send('Page.reload');
        assert.ok(await waitFor(`document.getElementById('${banner}')?.textContent.includes('Response saved: Acknowledged')`));
        assert.equal(await evaluate(`document.querySelectorAll('[data-ping-id="${pingId}"]').length`),0);
        assert.ok(submittedResponses.filter(r=>r.role===role).every(r=>r.id===pingId && r.status==='Acknowledged'));
        console.log('PASS browser: '+role+' failed acknowledgement remains pending; saved response survives reload');
      }
      if (role==='admin') {
        await evaluate(`showSection('preparedness');document.querySelector('button[onclick="notifyAllResponders()"]').click()`);
        assert.ok(await waitFor(`!![...document.querySelectorAll('.toast-msg.warning')].find(t=>t.textContent.includes('2 new in-app alert records (1 volunteer, 1 NGO)'))`));
        const summary = await evaluate(`[...document.querySelectorAll('.toast-msg.warning')].find(t=>t.textContent.includes('2 new in-app alert records')).textContent`);
        assert.match(summary,/1 advisories failed or unconfirmed/);
        assert.match(summary,/No external delivery or acknowledgement confirmed/);
        assert.equal(await evaluate(`!!document.querySelector('.toast-msg.success')`),false);
        console.log('PASS browser: admin bulk control reports persisted mixed-role counts and partial failure');
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
    if (path.dirname(path.resolve(profile)) === path.resolve(os.tmpdir()) && path.basename(profile).startsWith('resqnet-rbac-')) {
      for (let n = 0; n < 20; n++) {
        try { fs.rmSync(profile, { recursive: true, force: true }); break; } catch (_) { await delay(100); }
      }
    }
  }
}
const watchdog = setTimeout(() => { console.error('RBAC browser smoke timed out'); process.exit(1); }, 55000);
main().then(() => clearTimeout(watchdog), error => { clearTimeout(watchdog); console.error(error); process.exitCode = 1; });
