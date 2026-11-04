// Run from repository root: node --test tests/browser/treemap_colors.cjs
// Exercise the real client draw path without a browser or extra dependencies.
'use strict';
const assert=require('node:assert/strict');
const {test}=require('node:test');
const vm=require('node:vm');
const {readFileSync}=require('node:fs');

function harness(){
 const elements=new Map();
 const element=id=>{
  if(!elements.has(id))elements.set(id,{value:'',textContent:'',add(){},replaceChildren(){},setAttribute(){},removeAttribute(){}});
  return elements.get(id);
 };
 const form={};
 const draws=[];
 const Plotly={purge(){},newPlot(target,traces,layout){draws.push({traces,layout});},react(target,traces,layout){draws.push({traces,layout});return Promise.resolve();}};
 const context={
  document:{querySelector:()=>form,getElementById:element,createElement:()=>({}),head:{append(){}}},
  sessionStorage:{getItem:()=>null},location:{search:''},URLSearchParams,
  Option:function(text,value){this.text=text;this.value=value;},
  GaiaTiles:{metric:(_,value)=>value,label:(_,value)=>value},Plotly,window:{Plotly},
 };
 vm.createContext(context);
 // Only suppress the initial network request; all tested draw code is unchanged.
 const source=readFileSync('web/cohort/app.js','utf8').replace(/loadMode\(\);\s*$/,'');
 vm.runInContext(source+`\ntable=()=>{};this.style=treemapScoreStyle;
 this.render=(values,kind='round-one-structures')=>{
  el('plot').value=kind;
  result={plots:{[kind]:{cells:values.map((value,i)=>({label:'Structure '+i,mean_score:value,samples:i+1,x:'Round 1',y:'score'+i,win_share:.5,score_samples:1})),note:'Fixture.',unavailable_records:0,value_label:'Mean net VP'}}};draw();
 };`,context);
 return {context,draws,element};
}
const plain=value=>JSON.parse(JSON.stringify(value));
const grey='#d1d5db',blue='#081d58',rust='#9c3b16';

test('positive means are grey at zero and very dark blue at the exact plotted maximum',()=>{
 const {context,draws,element}=harness();context.render([116,170,201.25]);
 const marker=draws.at(-1).traces[0].marker;
 assert.equal(marker.cmin,0);assert.equal(marker.cmax,201.25);
 assert.equal(marker.cauto,false);assert.equal(marker.autocolorscale,false);assert.equal(marker.reversescale,false);
 assert.deepEqual(plain(marker.colors),[116,170,201.25]);
 assert.deepEqual(plain(marker.colorscale[0]),[0,grey]);
 assert.deepEqual(plain(marker.colorscale.at(-1)),[1,blue]);
 assert.equal(marker.colorbar.tickvals[0],0);
 assert.equal(marker.colorbar.tickvals.at(-1),201.25);
 assert.match(element('note').textContent,/highest mean net VP shown/);
 assert.deepEqual(plain(draws.at(-1).traces[0].values),[1,2,3]);
});

test('a new selection recomputes its maximum, including a single positive mean',()=>{
 const {context,draws}=harness();context.render([120,200]);context.render([45]);
 const marker=draws.at(-1).traces[0].marker;
 assert.equal(marker.cmin,0);assert.equal(marker.cmax,45);
 assert.equal(marker.colorscale.at(-1)[1],blue);
});

test('negative values remain signed on a distinct rust arm and zero stays grey',()=>{
 const {context,draws,element}=harness();context.render([-40,0,160]);
 const marker=draws.at(-1).traces[0].marker;
 assert.equal(marker.cmin,-40);assert.equal(marker.cmax,160);
 assert.deepEqual(plain(marker.colors),[-40,0,160]);
 assert.deepEqual(plain(marker.colorscale[0]),[0,rust]);
 assert.deepEqual(plain(marker.colorscale[1]),[.2,grey]);
 assert.deepEqual(plain(marker.colorscale.at(-1)),[1,blue]);
 assert.ok(marker.colorbar.tickvals.includes(0));
 assert.match(element('note').textContent,/Rust indicates negative/);
});

test('negative-only data ends at grey zero without inventing a positive observation',()=>{
 const {context}=harness();const {marker,note}=context.style([-40,-10]);
 assert.equal(marker.cmin,-40);assert.equal(marker.cmax,0);
 assert.deepEqual(plain(marker.colorscale),[[0,rust],[1,grey]]);
 assert.equal(marker.colorbar.tickvals.at(-1),0);
 assert.doesNotMatch(note,/Very dark blue/);
});

test('all-zero means are grey without a misleading nonzero legend',()=>{
 const {context}=harness();const {marker,note}=context.style([0,0]);
 assert.equal(marker.showscale,false);
 assert.deepEqual(plain(marker.colorscale),[[0,grey],[1,grey]]);
 assert.match(note,/values are 0/);
});

test('missing/nonfinite values never set bounds or become zero scores',()=>{
 const {context}=harness();let style=context.style([null,undefined,NaN,Infinity,75]);
 assert.equal(style.marker.cmax,75);
 assert.deepEqual(plain(style.marker.colors),[null,null,null,null,75]);
 style=context.style([null,undefined,NaN,Infinity]);
 assert.equal(style.marker.showscale,false);
 assert.match(style.note,/unavailable/);assert.doesNotMatch(style.note,/values are 0/);
});

test('empty selections show no observations; other chart scales are unchanged',()=>{
 const {context,draws,element}=harness();context.render([]);
 assert.equal(draws.length,0);assert.match(element('chart').textContent,/No observations/);
 context.render([20,50],'round-scoring');
 assert.equal(draws.at(-1).traces[0].colorscale,'Blues');
 assert.doesNotMatch(element('note').textContent,/Very dark blue/);
});
