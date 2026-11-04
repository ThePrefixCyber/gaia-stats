'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{},GaiaTiles:{position:s=>({free:'Free',terra:'Terra',taken:'Taken',not_taken:'Not taken'})[s]||s,label:(_c,t)=>t}};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/cohort/basic-tech.js','utf8'),context);
const chart=context.window.GaiaBasicTech;
test('both basic score modes render one pooled Free series and preserve its counts in hover',()=>{
 const cells=[{tile_id:'tech1',location_id:'free',samples:4,games:2,mean_score:140},
              {tile_id:'tech1',location_id:'terra',samples:1,games:1,mean_score:180},
              {tile_id:'tech1',location_id:'taken',samples:5,games:3,mean_score:148}];
 for(const kind of ['basic-tech-score','basic-tech-setup-score']){
  const result=chart.build(kind,cells,{mean_score:150},390,700);
  const free=result.traces.filter(t=>t.name==='Free');assert.equal(free.length,1);
  assert.deepEqual(Array.from(free[0].x),[140]);assert.deepEqual(Array.from(free[0].customdata[0]),['tech1',4,2]);
  assert.match(free[0].hovertemplate,/ · Free<br>/);assert.doesNotMatch(free[0].hovertemplate,/Free [123]/);
  assert.equal(result.traces.filter(t=>t.name==='Terra').length,1);
  assert.ok(result.traces.every(t=>!/^Free [123]$/.test(t.name)));
 }
 assert.ok(!['free1','free2','free3'].some(slot=>slot in chart.colors));
});
test('acquisition view has one Free bucket and pooled denominators in each rank hover',()=>{
 const cell={tile_id:'tech1',location_id:'free',samples:4,games:2,available:8,rank_counts:{1:1,2:3},unknown_ownership:1};
 const result=chart.build('basic-tech-frequency',[cell],{ruleset:'base',filters:{},samples:8,rank_counts:{1:2,2:6}},1000,700);
 assert.equal(result.layout.annotations.filter(a=>a.text==='Free').length,1);
 for(const trace of result.traces){assert.deepEqual(Array.from(trace.customdata[0].slice(0,4)),['tech1','Free',4,8]);}
 assert.equal(result.traces[0].y[0],12.5);assert.equal(result.traces[1].y[0],37.5);
});
