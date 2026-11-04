// Optional smoke test: run from repository root with Playwright and Chromium installed.
// Fixture API and Plotly capture are mocked; this checks DOM and trace construction, not visual rendering.
const {chromium}=require('playwright'),fs=require('fs'),cp=require('child_process'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM || '/usr/bin/chromium',args:['--no-sandbox']});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const asset=cp.execFileSync(process.env.PYTHON || 'python',['-c',"from gaia_stats.cohort import response; print(response(None,'/cohort/tile-labels.js',{})[0].decode())"],{encoding:'utf8'});
 const data=JSON.parse(cp.execFileSync(process.env.PYTHON || 'python',['-c',`import json
from pathlib import Path
from gaia_stats.analysis import normalize
from gaia_stats.cohort import enrich,report,response
g=json.loads(Path('tests/fixtures/Jubilant-rover-3041.json').read_text())
d={'rows':enrich(g,normalize(g))}
print(json.dumps({'catalog':json.loads(response(d,'/cohort/api/catalog',{})[0]),'stats':report(d,{'ruleset':'lost-fleet'})}))`],{encoding:'utf8'}));
 const queries=[];
 await page.route('http://gaia.test/**',async route=>{const url=new URL(route.request().url());let body,contentType='text/html';
 if(url.pathname==='/cohort/tile-labels.js'){body=asset;contentType='application/javascript';}
 else if(url.pathname==='/cohort/tables.js'){body=fs.readFileSync('web/cohort/tables.js','utf8');contentType='application/javascript';}
 else if(url.pathname==='/cohort/styles.css'){body=fs.readFileSync('web/cohort/styles.css','utf8');contentType='text/css';}
 else if(url.pathname==='/cohort/app.js'){body=fs.readFileSync('web/cohort/app.js','utf8');contentType='application/javascript';}
 else if(url.pathname.includes('plotly')){body='window.Plotly={purge(){},newPlot(el,traces,layout){window.lastPlot={traces,layout};}}';contentType='application/javascript';}
 else if(url.pathname.endsWith('/catalog')){body=JSON.stringify(data.catalog);contentType='application/json';}
 else if(url.pathname.endsWith('/stats')){queries.push(url.search);body=JSON.stringify(data.stats);contentType='application/json';}
 else body=fs.readFileSync('web/cohort/index.html','utf8');
 await route.fulfill({body,contentType});});
 await page.goto('http://gaia.test/?ruleset=lost-fleet');await page.waitForFunction(()=>window.lastPlot,{},{timeout:5000}).catch(async e=>{console.log(await page.locator('#status').textContent(),errors);throw e});
 const option=await page.locator('select[name="adv-terra"] option').nth(1).textContent();assert.match(option,/\[advtech/);
 const value=await page.locator('select[name="adv-terra"] option').nth(1).getAttribute('value');await page.getByText('Match scoring setup',{exact:true}).click();await page.selectOption('select[name="adv-terra"]',value);await page.locator('#filters').evaluate(f=>f.requestSubmit());await page.waitForTimeout(100);assert.ok(queries.at(-1).includes('adv-terra='+value));
 for(const kind of ['advanced-tech-frequency','advanced-tech-score','basic-tech-frequency','basic-tech-score','round-scoring','final-scoring','point-sources','round-one-structures']){await page.selectOption('#plot',kind);await page.waitForTimeout(80);const text=await page.locator('#metrics').textContent();if(kind.includes('tech-'))assert.match(text,/\[(advtech|tech|ship-tech)/);if(kind==='round-scoring'){const p=await page.evaluate(()=>window.lastPlot);assert.equal(p.layout.xaxis.ticktext[0],'Round 1');assert.match(p.layout.yaxis.ticktext[0],/This round:/);}}
 assert.deepEqual(errors,[]);await browser.close();console.log('Browser: eight chart modes, readable selectors/ticks/tables, raw filter values, no page errors passed');
})().catch(e=>{console.error(e);process.exit(1)});
