const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function setup() {
  const charts=new Map(), elements=new Map();
  const context={window:{}, console, requestAnimationFrame:fn=>fn(),
    document:{addEventListener(){}, getElementById(id){
      if(!elements.has(id))elements.set(id,{textContent:'',innerHTML:'',getContext:()=>id});
      return elements.get(id);
    }},
    Chart:class {constructor(id,config){charts.set(id,config);} destroy(){}},
    Api:{get:async()=>null}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../js/admin-dashboard.js'),'utf8'),context);
  return {context,charts,elements};
}
test('charts preserve API counts including Duplicate and ordered ISO daily points',async()=>{
  const s=setup();
  const payload={success:true,by_type:{Rescue:1,Food:2,Water:1,Medicine:1,Shelter:1},
    by_status:{Pending:1,Accepted:1,'En Route':1,'On Site':1,Completed:1,Duplicate:1},
    by_disaster:{Flood:2,Cyclone:1},by_priority:{High:2,Medium:4},
    by_day:[{day:'2026-10-18',count:2},{day:'2026-10-19',count:1}]};
  s.context.Api.get=async endpoint=>{assert.equal(endpoint,'/admin/analytics');return payload;};
  await s.context.loadAnalytics();
  for(const [id,values] of [['chart-requests-type',payload.by_type],['chart-status',payload.by_status],['chart-disasters',payload.by_disaster]]){
    const data=s.charts.get(id).data;
    assert.equal(data.datasets[0].data.reduce((a,b)=>a+b,0),Object.values(values).reduce((a,b)=>a+b,0));
    data.labels.forEach((label,i)=>assert.equal(data.datasets[0].data[i],values[label]||0));
  }
  assert.deepEqual(Array.from(s.charts.get('chart-trend').data.labels),['10-18','10-19']);
  assert.deepEqual(Array.from(s.charts.get('chart-trend').data.datasets[0].data),[2,1]);
});
test('dashboard displays explicit busy volunteer and completed task counts',async()=>{
  const s=setup();
  s.context.Api.get=async()=>({success:true,stats:{total_requests:6,high_priority:2,active_volunteers:1,
    total_volunteers:3,busy_volunteers:1,relief_tasks:2,completed_tasks:1,completed:1,pending:1,disaster_reports:3}});
  await s.context.loadDashboard();
  assert.equal(s.elements.get('stat-total').textContent,6);
  assert.equal(s.elements.get('stat-completed').textContent,1);
  const summary=s.elements.get('volunteer-summary').innerHTML;
  assert.match(summary,/On Active Task<\/div>\s*<div[^>]*>1<\/div>/);
  assert.match(summary,/Tasks Completed<\/div>\s*<div[^>]*>1<\/div>/);
});
test('failed analytics responses do not replace existing charts or counts with zeros',async()=>{
  const s=setup();
  s.charts.set('chart-trend',{existing:true});
  s.elements.set('stat-total',{textContent:6});
  s.context.Api.get=async()=>({success:false,message:'Unavailable'});
  await s.context.loadAnalytics(); await s.context.loadDashboard();
  assert.deepEqual(s.charts.get('chart-trend'),{existing:true});
  assert.equal(s.elements.get('stat-total').textContent,6);
});
