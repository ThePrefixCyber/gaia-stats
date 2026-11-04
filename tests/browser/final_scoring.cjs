// Optional actual-Plotly browser check; run from repo root with Playwright, Chromium and plotting Python.
const {chromium}=require('playwright'),fs=require('fs'),cp=require('child_process'),assert=require('node:assert/strict');
const py=code=>cp.execFileSync(process.env.PYTHON||'python',['-c',code],{encoding:'utf8',maxBuffer:8*1024*1024});
const setup="import sys,json;sys.path.insert(0,'tests');from test_final_combinations import FinalCombinationTests;from gaia_stats.cohort import report,response;t=FinalCombinationTests();t.setUp();d={'rows':[r for g in t.games for r in g],'scope':'test'};";
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const labels=py("from gaia_stats.cohort import response;print(response(None,'/cohort/tile-labels.js',{})[0].decode())");
 const plotly=py('from plotly.offline import get_plotlyjs;print(get_plotlyjs())');
 await page.route('http://gaia.test/**',async route=>{const u=new URL(route.request().url());let body,contentType='text/html';
 if(u.pathname==='/cohort/tile-labels.js'){body=labels;contentType='application/javascript';}
 else if(u.pathname==='/cohort/app.js'){body=fs.readFileSync('web/cohort/app.js','utf8');contentType='application/javascript';}
 else if(u.pathname.includes('plotly')){body=plotly;contentType='application/javascript';}
 else if(u.pathname.endsWith('/catalog')){body=py(setup+"print(response(d,'/cohort/api/catalog',{})[0].decode())");contentType='application/json';}
 else if(u.pathname.endsWith('/stats')){body=py(setup+`print(json.dumps(report(d,json.loads(${JSON.stringify(JSON.stringify(Object.fromEntries(u.searchParams)))}))))`);contentType='application/json';}
 else body=fs.readFileSync('web/cohort/index.html','utf8');await route.fulfill({body,contentType});});
 await page.goto('http://gaia.test/?ruleset=lost-fleet');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('games'));
 await page.selectOption('#plot','final-scoring');await page.waitForFunction(()=>document.querySelector('#chart').textContent.includes('Choose a faction'));
 await page.selectOption('select[name="faction"]','terrans');await page.locator('#filters').evaluate(f=>f.requestSubmit());
 await page.waitForFunction(()=>document.querySelector('#chart').data?.length===2);
 const traces=await page.locator('#chart').evaluate(e=>e.data);
 assert.deepEqual(traces[0].z,[[9],[-18]]);assert.deepEqual(traces[1].z,[[25],[-50]]);
 assert.match(traces[1].text[0][0],/faction baseline across pairs=50.00% \(win n=3\)/);
 assert.match(traces[0].text[0][0],/VP n=8/);
 const headings=await page.locator('#metrics th').allTextContents();
 const values=await page.locator('#metrics tbody tr').first().locator('td').allTextContents();
 assert.equal(values[headings.indexOf('Shared wins (%)')],'75.00');
 assert.equal(values[headings.indexOf('Faction win baseline (%)')],'50.00');
 assert.equal(values[headings.indexOf('Win difference (percentage points)')],'25.00');
 await page.locator('#chart').screenshot({path:process.env.SCREENSHOT||'/tmp/gaia-final-scoring.png'});
 assert.deepEqual(errors,[]);console.log('Actual Plotly: faction-required state, two delta heatmaps, exact baselines and denominators passed');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
