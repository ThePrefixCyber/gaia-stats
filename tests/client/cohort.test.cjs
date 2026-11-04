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
for name in ('cohort/Shiny-cypress-1384.json','Jubilant-rover-3041.json'):
    game=json.loads((Path('tests/fixtures')/name).read_text())
    enriched=enrich(game,normalize(game))
    if name.startswith('cohort/'):
        # This compact standard fixture omits holdings; use synthetic UI-only
        # holdings/openings to exercise populated charts without including MB games.
        for row in enriched:
            row['owned_technologies']=[{'slot':k,'tile':v} for k,v in row['technologies'].items()]
            row['round_one_structures']={'m':2,'ts':0,'lab':0,'PI':1,'ac1':0,'ac2':0}
    rows.extend(enriched)
dataset={'rows':rows,'scope':'Client test fixtures'}
print(json.dumps({mode:{'catalog':json.loads(response(dataset,'/cohort/api/catalog',{'ruleset':mode})[0]),
    'faction_scoring':report(dataset,{'ruleset':mode,'faction':'ivits'}),
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
    let data=isStats?structuredClone(q.plot==='final-scoring'&&q.faction==='ivits'?fixture.faction_scoring:fixture.stats[q.min_elo||'']):fixture.catalog;
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
  w.eval(script+'\nwindow.testClient={getResult:()=>result,openingTree,getSize:()=>responses.size,expire:()=>{for(const entry of responses.values())entry.time-=RESPONSE_TTL+1;}};');
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
    assert.match(h.get('chart').textContent,/Choose a faction/);
    await h.select('scoring-view','absolute');
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


test('point shares keep rank groups and retained absolute mode switches without requests', async()=>{
  const h=await harness();
  try{
    await h.select('plot','point-sources');
    const requests=h.requests.length;
    assert.ok(h.draws.at(-1).every(t=>t.name.includes('rank')));
    assert.equal(h.get('chart').layout.yaxis.title,'Signed share of pre-bid score (%)');
    assert.match(h.get('metrics').textContent,/Median score share/);
    await h.select('scoring-view','absolute');
    assert.equal(h.get('chart').layout.yaxis.title,'VP contribution (signed)');
    await h.select('scoring-view','relative');
    assert.ok(h.draws.at(-1).every(t=>t.name.includes('rank')));
    assert.equal(h.requests.length,requests);
    await h.select('plot','round-scoring');
    assert.match(h.get('chart').textContent,/Choose a faction/);
    await h.select('scoring-view','absolute');
    assert.equal(h.draws.at(-1)[0].type,'heatmap');
    await h.select('scoring-view','relative');
    assert.match(h.get('chart').textContent,/Choose a faction/);
  }finally{h.close();}
});


test('round comparison labels expand tile IDs without misreading the player-count prefix', async()=>{
  const h=await harness();
  try{
    for(const players of [2,3,4]){
      const text=h.w.GaiaTiles.metric('round-scoring',`${players}p: Round 1 / score1`);
      assert.match(text,new RegExp(`${players} players: Round 1`));
      assert.doesNotMatch(text,/Unmapped/);
      assert.equal(text.slice(text.indexOf(' / ')+3),h.w.GaiaTiles.label('round','score1').replace(/ \[[^\]]+\]$/, ''));
      assert.doesNotMatch(text,/score1/);
    }
    await h.select('plot','round-scoring');await h.select('scoring-view','absolute');
    assert.match(h.get('note').textContent,/When every player in each game is included/);
    assert.match(h.get('note').textContent,/filters can omit seats/);
  }finally{h.close();}
});

test('frequency default is one tile bar with all original hover probabilities', async()=>{
  const h=await harness();
  try{
    const result=h.w.testClient.getResult(),plot=result.plots['advanced-tech-frequency'];
    const traces=h.draws.at(-1),tile=plot.tile_cells[0];
    assert.equal(traces[0].x.length,plot.tile_cells.length);
    assert.equal(new Set(traces[0].x).size,plot.tile_cells.length);
    assert.equal(traces[0].y[0],tile.available?(tile.rank_counts[1]||0)/tile.available:null);
    assert.match(traces[0].hovertext[0],/P\(rank \| taken\)/);
    assert.match(traces[0].hovertext[0],/P\(taken and rank \| available\)/);
    assert.match(traces[0].hovertext[0],/Selected cohort overall P\(rank\)/);
    assert.equal(h.get('chart').layout.yaxis.tickformat,'.0%');
    assert.equal(h.get('chart').layout.xaxis.categoryorder,'total ascending');
    assert.deepEqual(Array.from(h.get('chart').layout.xaxis.tickvals),Array.from(traces[0].x));
    await h.select('frequency-view','position');
    assert.equal(h.draws.at(-1)[0].x.length,plot.cells.length);
    assert.equal(h.requests.length,1);
    await h.select('frequency-view','tile');
    assert.equal(h.draws.at(-1)[0].x.length,plot.tile_cells.length);
    assert.equal(h.requests.length,1);
  }finally{h.close();}
});

test('opening hierarchy has exact root/class/leaf totals and weighted parent means', async()=>{
  const h=await harness();
  try{
    const cells=[{label:'2-m_0-ts_0-lab_1-pi_0-ac1_0-ac2',structure_class:'PI',samples:1,mean_score:100,mean_elo:100,mean_elo_n:1},
                 {label:'3-m_0-ts_0-lab_1-pi_0-ac1_0-ac2',structure_class:'PI',samples:9,mean_score:200,mean_elo:300,mean_elo_n:3}];
    const nodes=h.w.testClient.openingTree(cells,'Round 1');
    const root=nodes.find(n=>n.parent===''),group=nodes.find(n=>n.parent===root.id);
    assert.equal(root.samples,10);assert.equal(group.samples,10);
    assert.equal(root.mean_score,190);assert.equal(group.mean_score,190);
    assert.equal(root.mean_elo,250);assert.equal(root.mean_elo_n,4);
    assert.equal(new Set(nodes.map(n=>n.id)).size,nodes.length);
    assert.deepEqual(Array.from(nodes.filter(n=>n.parent===group.id),n=>n.samples),[1,9]);
    await h.select('plot','round-one-structures');
    const trace=h.draws.at(-1)[0];
    assert.equal(trace.branchvalues,'total');
    assert.equal(trace.parents.filter(p=>p==='').length,1);
    for(let i=0;i<trace.ids.length;i++){
      const children=trace.values.filter((v,j)=>trace.parents[j]===trace.ids[i]);
      if(children.length)assert.equal(children.reduce((a,b)=>a+b,0),trace.values[i]);
    }
    assert.match(trace.hovertext[0],/Mean pregame Elo/);
  }finally{h.close();}
});


test('integrated scoring and frequency controls retain independent modes across chart switches', async()=>{
  const h=await harness();
  try{
    await h.select('frequency-view','position');
    await h.select('plot','point-sources');
    assert.equal(h.get('frequency-view-label').hidden,true);
    assert.equal(h.get('scoring-view-control').hidden,false);
    await h.select('scoring-view','absolute');
    await h.select('plot','advanced-tech-frequency');
    assert.equal(h.get('frequency-view').value,'position');
    assert.equal(h.get('scoring-view-control').hidden,true);
    assert.equal(h.get('frequency-view-label').hidden,false);
    await h.select('plot','point-sources');
    assert.equal(h.get('scoring-view').value,'absolute');
    await h.select('plot','round-one-structures');
    assert.equal(h.get('frequency-view-label').hidden,true);
    assert.equal(h.get('scoring-view-control').hidden,true);
    const trace=h.draws.at(-1)[0];
    assert.equal(trace.branchvalues,'total');
    assert.ok(trace.marker.colorscale.some(([position,color])=>color==='#ff3b30'));
  }finally{h.close();}
});
 test('mode labels, new visitor default, remembered choice and explicit links',async()=>{
 for(const [url,rememberedMode,expected] of [['http://localhost/',null,'lost-fleet'],['http://localhost/','base','base'],['http://localhost/?ruleset=lost-fleet','base','lost-fleet'],['http://localhost/?ruleset=base','lost-fleet','base'],['http://localhost/','invalid','lost-fleet']]){
 const h=await harness({url,rememberedMode});try{assert.equal(h.get('mode').value,expected);assert.deepEqual([...h.get('mode').options].map(o=>o.text),['Lost Fleet • Live','Base Game • Static']);await h.select('mode',expected==='base'?'lost-fleet':'base');assert.equal(h.w.sessionStorage.getItem('gaia-cohort-mode'),h.get('mode').value);}finally{h.close();}
 }
 });

test('retired faction-variant controls never filter requests and saved values are discarded',async()=>{
 for(const value of ['standard','beta','more-balanced']){
  const h=await harness({url:'http://localhost/',memories:{base:{faction_variant:value,faction_variant_version:'1'},'lost-fleet':{player_count:'2',faction_variant:value,faction_variant_version:'1',lf_2p_4qic_mode:'variant-only'}}});
  try{
   const fields=h.get('filters').elements;
   assert.equal(fields.faction_variant,undefined);assert.equal(fields.faction_variant_version,undefined);
   assert.doesNotMatch(h.get('filters').textContent,/Faction variant|Faction balance|Balance version/);
   assert.equal(fields.lf_2p_4qic_mode.value,'variant-only');assert.equal(h.requests.at(-1).lf_2p_4qic_mode,'variant-only');
   for(const mode of ['base','lost-fleet']){
    await h.select('mode',mode);await h.apply();
    assert.ok(!('faction_variant' in h.requests.at(-1)));assert.ok(!('faction_variant_version' in h.requests.at(-1)));
    assert.doesNotMatch(h.get('csv').href,/faction_variant/);
    const saved=JSON.parse(h.w.sessionStorage.getItem('gaia-cohort-filters'));
    for(const state of Object.values(saved)){assert.ok(!('faction_variant' in state));assert.ok(!('faction_variant_version' in state));}
   }
   assert.equal(fields.lf_2p_4qic_mode.value,'variant-only');
  }finally{h.close();}
 }
 // Cleanup also happens when invalid saved Elo prevents the first statistics request.
 const h=await harness({url:'http://localhost/',memories:{base:{faction_variant:'beta'},'lost-fleet':{min_elo:'0',faction_variant:'standard'}}});
 try{assert.equal(h.requests.length,0);assert.doesNotMatch(h.w.sessionStorage.getItem('gaia-cohort-filters'),/faction_variant/);}finally{h.close();}
});


test('player count defaults to 4; 4-QIC only submits for 2/Any and remembers hidden choices',async()=>{
 const h=await harness({url:'http://localhost/'});try{
  const fields=h.get('filters').elements, player=fields.player_count,variant=fields.lf_2p_4qic_mode;
  const choose=async(value)=>{player.value=value;player.dispatchEvent(new h.w.Event('change'));await h.apply();};
  assert.deepEqual([...player.options].map(o=>[o.value,o.text]),[['4','4'],['3','3'],['2','2'],['','Any']]);
  assert.equal(player.value,'4');assert.equal(h.requests.at(-1).player_count,'4');
  assert.equal(variant.disabled,true);assert.equal(variant.parentElement.hidden,true);assert.ok(!('lf_2p_4qic_mode' in h.requests.at(-1)));
  await choose('2');assert.equal(variant.disabled,false);assert.equal(variant.parentElement.hidden,false);assert.equal(h.requests.at(-1).lf_2p_4qic_mode,'standard-only');
  variant.value='variant-only';await h.apply();assert.equal(h.requests.at(-1).lf_2p_4qic_mode,'variant-only');
  await choose('3');assert.equal(variant.disabled,true);assert.equal(variant.parentElement.hidden,true);assert.ok(!('lf_2p_4qic_mode' in h.requests.at(-1)));
  assert.equal(JSON.parse(h.w.sessionStorage.getItem('gaia-cohort-filters'))['lost-fleet'].lf_2p_4qic_mode,'variant-only');
  await choose('');assert.equal(variant.disabled,false);assert.equal(variant.parentElement.hidden,false);assert.equal(variant.value,'variant-only');assert.ok(!('player_count' in h.requests.at(-1)));assert.equal(h.requests.at(-1).lf_2p_4qic_mode,'variant-only');
  await h.select('mode','base');assert.equal(player.value,'4');assert.equal(variant.disabled,true);assert.equal(variant.parentElement.hidden,true);assert.ok(!('lf_2p_4qic_mode' in h.requests.at(-1)));
  await h.select('mode','lost-fleet');assert.equal(player.value,'');assert.equal(variant.value,'variant-only');assert.equal(variant.disabled,false);assert.equal(h.requests.at(-1).lf_2p_4qic_mode,'variant-only');
 }finally{h.close();}
});

test('saved player count restores visibility; hidden variant requests cannot win races or reuse old cache',async()=>{
 for(const count of ['4','3','2','']){
  const h=await harness({url:'http://localhost/',memories:{'lost-fleet':{player_count:count,lf_2p_4qic_mode:'include-both'}}});
  try{const field=h.get('filters').elements.lf_2p_4qic_mode;assert.equal(field.disabled,['4','3'].includes(count));assert.equal(field.parentElement.hidden,field.disabled);assert.equal(h.requests.at(-1).lf_2p_4qic_mode,field.disabled?undefined:'include-both');}finally{h.close();}
 }
 const h=await harness({url:'http://localhost/',controlled:true,memories:{'lost-fleet':{player_count:'2',lf_2p_4qic_mode:'variant-only'}}});
 try{
  const stale=h.pending.shift();const player=h.get('filters').elements.player_count;
  player.value='4';player.dispatchEvent(new h.w.Event('change'));await h.apply();
  assert.equal(stale.signal.aborted,true);assert.equal(h.requests.at(-1).player_count,'4');assert.ok(!('lf_2p_4qic_mode' in h.requests.at(-1)));
  await h.flush();stale.resolve();await tick();await tick();assert.equal(h.w.testClient.getResult().filters.player_count,'4');
  const before=h.requests.length;await h.select('plot','advanced-tech-score');assert.equal(h.requests.length,before);
  player.value='2';player.dispatchEvent(new h.w.Event('change'));await h.apply();assert.equal(h.requests.length,before+1);assert.equal(h.requests.at(-1).lf_2p_4qic_mode,'variant-only');await h.flush();
 }finally{h.close();}
});

test('basic mode selection keeps scoring, advanced frequency and global comparisons intact',async()=>{
 const h=await harness();try{
  const comparison=h.get('comparison').firstChild;
  await h.select('frequency-view','position');
  for(const kind of ['basic-tech-frequency','basic-tech-score','basic-tech-setup-score']){
   await h.select('plot',kind);assert.equal(h.get('frequency-view-label').hidden,true);assert.equal(h.get('scoring-view-control').hidden,true);assert.equal(h.get('comparison').firstChild,comparison);assert.ok(h.draws.at(-1).length);
  }
  await h.select('plot','advanced-tech-frequency');assert.equal(h.get('frequency-view-label').hidden,false);assert.equal(h.get('frequency-view').value,'position');
  await h.select('plot','point-sources');assert.ok(h.draws.at(-1).every(t=>t.name.includes('rank')));
  assert.equal(h.w.document.querySelector('#filters [name=faction]'),null);assert.equal(h.w.document.querySelector('#chart-panel [name=faction]').form,h.get('filters'));
 }finally{h.close();}
});

test('layout uses distinct known catalog choices and never filters while hidden',async()=>{
 const original=fixtures['lost-fleet'].catalog.layout;
 try{
  for(const [values,visible] of [[[],false],[[null,'','unknown'],false],[['standard','standard','unknown'],false],[['standard','X'],true]]){
   fixtures['lost-fleet'].catalog.layout=values;
   const h=await harness({url:'http://localhost/',memories:{'lost-fleet':{layout:'standard'}}});
   try{
    const field=h.get('filters').elements.layout;
    assert.equal(field.disabled,!visible);assert.equal(field.parentElement.hidden,!visible);
    assert.equal(h.requests.at(-1).layout,visible?'standard':undefined);
    assert.equal(JSON.parse(h.w.sessionStorage.getItem('gaia-cohort-filters'))['lost-fleet'].layout,'standard');
    assert.equal(new Set([...field.options].map(o=>o.value)).size,field.options.length);
   }finally{h.close();}
  }
  fixtures['lost-fleet'].catalog.layout=['standard'];
  const h=await harness({url:'http://localhost/',memories:{'lost-fleet':{layout:'X'}}});
  try{
   assert.equal(h.get('filters').elements.layout.value,'');assert.ok(!('layout' in h.requests.at(-1)));
   await h.select('mode','base');fixtures['lost-fleet'].catalog.layout=['standard','X'];await h.select('mode','lost-fleet');
   assert.equal(h.get('filters').elements.layout.disabled,false);assert.equal(h.get('filters').elements.layout.value,'X');assert.equal(h.requests.at(-1).layout,'X');
   await h.select('mode','base');fixtures['lost-fleet'].catalog.layout=['standard'];await h.select('mode','lost-fleet');
   assert.equal(h.get('filters').elements.layout.disabled,true);assert.ok(!('layout' in h.requests.at(-1)));assert.equal(JSON.parse(h.w.sessionStorage.getItem('gaia-cohort-filters'))['lost-fleet'].layout,'X');
  }finally{h.close();}
 }finally{fixtures['lost-fleet'].catalog.layout=original;}
});

test('faction names are display-only title case across both modes',async()=>{
 const original=fixtures['lost-fleet'].catalog.faction;
 fixtures['lost-fleet'].catalog.faction=[...original,'space-giants'];
 const h=await harness({url:'http://localhost/'});
 try{
  const field=h.get('filters').elements.faction;
  assert.equal([...field.options].find(o=>o.value==='space-giants').text,'Space Giants');
  field.value='space-giants';field.dispatchEvent(new h.w.Event('change'));await tick();await tick();
  assert.equal(h.requests.at(-1).faction,'space-giants');assert.match(h.get('csv').href,/faction=space-giants/);
  await h.select('mode','base');
  for(const option of field.options)if(option.value)assert.equal(option.text,h.w.GaiaTiles.faction(option.value));
  await h.select('mode','lost-fleet');assert.equal(field.value,'space-giants');assert.equal(field.selectedOptions[0].text,'Space Giants');
  assert.match(readFileSync('web/classic/index.html','utf8'),/new Option\(GaiaTiles.faction\(faction\),faction\)/);
  assert.match(readFileSync('web/index.html','utf8'),/\['faction','opponent'\]\.includes\(key\)\?GaiaTiles.faction\(value\)/);
 }finally{h.close();fixtures['lost-fleet'].catalog.faction=original;}
});

test('Elo text input allows only empty or positive integers and never submits invalid values',async()=>{
 const h=await harness();try{
  const field=h.get('filters').elements.min_elo;
  assert.equal(field.type,'text');assert.equal(field.getAttribute('inputmode'),'numeric');assert.match(field.getAttribute('aria-describedby'),/elo-error/);
  const baseline=h.requests.length;
  for(const invalid of ['0','00','-1','1.5','1e3','abc',' 200','200 ']){
   field.value=invalid;field.dispatchEvent(new h.w.Event('input'));await h.apply();
   assert.equal(h.requests.length,baseline,invalid);assert.equal(field.checkValidity(),false);assert.equal(field.getAttribute('aria-invalid'),'true');assert.equal(h.get('elo-error').hidden,false);
  }
  // Both a chart change and a graph-faction change must also reject invalid text.
  await h.select('plot','point-sources');assert.equal(h.requests.length,baseline);
  field.value='200';field.dispatchEvent(new h.w.Event('input'));await h.apply();assert.equal(h.requests.at(-1).min_elo,'200');assert.equal(field.checkValidity(),true);assert.equal(field.getAttribute('aria-invalid'),'false');assert.equal(h.get('elo-error').hidden,true);
  field.value='';field.dispatchEvent(new h.w.Event('input'));await h.apply();assert.ok(!('min_elo' in h.requests.at(-1)));assert.equal(field.checkValidity(),true);
  field.value='001';field.dispatchEvent(new h.w.Event('input'));assert.equal(field.checkValidity(),true);
 }finally{h.close();}
});

test('restored invalid Elo exits loading accessibly and recovers after correction',async()=>{
 for(const value of ['0','1.5']){
  const h=await harness({url:'http://localhost/',memories:{'lost-fleet':{min_elo:value}}});
  try{
   assert.equal(h.requests.length,0);assert.equal(h.get('chart').getAttribute('aria-busy'),'false');
   assert.match(h.get('status').textContent,/positive whole-number Elo/);assert.match(h.get('chart').textContent,/Correct the Elo field/);assert.doesNotMatch(h.get('status').textContent,/Loading/);
   assert.equal(h.get('csv').getAttribute('href'),null);assert.equal(h.get('filters').elements.min_elo.getAttribute('aria-invalid'),'true');
   h.get('filters').elements.min_elo.value='200';await h.apply();assert.equal(h.requests.length,1);assert.equal(h.requests[0].min_elo,'200');assert.match(h.get('status').textContent,/ games · /);assert.equal(h.get('chart').getAttribute('aria-busy'),'false');
  }finally{h.close();}
 }
 const h=await harness({controlled:true});
 try{
  const stale=h.pending.shift();h.get('filters').elements.min_elo.value='0';await h.apply();assert.equal(stale.signal.aborted,true);
  stale.resolve();await tick();await tick();assert.equal(h.w.testClient.getResult(),null);assert.equal(h.get('chart').getAttribute('aria-busy'),'false');assert.match(h.get('status').textContent,/positive whole-number Elo/);
 }finally{h.close();}
});

test('native invalid input, Apply click and requestSubmit cancel pending responses before submit',async()=>{
 for(const action of ['input','click','requestSubmit'])for(const retained of [false,true]){
  const h=await harness({controlled:true});
  try{
   if(retained){await h.flush();h.get('filters').elements.min_elo.value='200';h.get('filters').requestSubmit();await tick();await tick();}
   const stale=h.pending.shift(),previous=h.w.testClient.getResult(),draws=h.draws.length;
   const field=h.get('filters').elements.min_elo;field.value='0';
   let submits=0;h.get('filters').addEventListener('submit',()=>submits++);
   if(action==='input')field.dispatchEvent(new h.w.Event('input'));
   else if(action==='click')h.get('filters').querySelector('button').click();
   else h.get('filters').requestSubmit();
   await tick();await tick();
   assert.equal(submits,0,action+' should be stopped by native validation');
   assert.equal(stale.signal.aborted,true,action);assert.equal(h.get('chart').getAttribute('aria-busy'),'false');assert.equal(h.get('chart-loading').hidden,true);assert.equal(h.get('chart-frame').inert,false);
   const requests=h.requests.length;assert.match(h.get('status').textContent,/positive whole-number Elo/);assert.equal(h.get('csv').getAttribute('href'),null);assert.equal(h.get('elo-error').hidden,false);assert.ok(field.validationMessage);
   stale.resolve();await tick();await tick();
   assert.equal(h.w.testClient.getResult(),previous);assert.equal(h.draws.length,draws);assert.equal(h.requests.length,requests);assert.equal(h.get('csv').getAttribute('href'),null);assert.match(h.get('status').textContent,/positive whole-number Elo/);
   field.value='';field.dispatchEvent(new h.w.Event('input'));h.get('filters').querySelector('button').click();await tick();await tick();await h.flush();
   assert.equal(submits,1);assert.equal(h.requests.length,requests+1);assert.equal(h.get('elo-error').hidden,true);assert.match(h.get('status').textContent,/ games · /);assert.ok(h.get('csv').getAttribute('href'));
  }finally{h.close();}
 }
});

test('point-source shorthand never merges distinct raw categories', async()=>{
 const h=await harness();
 try{
  await h.select('plot','point-sources');
  const plot=h.w.testClient.getResult().plots['point-sources'];
  const source=plot.rank_cells.find(c=>c.samples);
  plot.rank_cells=['research','tech_score'].map((label,i)=>({...source,label,median:10+i,q1:5+i,q3:15+i}));
  plot.cells=plot.rank_cells;
  await h.select('scoring-view','relative');
  let trace=h.draws.at(-1)[0],axis=h.get('chart').layout.xaxis;
  assert.deepEqual(Array.from(trace.x),['research','tech_score']);
  assert.deepEqual(Array.from(axis.tickvals),['research','tech_score']);
  assert.deepEqual(Array.from(axis.ticktext),['Research','Research']);
  assert.ok(trace.hovertext.every(text=>text.startsWith('Research<br>')));
  assert.doesNotMatch(trace.hovertemplate,/%\{x\}/);
  assert.equal(h.get('metrics').querySelectorAll('tbody tr').length,2);
  await h.select('scoring-view','absolute');
  const traces=h.draws.at(-1);
  assert.deepEqual(traces.map(t=>Array.from(t.x)[0]),['research','tech_score']);
  assert.deepEqual(traces.map(t=>t.median[0]),[10,11]);
  assert.ok(traces.every(t=>t.name==='Research'&&!t.hovertemplate.includes('%{x}')));
 }finally{h.close();}
});

test('loading overlay preserves the previous plot until fetching and rendering finish',async()=>{
 const h=await harness({controlled:true});
 try{
  const loading=active=>{assert.equal(h.get('chart-loading').hidden,!active);assert.equal(h.get('chart-frame').inert,active);assert.equal(h.get('chart').getAttribute('aria-busy'),String(active));};
  loading(true);assert.match(h.get('chart-loading-status').textContent,/Loading chart/);
  await h.flush();loading(false);
  const previous=h.get('chart').data,child=h.w.document.createElement('span');child.textContent='Previous plot pixels';h.get('chart').append(child);
  h.get('filters').elements.min_elo.value='200';h.get('filters').requestSubmit();await tick();
  loading(true);assert.equal(h.get('chart').data,previous);assert.equal(child.parentElement,h.get('chart'));assert.equal(h.get('status').textContent,'');
  assert.equal(h.get('chart-loading-status').getAttribute('role'),'status');assert.match(h.get('chart-loading-status').textContent,/Updating chart/);
  let finish;h.w.Plotly.react=()=>new Promise(resolve=>{finish=resolve;});
  await h.flush();loading(true);finish();await tick();loading(false);
  assert.match(h.get('chart-loading-status').textContent,/ games · /);
 }finally{h.close();}
});

test('only the current request can remove the loading overlay; cached and invalid selections clear it',async()=>{
 const h=await harness({controlled:true});
 try{
  await h.flush();await h.apply();const stale=h.pending.shift();
  await h.select('plot','round-one-structures');const latest=h.pending.shift();
  stale.resolve();await tick();await tick();assert.equal(h.get('chart-loading').hidden,false);assert.equal(h.get('chart-frame').inert,true);
  latest.resolve();await tick();await tick();assert.equal(h.get('chart-loading').hidden,true);
  await h.select('plot','point-sources');const superseded=h.pending.shift();
  await h.select('plot','round-one-structures');assert.equal(superseded.signal.aborted,true);assert.equal(h.get('chart-loading').hidden,true);
  superseded.resolve();await tick();await tick();assert.equal(h.get('chart-loading').hidden,true);
  await h.apply();const invalidated=h.pending.shift();h.get('filters').elements.min_elo.value='0';h.get('filters').querySelector('button').click();
  assert.equal(h.get('chart-loading').hidden,true);assert.equal(h.get('chart-frame').inert,false);assert.match(h.get('chart-loading-status').textContent,/positive whole-number Elo/);
  invalidated.resolve();await tick();await tick();assert.equal(h.get('chart-loading').hidden,true);
 }finally{h.close();}
});

test('API, network, rendering and catalog errors always dismiss the overlay and allow retry',async()=>{
 const h=await harness({controlled:true,controlledCatalog:true});
 const originalReact=h.plots.react;
 const resolveCatalog=async()=>{h.catalogs.shift().resolve();await tick();await tick();};
 try{
  await resolveCatalog();await h.flush();
  for(const failure of ['api','network','abort','render']){
   await h.apply();assert.equal(h.get('chart-loading').hidden,false);
   const request=h.pending.shift();
   if(failure==='api'){h.setFailures(true);request.resolve();}
   else if(failure==='network'||failure==='abort'){request.reject(Object.assign(new Error('Network failed'),{name:failure==='abort'?'AbortError':'Error'}));}
   else{h.w.Plotly.react=()=>Promise.reject(new Error('Rendering failed'));request.resolve();}
   await tick();await tick();assert.equal(h.get('chart-loading').hidden,true,failure);assert.equal(h.get('chart-frame').inert,false,failure);
   h.setFailures(false);h.w.Plotly.react=originalReact;await h.apply();await h.flush();assert.match(h.get('status').textContent,/ games · /);
  }
  await h.select('mode','lost-fleet');assert.equal(h.get('chart-loading').hidden,false);h.setFailures(true);await resolveCatalog();
  assert.equal(h.get('chart-loading').hidden,true);assert.equal(h.get('chart-frame').inert,false);assert.equal(h.get('chart-loading-status').textContent,'Temporary failure');
  h.setFailures(false);await h.apply();await resolveCatalog();await h.flush();assert.equal(h.get('chart-loading').hidden,true);
 }finally{h.close();}
});

test('spinner lives inside fullscreen chart workspace and respects reduced motion',()=>{
 assert.match(html,/id="chart-loading" hidden aria-hidden="true"/);
 const css=readFileSync('web/cohort/styles.css','utf8');
 assert.match(css,/@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.chart-spinner\s*\{ animation: none;/);
 assert.match(css,/body\.chart-focus #chart-stage \{ flex: 1; min-height: 0;/);
 const dom=new JSDOM(html);
 try{assert.ok(dom.window.document.querySelector('#chart-panel #chart-stage #chart-loading'));assert.ok(dom.window.document.querySelector('#chart-panel #chart-loading-status'));}finally{dom.window.close();}
});


test('mode error and restored invalid Elo purge retained Plotly state before replacing chart text',async()=>{
 for(const failure of ['catalog','invalid']){
  const h=await harness({memories:{'lost-fleet':{min_elo:failure==='invalid'?'0':''}}});
  try{
   assert.ok(h.get('chart').data);const purges=h.purges.length;
   if(failure==='catalog')h.setFailures(true);
   await h.select('mode','lost-fleet');
   assert.equal(h.get('chart').data,undefined,failure);assert.ok(h.purges.length>purges,failure);assert.equal(h.get('chart-loading').hidden,true);
   h.setFailures(false);h.get('filters').elements.min_elo.value='';await h.apply();assert.ok(h.get('chart').data);assert.equal(h.get('chart-loading').hidden,true);
  }finally{h.close();}
 }
});


test('front page omits source-slot scoring summaries but retains both detailed scoring charts',async()=>{
 const h=await harness();
 try{
  for(const id of ['round-comparison','final-comparison'])assert.equal(h.get(id),null);
  assert.doesNotMatch(h.w.document.body.textContent,/Round scoring VP|Final scoring VP|four comparison tables/);
  for(const kind of ['round-scoring','final-scoring']){
   h.get('filters').elements.faction.value='ivits';await h.select('plot',kind);
   if(kind==='round-scoring')await h.select('scoring-view','absolute');
   assert.equal(h.w.testClient.getResult().filters.faction,'ivits');
   assert.ok(h.get('chart').data?.some(trace=>trace.type==='heatmap'),kind);
   assert.ok(h.get('metrics').querySelector('table'),kind);
   for(const id of ['comparison','tech-comparison'])assert.ok(h.get(id).querySelector('table'),kind);
   assert.match(h.get('csv').href,new RegExp('plot='+kind));
  }
 }finally{h.close();}
});


test('opening explorer has no faction-balance selectors or hidden variant query filters',async()=>{
 const explorer=readFileSync('web/index.html','utf8');
 const dom=new JSDOM(explorer,{url:'http://localhost/explorer/',runScripts:'outside-only'}),w=dom.window,requests=[];
 w.fetch=async url=>{requests.push(new URL(url,w.location).searchParams);return {ok:true,json:async()=>({games:0,player_records:0,groups:[],rows:[],rejected_games:0,skill:{mode:'all',thresholds:{},rated_counts:{}},options:{faction_variant:['standard','beta','more-balanced'],faction_variant_version:['1'],auction:['bid']}})};};
 try{
  w.eval([...explorer.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1]);await tick();await tick();
  for(const mode of ['base','lost-fleet']){
   w.document.getElementById(mode).click();await tick();await tick();
   assert.doesNotMatch(w.document.getElementById('setup').textContent,/Faction balance|Balance version|more-balanced/);
   assert.equal(requests.at(-1).has('faction_variant'),false);assert.equal(requests.at(-1).has('faction_variant_version'),false);
   assert.doesNotMatch(w.document.getElementById('export').href,/faction_variant/);
  }
 }finally{w.close();}
});
