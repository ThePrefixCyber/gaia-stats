// Optional actual-Plotly browser check; run from repo root with Playwright, Chromium and plotting Python.
const {chromium}=require('playwright'),fs=require('fs'),cp=require('child_process'),assert=require('node:assert/strict');
const py=code=>cp.execFileSync(process.env.PYTHON||'python',['-c',code],{encoding:'utf8',maxBuffer:8*1024*1024});
const setup="import sys,json;sys.path.insert(0,'tests');from test_final_combinations import FinalCombinationTests;from gaia_stats.cohort import report,response;t=FinalCombinationTests();t.setUp();[r.update(round_scorings=['score1' if i!=1 else 'score2']*6) for i,g in enumerate(t.games) for r in g];d={'rows':[r for g in t.games for r in g],'scope':'test'};";
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const labels=py("from gaia_stats.cohort import response;print(response(None,'/cohort/tile-labels.js',{})[0].decode())");
 const plotly=py('from plotly.offline import get_plotlyjs;print(get_plotlyjs())');
 await page.route('http://gaia.test/**',async route=>{const u=new URL(route.request().url());let body,contentType='text/html';
 if(u.pathname==='/cohort/tile-labels.js'){body=labels;contentType='application/javascript';}
 else if(u.pathname==='/cohort/tables.js'){body=fs.readFileSync('web/cohort/tables.js','utf8');contentType='application/javascript';}
 else if(u.pathname==='/cohort/styles.css'){body=fs.readFileSync('web/cohort/styles.css','utf8');contentType='text/css';}
 else if(u.pathname==='/cohort/app.js'){body=fs.readFileSync('web/cohort/app.js','utf8');contentType='application/javascript';}
 else if(u.pathname.includes('plotly')){body=plotly;contentType='application/javascript';}
 else if(u.pathname.endsWith('/catalog')){body=py(setup+"print(response(d,'/cohort/api/catalog',{})[0].decode())");contentType='application/json';}
 else if(u.pathname.endsWith('/stats')){body=py(setup+`print(json.dumps(report(d,json.loads(${JSON.stringify(JSON.stringify(Object.fromEntries(u.searchParams)))}))))`);contentType='application/json';}
 else body=fs.readFileSync('web/cohort/index.html','utf8');await route.fulfill({body,contentType});});
 await page.goto('http://gaia.test/?ruleset=lost-fleet');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('games'));
 await page.selectOption('#plot','round-scoring');await page.waitForFunction(()=>document.querySelector('#chart').textContent.includes('Choose a faction'));
 await page.selectOption('select[name="faction"]','terrans');await page.locator('#filters').evaluate(f=>f.requestSubmit());
 await page.waitForFunction(()=>document.querySelector('#chart').data?.[1]?.z?.flat().includes(25));
 let traces=await page.locator('#chart').evaluate(e=>e.data);
 assert.ok(traces[1].z.flat().includes(-50));
 assert.ok(traces[1].text.flat().some(t=>t.includes('faction baseline=50.00% (n=3)')));
 await page.selectOption('#scoring-view','absolute');
 await page.waitForFunction(()=>document.querySelector('#chart').data?.[1]?.z?.flat().includes(75));
 await page.selectOption('#scoring-view','relative');
 await page.waitForFunction(()=>document.querySelector('#chart').data?.[1]?.z?.flat().includes(25));
 await page.locator('#chart').screenshot({path:'/tmp/gaia-round-deltas.png'});
 await page.selectOption('#plot','point-sources');
 await page.waitForFunction(()=>document.querySelector('#chart').layout?.yaxis?.title?.text==='Signed share of final net score (%)');
 traces=await page.locator('#chart').evaluate(e=>e.data);
 assert.ok(traces.every(t=>t.type==='box'&&t.name.includes('rank')));
 const expected=JSON.parse(py(setup+"print(json.dumps(report(d,{'ruleset':'lost-fleet','plot':'point-sources','faction':'terrans'})['plots']['point-sources']['rank_cells']))"));
 for(const c of expected.filter(c=>c.samples)){
   const trace=traces.find(t=>t.name===`${c.player_count}p · rank ${c.rank}`);
   assert.ok(trace);assert.ok(trace.median.includes(c.median));
 }
 await page.getByText('Exact chart observations',{exact:true}).click();
 assert.ok((await page.locator('#metrics th').allTextContents()).some(t=>t.includes('Median score share (%)')));
 await page.locator('#chart').screenshot({path:'/tmp/gaia-point-shares.png'});
 await page.selectOption('#scoring-view','absolute');
 await page.waitForFunction(()=>document.querySelector('#chart').layout?.yaxis?.title?.text==='VP contribution (signed)');
 await page.selectOption('#scoring-view','relative');
 await page.waitForFunction(()=>document.querySelector('#chart').layout?.yaxis?.title?.text==='Signed share of final net score (%)');
 await page.setViewportSize({width:390,height:844});await page.waitForTimeout(300);
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:'/tmp/gaia-point-shares-mobile.png'});
 assert.deepEqual(errors,[]);console.log('Actual Plotly: round deltas, baseline denominators, rank-share boxes, both retained absolute modes, repeated switches and mobile layout passed');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
