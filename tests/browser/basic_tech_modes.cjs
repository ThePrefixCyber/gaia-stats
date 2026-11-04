// Actual Plotly rendering, fixture data only. PYTHON=... node tests/browser/basic_tech_modes.cjs
const {chromium}=require('playwright'),fs=require('fs'),cp=require('child_process'),assert=require('node:assert/strict');
const py=code=>cp.execFileSync(process.env.PYTHON||'python',['-c',code],{encoding:'utf8',maxBuffer:8*1024*1024});
const setup="import json;from pathlib import Path;from gaia_stats.analysis import normalize;from gaia_stats.cohort import enrich,report,response;g=json.loads(Path('tests/fixtures/Jubilant-rover-3041.json').read_text());d={'rows':enrich(g,normalize(g)),'scope':'fixture'};";
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[],queries=[];page.on('pageerror',e=>errors.push(e.message));
  const labels=py("from gaia_stats.cohort import response;print(response(None,'/cohort/tile-labels.js',{})[0].decode())"),plotly=py('from plotly.offline import get_plotlyjs;print(get_plotlyjs())');
  await page.route('http://gaia.test/**',async route=>{const u=new URL(route.request().url());let body,contentType='text/html';
   if(u.pathname==='/cohort/tile-labels.js'){body=labels;contentType='application/javascript';}
   else if(['/cohort/app.js','/cohort/tables.js','/cohort/basic-tech.js'].includes(u.pathname)){body=fs.readFileSync('web'+u.pathname,'utf8');contentType='application/javascript';}
   else if(u.pathname==='/cohort/styles.css'){body=fs.readFileSync('web/cohort/styles.css','utf8');contentType='text/css';}
   else if(u.pathname.includes('plotly')){body=plotly;contentType='application/javascript';}
   else if(u.pathname.endsWith('/catalog')){body=py(setup+"print(response(d,'/cohort/api/catalog',{})[0].decode())");contentType='application/json';}
   else if(u.pathname.endsWith('/stats')){queries.push(u.searchParams.get('plot'));body=py(setup+`print(json.dumps(report(d,json.loads(${JSON.stringify(JSON.stringify(Object.fromEntries(u.searchParams)))}))))`);contentType='application/json';}
   else body=fs.readFileSync('web/cohort/index.html','utf8');await route.fulfill({body,contentType});
  });
  await page.goto('http://gaia.test/?ruleset=lost-fleet');await page.waitForFunction(()=>document.querySelector('#chart').data?.length);
  for(const kind of ['basic-tech-frequency','basic-tech-score','basic-tech-setup-score']){
   await page.selectOption('#plot',kind);await page.waitForFunction(k=>result?.plots[k]&&document.querySelector('#chart').getAttribute('aria-busy')==='false',kind);
   await page.waitForTimeout(180);
   const chart=await page.locator('#chart').evaluate(e=>({data:e.data,layout:e.layout}));
   if(kind==='basic-tech-frequency'){
    assert.equal(chart.layout.shapes.length,11);for(const a of chart.layout.annotations.filter(a=>a.y===1.04)){const rgb=a.font.color.match(/[a-f\d]{2}/gi).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);assert.ok(1.05/(rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722+.05)>=4.5,'heading contrast '+a.text);}assert.ok(chart.layout.annotations.some(a=>a.text==='Twilight'));assert.ok(chart.layout.annotations.some(a=>a.text==='No tech slot'));
    assert.equal(chart.layout.annotations.filter(a=>a.text==='Free').length,1);
   }else{
    assert.equal(chart.layout.yaxis.tickvals.length,new Set(chart.layout.yaxis.tickvals).size);
    assert.ok(chart.layout.yaxis.ticktext.includes('1o3k'));
    const ship=chart.data.find(t=>t.name==='TF Mars'),i=ship.y.indexOf('ship-tech-resource');
    assert.equal(ship.x[i],kind==='basic-tech-score'?159.5:139.75);
    assert.equal(ship.customdata[i][1],kind==='basic-tech-score'?2:4);
    assert.ok(chart.layout.shapes.some(s=>s.line?.dash==='dot'&&s.x0===139.75));
    if(kind==='basic-tech-score'){assert.ok(chart.data.some(t=>t.name==='Taken'));assert.ok(chart.data.some(t=>t.name==='Not taken'));}
   }
   await page.locator('#chart-focus').click();await page.waitForTimeout(180);
   assert.equal(await page.locator('#chart-focus').getAttribute('aria-pressed'),'true');
   const bounds=await page.locator('#chart-panel').boundingBox();assert.equal(bounds.width,1600);assert.equal(bounds.height,1000);
   await page.locator('#chart-panel').screenshot({path:'/tmp/gaia-'+kind+'.png'});
   await page.keyboard.press('Escape');assert.equal(await page.locator('#chart-focus').getAttribute('aria-pressed'),'false');
  }
  for(const kind of ['basic-tech-frequency','basic-tech-score','basic-tech-setup-score'])assert.equal(queries.filter(q=>q===kind).length,1);
  // Internal coordinates remain distinct when two tiles have identical shorthand.
  const distinct=await page.evaluate(()=>{const cells=[{tile_id:'score7',location_id:'terra',samples:1,mean_score:100,games:1},{tile_id:'score10',location_id:'terra',samples:1,mean_score:120,games:1}];const b=GaiaBasicTech.build('basic-tech-setup-score',cells,{mean_score:110},1000,700);return {y:b.traces[0].y,ticks:b.layout.yaxis.ticktext};});
  assert.equal(new Set(distinct.y).size,2);assert.equal(distinct.ticks[0],distinct.ticks[1]);
  await page.evaluate(()=>{for(const d of document.querySelectorAll('details'))d.open=true;});
  const visible=await page.locator('body').innerText(),aria=await page.locator('[aria-label]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('aria-label')).join(' '));
  assert.doesNotMatch(visible,/\btech\d+\b|advtech\d+|ship-tech-|tech-free|k_per_terra/);assert.doesNotMatch(aria,/tech\d+|ship-tech-/);
  await page.selectOption('#plot','basic-tech-score');await page.waitForTimeout(120);
  await page.evaluate(()=>{const e=document.querySelector('#chart'),t=e.data.findIndex(t=>t.name==='TF Mars');Plotly.Fx.hover(e,[{curveNumber:t,pointNumber:e.data[t].y.indexOf('ship-tech-resource')}]);});
  assert.doesNotMatch(await page.locator('#chart .hoverlayer').textContent(),/ship-tech-|tech\d+/);
  // Exercise all 14 legend entries, including a track absent from this game's acquisitions.
  await page.evaluate(()=>{const cells=result.plots['basic-tech-score'].cells;if(!cells.some(c=>c.location_id==='int'&&c.samples))cells.push({...cells.find(c=>c.samples),location_id:'int'});});
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(250);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.locator('#chart-focus').click();await page.waitForTimeout(150);assert.equal((await page.locator('#chart-panel').boundingBox()).width,390);assert.equal(await page.locator('#chart .legendtext').count(),14);const axis=await page.locator('#chart .xtitle').boundingBox();for(const entry of await page.locator('#chart .legendtext').all()){const legend=await entry.boundingBox();assert.ok(axis.y+axis.height+4<=legend.y,JSON.stringify({axis,legend}));}await page.locator('#chart-panel').screenshot({path:'/tmp/gaia-basic-tech-mobile.png'});await page.keyboard.press('Escape');
  assert.equal(await page.locator('#filters [name=faction]').count(),0);assert.equal(await page.locator('#chart-panel [name=faction]').count(),1);
  await page.locator('#chart-focus').click();const faction=await page.locator('[name=faction] option').nth(1).getAttribute('value');await page.selectOption('[name=faction]',faction);await page.waitForFunction(f=>result?.filters.faction===f&&document.querySelector('#chart').getAttribute('aria-busy')==='false',faction);assert.equal(await page.locator('[name=faction]').isEnabled(),true);await page.keyboard.press('Escape');
  assert.equal(await page.locator('#scope').textContent(),'');assert.equal(await page.locator('#scope').isVisible(),false);assert.deepEqual(errors,[]);console.log('Three basic-tech modes: actual Plotly, fixture means/counts, 11 buckets, no exposed IDs, separate cache, focus/escape/mobile passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
