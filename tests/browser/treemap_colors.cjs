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
  if(!elements.has(id))elements.set(id,{value:'',textContent:'',style:{},add(){},replaceChildren(){},setAttribute(){},removeAttribute(){}});
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
 vm.runInContext(source+`\ntable=()=>{};this.style=treemapScoreStyle;this.color=treemapScoreColor;
 this.render=(values,kind='round-one-structures')=>{
  el('plot').value=kind;
  result={plots:{[kind]:{cells:values.map((value,i)=>({label:'Structure '+i,mean_score:value,samples:i+1,x:'Round 1',y:'score'+i,win_share:.5,score_samples:1})),note:'Fixture.',unavailable_records:0,value_label:'Mean net VP'}}};draw();
 };`,context);
 return {context,draws,element};
}
const plain=value=>JSON.parse(JSON.stringify(value));
const red='#ff3b30',grey='#d1d5db',blue='#081d58';
const stopAt=(marker,score)=>marker.colorscale.find(stop=>Math.abs(stop[0]-(score-marker.cmin)/(marker.cmax-marker.cmin))<1e-12)?.[1];
const channels=color=>[1,3,5].map(i=>parseInt(color.slice(i,i+2),16));

test('fixed 0, 100 and 200 VP anchors survive selections with different extremes',()=>{
 const {context}=harness();
 for(const values of [[0,100,200],[-80,100,275],[116,170,201.25],[600],[75]]){
  const {marker,note}=context.style(values);
  assert.equal(stopAt(marker,0),red);assert.equal(stopAt(marker,100),grey);assert.equal(stopAt(marker,200),blue);
  assert.equal(marker.cauto,false);assert.equal(marker.autocolorscale,false);assert.equal(marker.reversescale,false);
  assert.ok(marker.colorbar.tickvals.includes(0));assert.ok(marker.colorbar.tickvals.includes(100));assert.ok(marker.colorbar.tickvals.includes(200));
  assert.match(note,/Fixed score colors/);assert.doesNotMatch(note,/highest mean/);
 }
});

test('the real draw path preserves means and frequency areas with the fixed palette',()=>{
 const {context,draws,element}=harness();context.render([0,100,200,250]);
 const trace=draws.at(-1).traces[0];
 assert.deepEqual(plain(trace.marker.colors),[0,100,200,250]);
 assert.deepEqual(plain(trace.values),[1,2,3,4]);
 assert.equal(stopAt(trace.marker,0),red);assert.equal(stopAt(trace.marker,100),grey);assert.equal(stopAt(trace.marker,200),blue);
 assert.match(element('note').textContent,/blue blends into green/);
});

test('every observed score has the same color regardless of cohort minimum or maximum',()=>{
 const {context}=harness();
 for(const score of [-200,-40,0,50,100,125,150,200,210,225,250,300,450,1000]){
  const narrow=context.style([score]).marker,wide=context.style([-400,score,1200]).marker;
  assert.equal(stopAt(narrow,score),stopAt(wide,score));
  assert.equal(stopAt(narrow,score),context.color(score));
 }
});

test('the color function and distinct scale stops are continuous at every landmark',()=>{
 const {context}=harness();
 for(const score of [0,100,150,200,225,300]){
  const before=channels(context.color(score-.001)),at=channels(context.color(score)),after=channels(context.color(score+.001));
  for(let i=0;i<3;i++){assert.ok(Math.abs(before[i]-at[i])<=1);assert.ok(Math.abs(after[i]-at[i])<=1);}
 }
 const scale=context.style([-50,0,100,200,200,250,500]).marker.colorscale;
 assert.equal(scale[0][0],0);assert.equal(scale.at(-1)[0],1);
 for(let i=1;i<scale.length;i++)assert.ok(scale[i][0]>scale[i-1][0]);
});

test('negative and high values extend the domain without clipping or shifting anchors',()=>{
 const {context}=harness();const {marker,note}=context.style([-175,0,100,200,250,450]);
 assert.equal(marker.cmin,-175);assert.equal(marker.cmax,450);
 assert.deepEqual(plain(marker.colors),[-175,0,100,200,250,450]);
 assert.notEqual(stopAt(marker,-175),red);assert.notEqual(context.color(450),context.color(300));
 for(const score of [225,250,300,450]){const [r,g,b]=channels(context.color(score));assert.ok(g>r&&g>b);}
 assert.deepEqual(plain(marker.colorbar.tickvals),[-175,0,100,200,300,450]);
 assert.match(note,/Negative scores use darker reds/);
});

test('constant zero and hundred selections use red and grey, not a data-relative midpoint',()=>{
 const {context}=harness();
 for(const [score,color] of [[0,red],[100,grey],[200,blue]]){
  const {marker}=context.style([score,score]);
  assert.equal(marker.showscale,true);assert.equal(marker.cmin,0);assert.equal(marker.cmax,300);
  assert.equal(stopAt(marker,score),color);
 }
});

test('missing or nonfinite observations stay white, separate from both red zero and grey hundred',()=>{
 const {context}=harness();let {marker,note}=context.style([null,undefined,NaN,Infinity,75]);
 assert.deepEqual(plain(marker.colors),['#ffffff','#ffffff','#ffffff','#ffffff',75]);
 assert.equal(marker.cmin,0);assert.equal(marker.cmax,300);assert.match(note,/White tiles/);
 ({marker,note}=context.style([null,undefined,NaN,Infinity]));
 assert.equal(marker.showscale,false);assert.match(note,/unavailable/);
});

test('empty selections show no observations; other chart scales are unchanged',()=>{
 const {context,draws,element}=harness();context.render([]);
 assert.equal(draws.length,0);assert.match(element('chart').textContent,/No observations/);
 context.render([20,50],'round-scoring');
 assert.equal(draws.at(-1).traces[0].colorscale,'Blues');
 assert.doesNotMatch(element('note').textContent,/Fixed score colors/);
});
