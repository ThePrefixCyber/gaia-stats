// Actual cached Plotly labels; statistical arrays and count metadata must survive.
const {chromium}=require('playwright'),cp=require('child_process'),assert=require('node:assert/strict');
const py=process.env.PYTHON||'python';
const pages=JSON.parse(cp.execFileSync(py,['-c',`
import json,tempfile
from pathlib import Path
import pandas as pd
from gaia_stats.legacy_plots import make_plot
from gaia_stats.legacy_cache import cache_response
from plotly.offline import get_plotlyjs
frame=pd.read_csv('data/remote_four_players_data.csv')
out={}
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp);base=root/'build-test';(base/'plots').mkdir(parents=True)
 (root/'current.json').write_text(json.dumps({'build':'build-test'}))
 for kind in ('basic-tech-frequency','basic-tech-score','advanced-tech-frequency','advanced-tech-score','round-scoring','final-scoring','point-sources'):
  fig=make_plot(kind,frame,players=4,faction='terrans')
  fig.write_html(base/'plots'/f'4-terrans-{kind}.html',include_plotlyjs='/plotly.js')
  body=cache_response(root,'/classic/plot',{'players':'4','faction':'terrans','plot':kind})[0]
  out[kind]={'html':body.decode(),'data':json.loads(fig.to_json())['data']}
 print(json.dumps(out))
`],{encoding:'utf8',maxBuffer:30*1024*1024}));
const plotly=cp.execFileSync(py,['-c','from plotly.offline import get_plotlyjs;print(get_plotlyjs())'],{encoding:'utf8',maxBuffer:8*1024*1024});
(async()=>{const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});try{
const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('http://legacy.test/**',route=>route.fulfill({body:route.request().url().endsWith('plotly.js')?plotly:pages[new URL(route.request().url()).pathname.slice(1)].html,contentType:route.request().url().endsWith('.js')?'application/javascript':'text/html'}));
for(const [kind,item] of Object.entries(pages)){
 await page.goto('http://legacy.test/'+kind);await page.waitForTimeout(300);
 const data=await page.locator('.js-plotly-plot').evaluate(e=>e.data);
 data.forEach((t,i)=>{for(const key of ['x','y','z','customdata'])assert.deepEqual(t[key],item.data[i][key],kind+' '+key);});
 if(kind==='point-sources'){
  const expected=item.data.map(t=>t.name);assert.equal(new Set(expected).size,4);assert.ok(expected.every(n=>/^bid-restored order [1-4] \(ties broken by original player order\)$/.test(n)));
  assert.deepEqual(data.map(t=>t.name),expected,'finishing-order identities and historical tie convention survive');
  assert.deepEqual(await page.locator('.legendtext').allTextContents(),expected,'actual rendered legend preserves all four finishing orders');
 }
 const text=await page.locator('.js-plotly-plot').innerText();assert.doesNotMatch(text,/advtech\d|tech\d|ship-tech-|_per_|Unknown location/);
}
assert.deepEqual(errors,[]);console.log('Seven actual cached plot families relabelled without changing coordinates, values or sample metadata');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
