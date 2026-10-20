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
      ? (available?{success:true,current:{main:{temp:26},weather:[{main:'Clouds'}]}}:{success:false}):{};}}};
  vm.createContext(context);vm.runInContext(inline,context);
  await context.loadStats();
  assert.ok(calls.includes('/weather/live'));
  assert.equal(elements.get('status-weather').textContent,'26°C, Clouds');
  available=false;await context.loadStats();
  assert.equal(elements.get('status-weather').textContent,'Unavailable');
});
