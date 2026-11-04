'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const {execFileSync} = require('node:child_process');
const {JSDOM} = require('jsdom');

const fixtures = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c', `
import json
from pathlib import Path
from gaia_stats.analysis import normalize
from gaia_stats.cohort import enrich, report, response
rows=[]
for name in ('Modern-riddle-1723.json','Jubilant-rover-3041.json'):
    game=json.loads((Path('tests/fixtures')/name).read_text())
    rows.extend(enrich(game,normalize(game)))
dataset={'rows':rows,'scope':'Client test fixtures'}
print(json.dumps({mode:{'catalog':json.loads(response(dataset,'/cohort/api/catalog',{'ruleset':mode})[0]),
    'stats':{cutoff:report(dataset,dict(ruleset=mode,**({'min_elo':cutoff} if cutoff else {}))) for cutoff in ('','200','99999')}}
    for mode in ('base','lost-fleet')}))
`], {encoding:'utf8'}));
const html = readFileSync('web/cohort/index.html', 'utf8');
const script = readFileSync('web/cohort/app.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function harness({plotly=true, controlled=false, controlledCatalog=false, memories={}, url='http://localhost/?ruleset=base', rememberedMode=null}={}) {
  const dom = new JSDOM(html, {url, runScripts:'outside-only'});
  const w=dom.window, requests=[], pending=[], catalogs=[], draws=[], purges=[];
  w.sessionStorage.setItem('gaia-cohort-filters',JSON.stringify(memories));
  if(rememberedMode!==null)w.sessionStorage.setItem('gaia-cohort-mode',rememberedMode);
  let failures=false;
  const plots = {
    react(target,traces,layout){target.data=traces;target.layout=layout;draws.push(traces);return Promise.resolve();},
    purge(target){delete target.data;purges.push(target);}
  };
  if(plotly)w.Plotly=plots;
  w.fetch=(url,{signal}={})=>{
    const u=new URL(url,w.location), q=Object.fromEntries(u.searchParams);
    const mode=q.ruleset||'lost-fleet', fixture=fixtures[mode];
    const isStats=u.pathname.endsWith('/stats');
    if(isStats)requests.push(q);
    let data=isStats?structuredClone(fixture.stats[q.min_elo||'']):fixture.catalog;
    if(isStats){data.filters=q;data.plots={[q.plot]:data.plots[q.plot]};}
    const entry={q,signal,isStats,resolve:null};
    return new Promise((resolve,reject)=>{
      entry.resolve=()=>resolve({ok:!failures,json:async()=>failures?{error:'Temporary failure'}:data});
      entry.reject=reject;
      // Resolve manually even if aborted: generation checks must also reject late
      // responses from a transport that cannot cancel completed server work.
      if(controlled&&isStats)pending.push(entry);else if(controlledCatalog&&!isStats)catalogs.push(entry);else entry.resolve();
    });
  };
  w.eval(readFileSync('web/cohort/tile-labels.js','utf8').replace('__TILE_REGISTRY__',readFileSync('web/cohort/tile-labels.json','utf8')));
  w.eval(readFileSync('web/cohort/tables.js','utf8'));
  w.eval(readFileSync('web/cohort/basic-tech.js','utf8'));
  w.eval(script+'\nwindow.testClient={getResult:()=>result,getSize:()=>responses.size,expire:()=>{for(const entry of responses.values())entry.time-=RESPONSE_TTL+1;}};');
  await tick();await tick();
  const get=id=>w.document.getElementById(id);
  const select=async(id,value)=>{get(id).value=value;get(id).dispatchEvent(new w.Event('change'));await tick();await tick();};
  const apply=async()=>{get('filters').dispatchEvent(new w.Event('submit',{cancelable:true}));await tick();await tick();};
  const flush=async()=>{pending.shift().resolve();await tick();await tick();};
  return {w,dom,get,select,apply,flush,requests,pending,catalogs,draws,purges,plots,
    setFailures(value){failures=value;}, close(){dom.window.close();}};
}

test('statistics and exact tables load before Plotly and render when it arrives', async()=>{
  const h=await harness({plotly:false});
  try{
    assert.match(h.get('status').textContent,/ games · /);
    assert.match(h.get('chart').textContent,/Loading chart library/);
    assert.ok(h.get('comparison').querySelector('table'));
    h.w.Plotly=h.plots;
    h.w.document.querySelector('script[src="/classic/assets/plotly.min.js"]').dispatchEvent(new h.w.Event('load'));
    await tick();
    assert.equal(h.draws.length,1);
  }finally{h.close();}
});

test('technology pairs and repeated views reuse responses and preserve comparison tables', async()=>{
  const h=await harness();
  try{
    const table=h.get('comparison').firstChild;
    assert.equal(h.requests.length,1);
    await h.select('plot','advanced-tech-score');
    assert.equal(h.requests.length,1);
    assert.equal(h.get('comparison').firstChild,table);
    assert.equal(h.draws.at(-1)[0].type,'scatter');
    await h.select('plot','round-scoring');
    assert.equal(h.requests.length,2);
    assert.equal(h.draws.at(-1)[0].type,'heatmap');
    await h.select('plot','advanced-tech-frequency');
    assert.equal(h.requests.length,2);
    assert.equal(h.draws.at(-1)[0].type,'bar');
    await h.apply();
    assert.equal(h.requests.length,3);
    assert.match(h.get('csv').href,/plot=advanced-tech-frequency/);
  }finally{h.close();}
});

test('duplicate applies do not queue requests; superseded responses cannot replace selection', async()=>{
  const h=await harness({controlled:true});
  try{
    await h.flush();
    h.w.document.querySelector('[name=min_elo]').value='200';
    await h.apply();await h.apply();
    assert.equal(h.requests.length,2);
    const stale=h.pending.shift();
    assert.equal(h.get('csv').hasAttribute('href'),false);
    assert.ok(h.get('comparison').firstChild);
    h.w.document.querySelector('[name=min_elo]').value='99999';
    await h.apply();
    assert.equal(stale.signal.aborted,true);
    await h.flush();
    assert.match(h.get('status').textContent,/^0 games/);
    stale.resolve();await tick();await tick();
    assert.match(h.get('status').textContent,/^0 games/);
    assert.match(h.get('csv').href,/min_elo=99999/);
    assert.equal(h.get('chart').getAttribute('aria-busy'),'false');
  }finally{h.close();}
});

test('mode changes invalidate cache and ignore old-mode results', async()=>{
  const h=await harness({controlled:true});
  try{
    const stale=h.pending.shift();
    await h.select('mode','lost-fleet');
    assert.equal(stale.signal.aborted,true);
    await h.flush();
    stale.resolve();await tick();
    assert.equal(h.w.testClient.getResult().ruleset,'lost-fleet');
    assert.match(h.get('csv').href,/ruleset=lost-fleet/);
    await h.select('mode','base');await h.flush();
    assert.equal(h.w.testClient.getResult().ruleset,'base');
    assert.equal(h.requests.length,3);
  }finally{h.close();}
});

test('Plotly and API errors retain exact fallback and allow retry', async()=>{
  const h=await harness({plotly:false});
  try{
    h.w.document.querySelector('script[src="/classic/assets/plotly.min.js"]').dispatchEvent(new h.w.Event('error'));
    assert.match(h.get('chart').textContent,/library unavailable/);
    assert.ok(h.get('metrics').firstChild);
    h.setFailures(true);await h.apply();
    assert.equal(h.get('status').textContent,'Temporary failure');
    assert.equal(h.get('comparison').children.length,0);
    assert.equal(h.get('csv').hasAttribute('href'),false);
    assert.equal(h.get('chart').getAttribute('aria-busy'),'false');
    h.setFailures(false);await h.apply();
    assert.match(h.get('status').textContent,/ games · /);
    assert.ok(h.get('comparison').firstChild);
  }finally{h.close();}
});

test('all nine views render with eight requests; expired responses refetch', async()=>{
  const h=await harness();
  try{
    for(const kind of Object.keys(fixtures.base.stats[''].plots))await h.select('plot',kind);
    assert.equal(h.requests.length,8);
    assert.equal(h.draws.at(-1)[0].type,'box');
    h.w.testClient.expire();
    await h.select('plot','advanced-tech-frequency');
    assert.equal(h.requests.length,9);
    assert.ok(h.w.testClient.getSize()<=8);
  }finally{h.close();}
});


test('interrupted mode catalogs never overwrite remembered form filters', async()=>{
  const h=await harness({controlledCatalog:true,memories:{
    'lost-fleet':{min_elo:'200',plot:'round-scoring',lf_2p_4qic_mode:'standard-only'}
  }});
  try{
    const resolve=async(entry)=>{entry.resolve();await tick();await tick();};
    await resolve(h.catalogs.shift()); // Initial base form is now loaded.
    await h.select('mode','lost-fleet');
    const interrupted=h.catalogs.shift();
    assert.equal(h.get('filters').querySelector('fieldset').disabled,true);
    await h.select('mode','base');
    await resolve(h.catalogs.shift());
    await resolve(interrupted); // A cancelled transport may still finish.
    await h.select('mode','lost-fleet');
    await resolve(h.catalogs.shift());
    const saved=JSON.parse(h.w.sessionStorage.getItem('gaia-cohort-filters'));
    assert.equal(saved['lost-fleet'].min_elo,'200');
    assert.equal(saved['lost-fleet'].plot,'round-scoring');
    assert.equal(h.w.document.querySelector('[name=min_elo]').value,'200');
    assert.equal(h.get('plot').value,'round-scoring');
    assert.equal(h.requests.at(-1).ruleset,'lost-fleet');
    assert.equal(h.requests.at(-1).min_elo,'200');
    assert.match(h.get('csv').href,/min_elo=200/);
  }finally{h.close();}
});

test('failed catalog can retry without saving the previous mode form', async()=>{
  const h=await harness({memories:{'lost-fleet':{min_elo:'200',plot:'round-scoring'}}});
  try{
    h.setFailures(true);
    await h.select('mode','lost-fleet');
    assert.equal(h.get('status').textContent,'Temporary failure');
    h.setFailures(false);
    await h.apply();
    assert.equal(h.w.document.querySelector('[name=min_elo]').value,'200');
    assert.equal(h.get('plot').value,'round-scoring');
    assert.equal(h.requests.at(-1).ruleset,'lost-fleet');
    assert.equal(h.requests.at(-1).min_elo,'200');
  }finally{h.close();}
});

 test('mode labels, new visitor default, remembered choice and explicit links',async()=>{
 for(const [url,rememberedMode,expected] of [['http://localhost/',null,'lost-fleet'],['http://localhost/','base','base'],['http://localhost/?ruleset=lost-fleet','base','lost-fleet'],['http://localhost/?ruleset=base','lost-fleet','base'],['http://localhost/','invalid','lost-fleet']]){
 const h=await harness({url,rememberedMode});try{assert.equal(h.get('mode').value,expected);assert.deepEqual([...h.get('mode').options].map(o=>o.text),['Lost Fleet • Live','Base Game • Static']);await h.select('mode',expected==='base'?'lost-fleet':'base');assert.equal(h.w.sessionStorage.getItem('gaia-cohort-mode'),h.get('mode').value);}finally{h.close();}
 }
 });

 test('more-balanced is never offered or restored; 4-QIC selection remains independent',async()=>{
 const old=fixtures['lost-fleet'].catalog.faction_variant;fixtures['lost-fleet'].catalog.faction_variant=[...old,'more-balanced'];
 const h=await harness({url:'http://localhost/',memories:{'lost-fleet':{faction_variant:'more-balanced',lf_2p_4qic_mode:'variant-only'}}});
 try{const fields=h.get('filters').elements;assert.ok(![...fields.faction_variant.options].some(o=>o.value==='more-balanced'));assert.equal(fields.faction_variant.value,'');assert.equal(fields.lf_2p_4qic_mode.value,'variant-only');assert.equal(h.requests.at(-1).lf_2p_4qic_mode,'variant-only');assert.notEqual(h.requests.at(-1).faction_variant,'more-balanced');}
 finally{h.close();fixtures['lost-fleet'].catalog.faction_variant=old;}
 });
