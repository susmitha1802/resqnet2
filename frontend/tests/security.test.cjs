const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const attack='<img src=x onerror="alert(1)">';
function setup(file){
  const elements=new Map();
  const context={window:{},console,setTimeout(){},timeAgo:()=>'',priorityBadge:()=>'',statusBadge:()=>'',
    Api:{get:async()=>({})},document:{addEventListener(){},querySelectorAll:()=>[],
      getElementById(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',appendChild(el){this.lastChild=el;}});return elements.get(id);},
      createElement:()=>({innerHTML:'',style:{}})}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../js',file),'utf8'),context);
  return {context,elements,run:s=>vm.runInContext(s,context)};
}
test('toast messages cannot execute HTML from URL or API errors',()=>{
  const s=setup('main.js');s.context.window.Toast.show(attack);
  assert.doesNotMatch(s.elements.get('toast-container').lastChild.innerHTML,/<img/);
  assert.match(s.elements.get('toast-container').lastChild.innerHTML,/&lt;img/);
});
test('citizen names and contact messages are escaped on admin pages',async()=>{
  const s=setup('admin-dashboard.js');
  s.context.renderRequestsTable([{request_id:1,name:attack,contact:attack,request_type:'Rescue',priority_level:'High',status:'Pending',number_of_people:1}]);
  assert.doesNotMatch(s.elements.get('requests-tbody').innerHTML,/<img/);
  s.context.Api.get=async()=>({success:true,messages:[{id:1,name:attack,email:attack,subject:attack,message:attack,status:'Unread'}]});
  await s.context.loadContactMessages();
  assert.doesNotMatch(s.elements.get('support-messages-tbody').innerHTML,/<img/);
  assert.match(s.elements.get('support-messages-tbody').innerHTML,/&lt;img/);
});
test('volunteer cards render free descriptions as text',()=>{
  const s=setup('volunteer-dashboard.js');
  assert.doesNotMatch(s.context.renderRequestCard({request_id:1,request_type:'Rescue',priority_level:'High',status:'Pending',description:attack},1),/<img/);
});
test('NGO inventory free-text fields cannot break out of markup',()=>{
  const s=setup('ngo-dashboard.js');
  s.run(`inventory=[{resource_id:1,name:${JSON.stringify(attack)},category:'Food',quantity:1,unit:'packs',location:${JSON.stringify(attack)}}]`);
  s.context.renderInventory();
  assert.doesNotMatch(s.elements.get('inventory-tbody').innerHTML,/<img/);
});

test('homepage weather uses the existing backend proxy without a browser provider key',async()=>{
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  assert.doesNotMatch(html,/appid=|api\.openweathermap\.org/);
  const inline=[...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].at(-1)[1];
  const elements=new Map();const calls=[];let available=true;
  const context={console,setInterval(){},window:{addEventListener(){}},document:{addEventListener(){},getElementById(id){
    if(!elements.has(id))elements.set(id,{textContent:'',addEventListener(){}});return elements.get(id);}},
    Api:{get:async endpoint=>{calls.push(endpoint);return endpoint==='/weather/live'
      ? (available?{success:true,current:{name:'Provider Place',sys:{country:'IN'},main:{temp:26,humidity:80},
        wind:{speed:2.5},rain:{'1h':0.7},weather:[{main:'Clouds',description:'scattered clouds'}]}}:{success:false}):{};}}};
  vm.createContext(context);vm.runInContext(inline,context);
  await context.loadWeather();
  assert.ok(calls.includes('/weather/live'));
  assert.equal(elements.get('status-weather').textContent,'26°C, Clouds');
  assert.match(elements.get('weather-location').textContent,/Provider Place, IN/);
  assert.equal(elements.get('weather-temperature').textContent,'26°C');
  assert.equal(elements.get('weather-rainfall').textContent,'0.7 mm');
  assert.equal(elements.get('weather-humidity').textContent,'80%');
  assert.equal(elements.get('weather-wind').textContent,'2.5 m\/s');
  available=false;await context.loadWeather();
  assert.equal(elements.get('status-weather').textContent,'Unavailable');
  assert.equal(elements.get('weather-temperature').textContent,'—');
  assert.match(elements.get('weather-state').textContent,/unavailable/);
  context.Api.get=async endpoint=>endpoint==='/weather/live'
    ? {success:false,message:'Weather service is not configured.'} : {};
  await context.loadWeather();
  assert.equal(elements.get('status-weather').textContent,'Not configured');
  assert.match(elements.get('weather-state').textContent,/not configured/);
  context.Api.get=async endpoint=>endpoint==='/weather/live'
    ? {success:false,message:'Weather provider unavailable. Please retry.'} : {};
  await context.loadWeather();
  assert.equal(elements.get('status-weather').textContent,'Provider error');
  assert.match(elements.get('weather-state').textContent,/provider returned an error/);
});

test('homepage statistics show real zero counts, empty data and unavailable states', async()=>{
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  const inline=[...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].at(-1)[1];
  const elements=new Map();
  let result={success:true,stats:{total_requests:0,active_requests:0,active_volunteers:0,
    total_volunteers:0,completed:0}};
  const context={console,setInterval(){},window:{addEventListener(){}},
    document:{addEventListener(){},getElementById(id){
      if(!elements.has(id))elements.set(id,{textContent:'',addEventListener(){}});
      return elements.get(id);}},
    Api:{get:async endpoint=>endpoint==='/public/stats'?result:{success:false}}};
  vm.createContext(context);vm.runInContext(inline,context);
  await context.loadStats();
  assert.equal(elements.get('hero-stat-requests').textContent,0);
  assert.equal(elements.get('hero-stat-volunteers').textContent,0);
  assert.equal(elements.get('hero-stat-completed').textContent,0);
  assert.match(elements.get('stats-message').textContent,/No SOS requests/);
  result={success:true,stats:{total_requests:5,active_requests:2,active_volunteers:1,
    total_volunteers:3,completed:2}};
  await context.loadStats();
  assert.equal(elements.get('hero-stat-requests').textContent,2);
  assert.equal(elements.get('hero-stat-volunteers').textContent,1);
  assert.equal(elements.get('hero-stat-completed').textContent,2);
  assert.doesNotMatch(elements.get('stats-message').textContent,/No SOS requests/);
  result={success:false};
  await context.loadStats();
  assert.equal(elements.get('hero-stat-requests').textContent,'Unavailable');
  assert.match(elements.get('stats-message').textContent,/unavailable/);
});

test('homepage activity distinguishes empty, redacted and unavailable data', async () => {
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  const inline=[...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].at(-1)[1];
  const feed={textContent:'',innerHTML:''};
  let result={success:true,visibility:'aggregate-only',requests:[],total_active:0};
  const context={console,setInterval(){},window:{addEventListener(){}},
    document:{addEventListener(){},getElementById:id=>id==='live-feed-container'?feed:{addEventListener(){}}},
    Api:{get:async()=>result}};
  vm.createContext(context);vm.runInContext(inline,context);
  await context.loadLiveFeed();
  assert.match(feed.textContent,/No active SOS/);
  result={success:true,visibility:'aggregate-only',requests:[],total_active:3};
  await context.loadLiveFeed();
  assert.match(feed.textContent,/3 active SOS or community report records/);
  assert.match(feed.textContent,/authorized map view/);
  result={success:false};
  await context.loadLiveFeed();
  assert.match(feed.textContent,/unavailable/);
  assert.doesNotMatch(feed.textContent,/No active SOS/);
  assert.doesNotMatch(html,/Live Emergency Feed/);
});
