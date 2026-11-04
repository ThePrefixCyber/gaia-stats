'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const registry=JSON.parse(fs.readFileSync('web/cohort/tile-labels.json','utf8'));
const script=fs.readFileSync('web/cohort/tile-labels.js','utf8').replace('__TILE_REGISTRY__',JSON.stringify(registry));
const forbidden=/\[[^\]\n]+\]|\b(?:advtech[\w-]*|tech\d+|ship-tech-[\w-]+|adv-(?:terra|nav|int|gaia|eco|sci|ext)|tech-free[123])\b|_per_/;
function harness(html='<div id="key"></div>'){
 const dom=new JSDOM(html,{url:'http://gaia.test/',runScripts:'outside-only'});dom.window.eval(script);return dom;
}
function assertClean(document){
 const text=[document.body.textContent,...[...document.querySelectorAll('[aria-label],[title]')].map(n=>`${n.getAttribute('aria-label')} ${n.getAttribute('title')}`)].join('\n');
 assert.doesNotMatch(text,forbidden);
}
test('every registry ID and historical alias has clean display text and glossary',()=>{
 const dom=harness(),T=dom.window.GaiaTiles;
 try{
  for(const [category,entries] of Object.entries(registry))for(const [id,entry] of Object.entries(entries)){
   for(const key of [id,...entry.aliases]){assert.equal(T.label(category,key),entry.short);assert.doesNotMatch(T.label(category,key),forbidden);}
  }
  for(const key of ['adv-terra','adv-nav','adv-int','adv-gaia','adv-eco','adv-sci','adv-ext','tech-free1','tech-free2','tech-free3'])assert.doesNotMatch(T.position(key),forbidden);
  T.glossary(dom.window.document.querySelector('#key'));assertClean(dom.window.document);
 }finally{dom.window.close();}
});
test('legacy source axes include every rank, preserve raw values and separate matching labels',()=>{
 const dom=harness('<div class="js-plotly-plot"></div>'),w=dom.window,g=w.document.querySelector('div'),updates=[];
 g.data=[{x:['research'],y:[1],name:'rank_1'},{x:['tech_score'],y:[2],name:'rank_2'},
  {x:['tech-free1'],y:[3],name:'rank_3',xaxis:'x2'},{x:['adv-terra'],y:[4],name:'rank_4',xaxis:'x2'}];
 const before=JSON.stringify(g.data);w.Plotly={restyle:(graph,update,index)=>updates.push({update,index}),relayout:(graph,layout)=>{g.layout=layout;}};
 try{
  w.GaiaTiles.legacy('point-sources');assert.equal(JSON.stringify(g.data),before);
  assert.deepEqual(Array.from(g.layout.xaxis.tickvals),['research','tech_score']);
  assert.deepEqual(Array.from(g.layout.xaxis.ticktext),['Research','Research']);
  assert.deepEqual(Array.from(g.layout.xaxis2.tickvals),['tech-free1','adv-terra']);
  assert.deepEqual(Array.from(g.layout.xaxis2.ticktext),['Tech Free','Adv Terra']);
  for(const {update} of updates){assert.doesNotMatch(update.hovertext.flat().join("\n"),forbidden);assert.equal(update.name,undefined);}
 }finally{dom.window.close();}
});
test('historical comparison wizard uses display labels with original distinct option values',()=>{
 const dom=harness('<dialog id="setup"><form id="setup-form"></form><button id="setup-back"></button><button id="setup-next"></button><button id="setup-close"></button><p id="setup-error"></p></dialog>'),w=dom.window;
 try{
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.eval(fs.readFileSync('web/classic/comparison.js','utf8'));w.openComparisonWizard(['2','3','4'],'4');
  assertClean(w.document);
  for(const s of w.document.querySelectorAll('select'))assert.equal(new Set([...s.options].map(o=>o.value)).size,s.options.length);
  const select=w.document.querySelector('[name=adv_1]');assert.equal(select.options[0].value,'3vp_per_fed_pass');assert.equal(select.options[0].textContent,w.GaiaTiles.label('advanced','3vp_per_fed_pass'));
  w.document.querySelector('#setup-close').click();assert.equal(w.document.querySelector('dialog').open,false);
  w.openComparisonWizard(['4'],'4');assertClean(w.document);
 }finally{dom.window.close();}
});

test('classic pre-bid competition rank legends are never relabeled as VP sources',()=>{
 const dom=harness('<div class="js-plotly-plot"></div>'),w=dom.window,g=w.document.querySelector('div'),updates=[];
 g.data=[1,2,3,4].map(rank=>({x:['research'],y:[rank],name:`pre-bid-score rank ${rank}`}));
 w.Plotly={restyle:(graph,update)=>updates.push(update),relayout:()=>{}};
 try{w.GaiaTiles.legacy('point-sources');for(const update of updates)assert.equal(update.name,undefined);}
 finally{w.close();}
});
