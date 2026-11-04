'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const {execFileSync} = require('node:child_process');
const {JSDOM} = require('jsdom');

const fixture = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c', `
import json
from pathlib import Path
from gaia_stats.analysis import normalize
from gaia_stats.cohort import enrich, report, response
game=json.loads(Path('tests/fixtures/Modern-riddle-1723.json').read_text())
data={'rows':enrich(game,normalize(game)),'scope':'Comparison regression fixture'}
print(json.dumps({'catalog':json.loads(response(data,'/cohort/api/catalog',{'ruleset':'base'})[0]),
    'stats':{faction+':'+cutoff:report(data,{'ruleset':'base','faction':faction,'min_elo':cutoff})
             for faction in ('','firaks','lantids') for cutoff in ('','200')}}))
`], {encoding:'utf8'}));
const tick = () => new Promise(resolve => setImmediate(resolve));

test('faction changes only the graph cohort, keeping sorted all-faction comparisons and separated counts', async()=>{
  const dom=new JSDOM(readFileSync('web/cohort/index.html','utf8'), {url:'http://localhost/',runScripts:'outside-only'});
  const w=dom.window, get=id=>w.document.getElementById(id);
  const apply=async()=>{get('filters').dispatchEvent(new w.Event('submit',{cancelable:true}));await tick();await tick();};
  const factions=id=>[...get(id).querySelectorAll('tbody tr')].map(row=>row.cells[0].textContent);
  w.Plotly={react(target,traces){target.data=traces;return Promise.resolve();},purge(target){delete target.data;}};
  w.fetch=async url=>{
    const q=new URL(url,w.location).searchParams;
    let data=url.includes('/catalog')?fixture.catalog:fixture.stats[(q.get('faction')||'')+':'+(q.get('min_elo')||'')];
    data=structuredClone(data);
    if(data.plots){data.filters=Object.fromEntries(q);data.plots={[q.get('plot')]:data.plots[q.get('plot')]};}
    return {ok:true,json:async()=>data};
  };
  try{
    w.eval(readFileSync('web/cohort/tile-labels.js','utf8').replace('__TILE_REGISTRY__',readFileSync('web/cohort/tile-labels.json','utf8')));
    w.eval(readFileSync('web/cohort/tables.js','utf8'));
    w.eval(readFileSync('web/cohort/app.js','utf8')+'\nwindow.currentResult=()=>result;');
    await tick();await tick();
    const targets=['comparison','round-comparison','final-comparison','tech-comparison'];
    for(const id of targets)assert.equal(factions(id).length,4);
    const table=get('comparison').firstChild;
    get('comparison').querySelector('button').click();
    const ordered=factions('comparison');
    w.document.querySelector('[name=faction]').value='firaks';await apply();
    assert.equal(w.currentResult().samples,1);
    assert.deepEqual(Array.from(w.currentResult().record_ids),fixture.stats['firaks:'].record_ids);
    assert.equal(get('comparison').firstChild,table);
    assert.deepEqual(factions('comparison'),ordered);
    for(const id of targets)assert.equal(factions(id).length,4);
    assert.match(get('csv').href,/faction=firaks/);
    const sampled=get('tech-comparison').querySelector('td[aria-label]');
    assert.match(sampled.textContent,/ VP \(1 sample\)$/);
    assert.match(sampled.getAttribute('aria-label'),/ VP; 1 sample$/);

    w.document.querySelector('[name=faction]').value='lantids';
    w.document.querySelector('[name=min_elo]').value='200';await apply();
    assert.equal(w.currentResult().samples,0);
    assert.match(get('chart').textContent,/No observations/);
    for(const id of targets){assert.equal(factions(id).length,3);assert.ok(!factions(id).includes('Lantids'));}
    w.document.querySelector('[name=faction]').value='';await apply();
    assert.equal(w.currentResult().samples,3);
    assert.ok(get('chart').data.length);
    assert.equal(factions('comparison').length,3);
  }finally{w.close();}
});
