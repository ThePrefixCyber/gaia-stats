'use strict';
const form=document.querySelector('#filters'), el=id=>document.getElementById(id);
const names={'advanced-tech-frequency':'Advanced tech: frequency / rank','advanced-tech-score':'Advanced tech: position / score','basic-tech-frequency':'Basic tech 1 · Acquisition by setup','basic-tech-score':'Basic tech 2 · Score when taken','basic-tech-setup-score':'Basic tech 3 · Score by setup','round-one-structures':'Round-one structures: frequency / score','final-scoring':'Final scoring by faction and pair','round-scoring':'Round scoring preferences','point-sources':'Point-source breakdown'};
for(const [value,label] of Object.entries(names))el('plot').add(new Option(label,value));
let result=null, generation=0, memories={};
let requestController=null, pendingKey=null, comparisonSignature=null, plotlyFailed=false;
let cachedCohort=null, loadedMode=null;
const responses=new Map(), RESPONSE_TTL=60_000;
function cancelRequest(){if(requestController)requestController.abort();requestController=null;pendingKey=null;}
function cacheKey(q){const key=new URLSearchParams(q);key.sort();return key.toString();}
function cachedResponse(q){
 const key=cacheKey(q),kind=q.get('plot');
 let entry=responses.get(key);
 // Frequency and score views use exactly the same technology observations.
 if(!entry&&kind.startsWith('advanced-tech-')){
  const alternate=new URLSearchParams(q);
  alternate.set('plot',kind.endsWith('frequency')?kind.replace('frequency','score'):kind.replace('score','frequency'));
  const source=responses.get(cacheKey(alternate));
  if(source){const plot=source.data.plots[alternate.get('plot')];entry={time:source.time,data:{...source.data,filters:{...source.data.filters,plot:kind},plots:{[kind]:{...plot,kind}}}};}
 }
 return entry&&Date.now()-entry.time<RESPONSE_TTL?entry.data:null;
}
try{memories=JSON.parse(sessionStorage.getItem('gaia-cohort-filters')||'{}');}catch{}
let rememberedMode;try{rememberedMode=sessionStorage.getItem('gaia-cohort-mode');}catch{}
const explicitMode=new URLSearchParams(location.search).get('ruleset');const initialMode=['base','lost-fleet'].includes(explicitMode)?explicitMode:rememberedMode;if(['base','lost-fleet'].includes(initialMode))el('mode').value=initialMode;
function save(){if(!loadedMode||form.querySelector('fieldset').disabled)return;memories[loadedMode]={...Object.fromEntries(new FormData(form)),plot:el('plot').value,frequency_view:el('frequency-view').value,lf_2p_4qic_mode:form.elements.lf_2p_4qic_mode.value,layout:form.elements.layout.disabled?(memories[loadedMode]?.layout||''):form.elements.layout.value};try{sessionStorage.setItem('gaia-cohort-filters',JSON.stringify(memories));}catch{}}
function syncVariantControl(){const field=form.elements.lf_2p_4qic_mode;const visible=el('mode').value==='lost-fleet'&&['','2'].includes(form.elements.player_count.value);field.disabled=!visible;field.parentElement.hidden=!visible;}
function syncLayoutControl(){const field=form.elements.layout;const known=new Set([...field.options].map(option=>option.value).filter(value=>value&&!['unknown','any'].includes(value.trim().toLowerCase())));field.disabled=known.size<=1;field.parentElement.hidden=field.disabled;}
function validateElo(){const field=form.elements.min_elo;const valid=field.value===''||/^0*[1-9][0-9]*$/.test(field.value);field.setCustomValidity(valid?'':'Enter a positive whole-number Elo, or leave this field empty.');field.setAttribute('aria-invalid',String(!valid));el('elo-error').hidden=valid;return valid;}
function rejectInvalidElo(){
 // Native constraint validation may prevent submit entirely. Invalidate pending
 // work from input/invalid events too, before a late response can restore it.
 cancelRequest();++generation;el('chart').setAttribute('aria-busy','false');el('csv').removeAttribute('href');
 el('status').textContent='Enter a positive whole-number Elo, or leave this field empty.'+(result?' Previous results remain visible.':'');
 if(!result)el('chart').textContent='Correct the Elo field, then apply filters to load the chart.';
}
function onEloInput(){if(!validateElo())rejectInvalidElo();}
function query(){syncVariantControl();syncLayoutControl();const q=new URLSearchParams(new FormData(form));q.set('ruleset',el('mode').value);q.set('plot',el('plot').value);for(const [key,value] of [...q])if(value==='')q.delete(key);return q;}
function table(target,rows,columns,options){GaiaTables.render(target,rows,columns,options);}
// Fixed score landmarks: filtering changes the visible range, never a score's
// color. Smooth tails distinguish values outside the usual 0–300 VP range.
function treemapScoreColor(score){
 const red='#ff3b30',grey='#d1d5db',blue='#081d58',green='#22c55e';
 const blend=(a,b,t)=>'#'+[1,3,5].map(i=>Math.round(parseInt(a.slice(i,i+2),16)*(1-t)+parseInt(b.slice(i,i+2),16)*t).toString(16).padStart(2,'0')).join('');
 if(score<0)return blend(red,'#7f1d1d',1-100/(100-score));
 if(score<=100)return blend(red,grey,score/100);
 if(score<=150)return blend(grey,'#5b8ac6',(score-100)/50);
 if(score<=200)return blend('#5b8ac6',blue,(score-150)/50);
 if(score<=225)return blend(blue,'#166534',(score-200)/25);
 if(score<=300)return blend('#166534',green,(score-225)/75);
 return blend(green,'#bbf7d0',1-100/(score-200));
}
function treemapScoreStyle(values){
 const observed=values.filter(Number.isFinite);
 const low=Math.min(0,...observed),high=Math.max(300,...observed);
 // Explicit colors keep unavailable observations separate from both red 0 and
 // grey 100. Plotly permits color strings alongside numeric marker values.
 const marker={colors:values.map(value=>Number.isFinite(value)?value:'#ffffff'),
  autocolorscale:false,reversescale:false,cauto:false,cmin:low,cmax:high,
  showscale:observed.length>0,colorbar:{title:'Mean net VP',tickmode:'array',tickformat:'.4~g'}};
 // Every observed score is a stop, so nonlinear tail colors remain identical
 // across selections as well. Interpolate continuously between distinct stops.
 const stops=[...new Set([low,0,50,100,150,200,225,300,high,...observed])].sort((a,b)=>a-b);
 marker.colorscale=stops.map(score=>[(score-low)/(high-low),treemapScoreColor(score)]);
 marker.colorbar.tickvals=[...(low<0?[low]:[]),0,100,200,300,...(high>300?[high]:[])];
 const note=observed.length
  ? 'Fixed score colors: 0 VP = bright red; 100 VP = grey; 200 VP = dark blue. Above 200, blue blends into green; higher values become lighter green.'+(low<0?' Negative scores use darker reds.':'')+(observed.length<values.length?' White tiles have unavailable mean net VP.':'')
  : 'Mean net VP is unavailable; white tiles have no score color scale.';
 return {marker,note};
}
// Match Tim's root → highest structure class → exact six-count configuration.
// Parents carry totals, and their score/Elo colors are observation-weighted.
function openingTree(cells,rootLabel){
 const nodes=[],classes=new Map();
 const summarize=(id,label,parent,group)=>{
  const samples=group.reduce((sum,c)=>sum+c.samples,0);
  const scored=group.filter(c=>Number.isFinite(c.mean_score));
  const scoreN=scored.reduce((sum,c)=>sum+c.samples,0);
  const rated=group.filter(c=>Number.isFinite(c.mean_elo)&&c.mean_elo_n>0);
  const eloN=rated.reduce((sum,c)=>sum+c.mean_elo_n,0);
  return {id,label,parent,samples,
   mean_score:scoreN?scored.reduce((sum,c)=>sum+c.mean_score*c.samples,0)/scoreN:null,
   mean_elo:eloN?rated.reduce((sum,c)=>sum+c.mean_elo*c.mean_elo_n,0)/eloN:null,mean_elo_n:eloN};
 };
 nodes.push(summarize('opening-root',rootLabel,'',cells));
 for(const cell of cells){const group=classes.get(cell.structure_class)||[];group.push(cell);classes.set(cell.structure_class,group);}
 const labels={PI:'PI',ac1:'Academy 1',ac2:'Academy 2',lab:'Lab',ts:'TS',m:'Mines'};
 for(const [category,group] of [...classes].sort(([a],[b])=>a.localeCompare(b))){
  const parent='opening-class/'+category;
  nodes.push(summarize(parent,labels[category]||category,'opening-root',group));
  for(const cell of group)nodes.push({id:'opening-leaf/'+cell.label,label:cell.label,parent,...cell});
 }
 return nodes;
}
const scoringModes={};
function scoringView(kind){
 const control=el('scoring-view-control'), select=el('scoring-view');
 const options=kind==='point-sources'?[['relative','Score share by rank (%)'],['absolute','Absolute VP (pooled)']]:kind==='round-scoring'?[['relative','Faction baseline comparison'],['absolute','Raw observed VP / wins']]:[];
 control.hidden=!options.length;
 if(select.dataset.kind!==kind){select.replaceChildren(...options.map(([value,label])=>new Option(label,value)));select.dataset.kind=kind;select.value=scoringModes[kind]||'relative';}
 return select.value==='absolute'?'absolute':'relative';
}
el('scoring-view').addEventListener('change',()=>{scoringModes[el('plot').value]=el('scoring-view').value;draw();});
function draw(){if(!result)return;const kind=el('plot').value,p=result.plots[kind];if(!p)return;const view=scoringView(kind),relative=view==='relative',frequency=kind==='advanced-tech-frequency',byPosition=el('frequency-view').value==='position';
el('frequency-view-label').hidden=!frequency;
const cells=relative&&kind==='point-sources'?(p.rank_cells||[]):relative&&kind==='round-scoring'?(p.comparison_cells||[]):frequency&&!byPosition?(p.tile_cells??p.cells):p.cells;
el('note').textContent=p.note+` ${p.unavailable_records} records unavailable for this metric.`;
if(kind==='point-sources'&&relative)el('note').textContent=p.share_note+` ${p.invalid_share_denominators} observations excluded for nonpositive or unknown score.`;
if(kind==='round-scoring')el('note').textContent=relative?p.round_note:'Raw selected-cohort averages. When every player in each game is included, pooled win rates are fixed by player count. Elo and other player filters can omit seats; these rates do not estimate setup advantage. '+p.note;
const columns=kind==='point-sources'?['label',...(relative?['player_count','rank']:[]),'samples','median','q1','q3']:kind==='basic-tech-frequency'?['label','samples','available','setup_samples','unknown_ownership','frequency','mean_score','mean_rank']:kind.startsWith('basic-tech-')?['label','samples','games','mean_score','mean_rank']:kind.includes('tech-')?['label','samples','available','frequency','mean_score','mean_rank']:(kind==='round-scoring'||kind==='final-scoring')?['label','games','samples','score_samples','mean_score',...(kind==='round-scoring'&&relative?[]:['mean_final_score']),'win_share',...(kind==='final-scoring'?['score_baseline','score_baseline_samples','score_difference','win_baseline','win_baseline_samples','win_difference']:kind==='round-scoring'&&relative?['win_baseline','win_baseline_samples','win_difference']:[])]:['label','samples','mean_score','mean_rank','win_share'];table(el('metrics'),cells,columns,{kind,labels:{mean_score:p.value_label,...(kind==='point-sources'&&relative?{median:'Median score share (%)',q1:'Lower quartile (%)',q3:'Upper quartile (%)',rank:'Competition rank',player_count:'Players'}:{})}});
if(!cells.length){if(window.Plotly)Plotly.purge(el('chart'));el('chart').textContent=(kind==='round-scoring'&&relative&&p.round_selection_required==='faction')?'Choose a faction above to compare round-scoring win differences. Raw observed averages remain available in Scoring view.':p.selection_required==='faction'?'Choose a faction above to compare final-scoring tile pairs. Pooling all players produces fixed prize-pool averages.':'No observations available for this selection.';return;}
const viewportWidth=Math.max(320,el('chart-frame').clientWidth||window.innerWidth-32),viewportHeight=document.body?.classList.contains('chart-focus')?Math.max(320,el('chart-frame').clientHeight):Math.max(480,window.innerHeight-125);
let traces=[],layout={margin:{b:180,t:40},title:names[kind],yaxis:{title:p.value_label,automargin:true},xaxis:{automargin:true},showlegend:true};
if(kind.startsWith('basic-tech-')){({traces,layout}=GaiaBasicTech.build(kind,cells,result,viewportWidth,viewportHeight));}
else if(kind==='point-sources'){
 if(relative){
  const groups=[...new Set(cells.map(c=>`${c.player_count}p · rank ${c.rank}`))];
  traces=groups.map(group=>{const part=cells.filter(c=>`${c.player_count}p · rank ${c.rank}`===group&&c.samples);return {type:'box',name:group,x:part.map(c=>c.label),q1:part.map(c=>c.q1),median:part.map(c=>c.median),q3:part.map(c=>c.q3),lowerfence:part.map(c=>c.lower),upperfence:part.map(c=>c.upper),hovertext:part.map(c=>`${GaiaTiles.metric(kind,c.label)}<br>n=${c.samples}; signed % of final net score`),hovertemplate:'%{hovertext}<br>%{y}<extra>%{fullData.name}</extra>'};});
  layout.boxmode='group';layout.yaxis.title='Signed share of final net score (%)';
 }else{traces=cells.map(c=>({type:'box',name:GaiaTiles.metric(kind,c.label),x:[c.label],q1:[c.q1],median:[c.median],q3:[c.q3],lowerfence:[c.lower],upperfence:[c.upper],hovertext:GaiaTiles.metric(kind,c.label)+'<br>n='+c.samples,hovertemplate:'%{hovertext}<br>%{y}<extra></extra>'}));layout.yaxis.title='VP contribution (signed)';}
 // A display label is never a category key: different sources can share shorthand.
 const sources=[...new Set(cells.map(c=>c.label))];
 layout.xaxis={...layout.xaxis,tickmode:'array',tickvals:sources,ticktext:sources.map(source=>GaiaTiles.metric(kind,source))};
 el('note').textContent+=' Boxes: quartiles, with min/max whiskers.';
}
else if(kind==='final-scoring'){
 const pairs=[...new Set(cells.map(c=>c.x))],factions=[...new Set(cells.map(c=>c.y))],lookup=new Map(cells.map(c=>[JSON.stringify([c.x,c.y]),c]));
 const pairText=x=>{const c=cells.find(c=>c.x===x);return c.player_count+' players: '+c.tiles.map(t=>GaiaTiles.label('final',t)).join(' + ');};
 const pairTick=x=>{const c=cells.find(c=>c.x===x);return c.player_count+'p · '+c.tiles.map(t=>GaiaTiles.label('final',t).replace(/^Most /,'').replace(/ \[.*?\]$/,'').replace(' (including Ivits space stations)',' + Ivits stations')).join('<br>+ ');};
 traces=['score_difference','win_difference'].map((metric,index)=>({type:'heatmap',x:factions,y:pairs,
  z:pairs.map(x=>factions.map(y=>{const c=lookup.get(JSON.stringify([x,y]));return c&&c[metric]!=null?c[metric]*(index?100:1):null;})),
  text:pairs.map(x=>factions.map(y=>{const c=lookup.get(JSON.stringify([x,y]));return c?`${pairText(x)}<br>${y}<br>Games=${c.games}; player observations=${c.samples}; complete tile VP observations=${c.score_samples}<br>Mean tile VP=${c.mean_score==null?'unavailable':c.mean_score.toFixed(2)}; all-faction pair baseline=${c.score_baseline==null?'unavailable':c.score_baseline.toFixed(2)} (VP n=${c.score_baseline_samples})<br>Shared wins=${(c.win_share*100).toFixed(2)}%; faction baseline across pairs=${(c.win_baseline*100).toFixed(2)}% (win n=${c.win_baseline_samples})`:'Unavailable';})),
  hovertemplate:'%{text}<br>'+(index?'Win difference (percentage points)':'Tile VP difference')+'=%{z:.2f}<extra></extra>',
  texttemplate:'%{z:.2f}',colorscale:'RdBu',zmid:0,hoverongaps:false,xaxis:index?'x2':'x',yaxis:index?'y2':'y',colorbar:{x:index?1.02:.4,thickness:12}}));
 layout.margin={t:100,b:60,l:230};layout.height=Math.max(420,pairs.length*65+160);layout.title={text:names[kind],y:.98};
 layout.xaxis={domain:[0,.35],automargin:true};layout.xaxis2={domain:[.65,1],anchor:'y2',automargin:true};
 layout.yaxis={domain:[0,1],tickmode:'array',tickvals:pairs,ticktext:pairs.map(pairTick),automargin:true,autorange:'reversed'};
 layout.yaxis2={...layout.yaxis,anchor:'x2',showticklabels:false};
 layout.annotations=[{text:'Tile VP − all-faction pair mean',x:.175,y:1.08,xanchor:'center',xref:'paper',yref:'paper',showarrow:false},{text:'Win share − faction baseline (pp)',x:.825,y:1.08,xanchor:'center',xref:'paper',yref:'paper',showarrow:false}];
}
else if(kind==='round-scoring'){const xs=[...new Set(cells.map(c=>c.x))],ys=[...new Set(cells.map(c=>c.y))],lookup=new Map(cells.map(c=>[JSON.stringify([c.x,c.y]),c]));traces=['mean_score',relative?'win_difference':'win_share'].map((metric,index)=>({type:'heatmap',x:xs,y:ys,z:ys.map(y=>xs.map(x=>{const c=lookup.get(JSON.stringify([x,y]));return c&&c[metric]!=null?c[metric]*(index?100:1):null;})),text:ys.map(y=>xs.map(x=>{const c=lookup.get(JSON.stringify([x,y]));return c?`${GaiaTiles.metric(kind,c.label)}<br>n=${index?c.samples:c.score_samples}`+(relative?`<br>Observed wins=${(c.win_share*100).toFixed(2)}%; faction baseline=${(c.win_baseline*100).toFixed(2)}% (n=${c.win_baseline_samples}); ${c.player_count} players`:''):'Unavailable';})),hovertemplate:''+(index?(relative?'Win difference (percentage points)':'Shared wins (%)'):p.value_label)+' %{z}<br>%{text}<extra></extra>',colorscale:index&&relative?'RdBu':'Blues',zmid:index&&relative?0:undefined,hoverongaps:false,xaxis:index?'x2':'x',yaxis:index?'y2':'y',colorbar:{x:index?1.02:.4,thickness:12}}));layout.margin.t=100;layout.title={text:names[kind],y:.98};layout.margin.l=120;layout.xaxis.domain=[0,.38];layout.xaxis2={domain:[.64,1],anchor:'y2',automargin:true};layout.yaxis.domain=[0,1];layout.yaxis2={domain:[0,1],anchor:'x2',automargin:true};layout.annotations=[{text:p.value_label,x:.18,y:1.06,xref:'paper',yref:'paper',showarrow:false},{text:relative?'Win share − faction baseline (pp)':'Shared wins (%)',x:.82,y:1.06,xref:'paper',yref:'paper',showarrow:false}];const category=kind==='round-scoring'?'round':'final';const axisLabels=values=>values.map(v=>category==='round'&&/^Round [1-6]( · [234]p)?$/.test(v)?v:(relative?GaiaTiles.label(category,v).replace(/ \[[^\]]+\]$/, ''):GaiaTiles.label(category,v)));for(const key of ['xaxis','xaxis2'])Object.assign(layout[key],{tickmode:'array',tickvals:xs,ticktext:axisLabels(xs)});for(const key of ['yaxis','yaxis2'])Object.assign(layout[key],{tickmode:'array',tickvals:ys,ticktext:axisLabels(ys)});layout.yaxis.title='Scoring tile';}

else if(kind.endsWith('frequency')){
 const percent=value=>value==null?'Unavailable':(100*value).toFixed(1)+'%';
 const baseline=result.filters.faction?'Faction overall':'Selected cohort overall';
 traces=[1,2,3,4].map(rank=>({type:'bar',name:'Rank '+rank,
  // Raw category keys stay distinct even when shortened display labels coincide.
  x:cells.map(c=>c.label),y:cells.map(c=>c.available?(c.rank_counts[rank]||0)/c.available:null),
  hovertext:cells.map(c=>`${GaiaTiles.metric(kind,c.label)}<br>Rank ${rank}<br>P(rank | taken): ${percent(c.samples?(c.rank_counts[rank]||0)/c.samples:null)}<br>P(taken and rank | available): ${percent(c.available?(c.rank_counts[rank]||0)/c.available:null)}<br>${baseline} P(rank): ${percent(result.samples?(result.rank_counts[rank]||0)/result.samples:null)}<br>Taken=${c.samples}; available=${c.available}; rank among taken=${c.rank_counts[rank]||0}; overall n=${result.samples}`),
  hovertemplate:'%{hovertext}<extra></extra>'}));
 const unplaced=cells.reduce((sum,c)=>sum+(c.unavailable_taken_n||0),0);
 if(unplaced)el('note').textContent+=` ${unplaced} acquired-tile observations have no matching setup evidence and are excluded from rates.`;
 layout.barmode='stack';layout.yaxis={...layout.yaxis,title:'Acquisition rate when available',tickformat:'.0%'};
 layout.xaxis={...layout.xaxis,categoryorder:'total ascending',tickmode:'array',tickvals:cells.map(c=>c.label),ticktext:cells.map(c=>GaiaTiles.metric(kind,c.label))};
 el('note').textContent+=' '+(byPosition?'Position breakdown: each bar conditions on the tile being in that position.':'One bar per tile, deduplicated across positions within each player-game.')+' Overall rank rates use all selected player-game observations; choose a player count for a consistent rank comparison. Unknown acquisitions or setup availability are not assumed.';
}
else if(kind==='round-one-structures'){
 const rootLabel=result.filters.faction?'Round 1: '+result.filters.faction:'Round 1 structures';
 const nodes=openingTree(cells,rootLabel),scoreStyle=treemapScoreStyle(nodes.map(c=>c.mean_score));
 el('note').textContent+=' '+scoreStyle.note+' Nested as overall → structure class → exact counts (mines, TS, lab, PI, academy 1, academy 2). Click a branch to inspect it. Parent scores are sample-weighted.';
 traces=[{type:'treemap',ids:nodes.map(c=>c.id),labels:nodes.map(c=>c.label),parents:nodes.map(c=>c.parent),
  values:nodes.map(c=>c.samples),branchvalues:'total',marker:scoreStyle.marker,
  hovertext:nodes.map(c=>`Player observations=${c.samples}; mean net VP=${c.mean_score==null?'Unavailable':c.mean_score.toFixed(2)}<br>Mean pregame Elo=${c.mean_elo==null?'Unavailable':c.mean_elo.toFixed(2)} (rated n=${c.mean_elo_n})`),
  hovertemplate:'%{label}<br>%{hovertext}<extra></extra>'}];
 layout.margin={t:50,l:25,r:25,b:25};
}

else {traces=[{type:'scatter',mode:'markers',name:'Mean net VP',y:cells.map(c=>c.label),customdata:cells.map(c=>GaiaTiles.metric(kind,c.label)),x:cells.map(c=>c.mean_score),hovertext:cells.map(c=>`n=${c.samples}; mean rank=${c.mean_rank??'unavailable'}`),hovertemplate:'%{customdata}<br>%{x} VP<br>%{hovertext}<extra></extra>'}];layout.xaxis.title=p.value_label;layout.yaxis={title:'Tech / Location',tickmode:'array',tickvals:cells.map(c=>c.label),ticktext:cells.map(c=>GaiaTiles.metric(kind,c.label)),automargin:true};}
layout.height=Math.max(layout.height||0,viewportHeight);layout.width=layout.width||viewportWidth;layout.showlegend=traces.length>1;el('chart').style.height=layout.height+'px';el('chart').style.width=layout.width+'px';
if(window.Plotly){
 // react preserves Plotly's DOM and listeners instead of tearing down every view.
 if(!el('chart').data)el('chart').replaceChildren();
 const rendered=result,current=generation;
 Plotly.react(el('chart'),traces,layout,{responsive:true,displaylogo:false}).catch(()=>{if(result!==rendered||current!==generation)return;Plotly.purge(el('chart'));el('chart').textContent='Chart unavailable; exact observations are available in the table.';});
}else el('chart').textContent=plotlyFailed?'Plot library unavailable; exact observations are available in the table.':'Loading chart library… Exact observations are already available in the table.';
}
function renderResult(data,q){
 result=data;
 el('status').textContent=`${data.games} games · ${data.samples} player-game observations · ${data.missing_elo} missing pregame Elo`;
 el('scope').hidden=el('mode').value==='lost-fleet';el('scope').textContent=el('mode').value==='base'?data.scope+'. Auction metadata is unavailable in these CSVs. All dynamic views use net scores, without historical score/quantile cutoffs.':'';
 el('csv').href='/cohort/api/export?'+q;
 // Chart changes do not require rebuilding identical comparison tables.
 const signature=JSON.stringify([data.comparisons,data.setup_comparisons]);
 if(signature!==comparisonSignature){
 table(el('comparison'),data.comparisons,['faction','samples','games','mean_score','mean_rank','win_share']);for(const [kind,target,keys] of [['rounds','round-comparison',[1,2,3,4,5,6].map(i=>'round'+i)],['finals','final-comparison',['final1','final2']],['technologies','tech-comparison',['adv-terra','adv-nav','adv-int','adv-gaia','adv-eco','adv-sci','adv-ext']]]){table(el(target),data.setup_comparisons[kind],['faction','samples',...keys]);}
 comparisonSignature=signature;
 }
 draw();
}
async function update({refresh=false}={}){
 // A failed/interrupted catalog leaves no valid form for the selected mode.
 if(loadedMode!==el('mode').value)return loadMode();
 if(!validateElo()){rejectInvalidElo();form.elements.min_elo.reportValidity();return;}
 save();
 const q=query(),key=cacheKey(q),cohort=new URLSearchParams(q);cohort.delete('plot');
 // Repeated clicks while the same request is pending do not queue more work.
 if(pendingKey===key)return;
 cancelRequest();const current=++generation;
 const nextCohort=cacheKey(cohort);
 if(refresh||cachedCohort!==nextCohort){responses.clear();cachedCohort=nextCohort;}
 const cached=cachedResponse(q);
 if(cached){el('chart').setAttribute('aria-busy','false');renderResult(cached,q);return;}
 requestController=new AbortController();const signal=requestController.signal;pendingKey=key;
 el('status').textContent=result?'Updating… Previous results remain visible until the selection is ready.':'Loading…';
 el('chart').setAttribute('aria-busy','true');el('csv').removeAttribute('href');
 try{
  const response=await fetch('/cohort/api/stats?'+q,{signal}),data=await response.json();
  if(!response.ok)throw Error(data.error||'Request failed');
  if(current!==generation)return;
  responses.set(key,{time:Date.now(),data});
  while(responses.size>8)responses.delete(responses.keys().next().value);
  renderResult(data,q);
 }catch(error){
  if(current!==generation||error.name==='AbortError')return;
  result=null;comparisonSignature=null;el('status').textContent=error.message;
  for(const id of ['comparison','round-comparison','final-comparison','tech-comparison','metrics'])el(id).replaceChildren();
  if(window.Plotly)Plotly.purge(el('chart'));el('chart').textContent='Unavailable';el('csv').removeAttribute('href');
 }finally{
  if(current===generation){requestController=null;pendingKey=null;el('chart').setAttribute('aria-busy','false');}
 }
}
form.onsubmit=e=>{e.preventDefault();update({refresh:true});};el('plot').onchange=()=>update();form.elements.faction.onchange=()=>update();form.elements.player_count.onchange=syncVariantControl;form.elements.min_elo.oninput=onEloInput;form.elements.min_elo.oninvalid=onEloInput;
el('frequency-view').onchange=()=>{save();draw();};
// The form still belongs to loadedMode when the selector changes. Never save
// half-loaded or disabled fields under a newly selected mode.
el('mode').onchange=()=>{save();try{sessionStorage.setItem('gaia-cohort-mode',el('mode').value);}catch{}loadMode();};
async function loadMode(){
 cancelRequest();responses.clear();cachedCohort=null;comparisonSignature=null;loadedMode=null;
 form.querySelector('fieldset').disabled=true;form.elements.faction.disabled=true;el('plot').disabled=true;el('chart').setAttribute('aria-busy','true');
 requestController=new AbortController();const signal=requestController.signal;
 const mode=el('mode').value,current=++generation;history.replaceState(null,'','?ruleset='+mode);result=null;el('status').textContent='Loading mode…';el('csv').removeAttribute('href');
 for(const id of ['comparison','round-comparison','final-comparison','tech-comparison','metrics'])el(id).replaceChildren();
 if(window.Plotly)Plotly.purge(el('chart'));el('chart').textContent='Loading…';
 try{
  const response=await fetch('/cohort/api/catalog?ruleset='+mode,{signal});const catalog=await response.json();if(!response.ok)throw Error(catalog.error||'Catalog unavailable');if(current!==generation)return;
  form.reset();el('rounds').replaceChildren();el('techs').replaceChildren();
  for(const key of ['faction','layout','auction','faction_variant','final_scoring','final_scoring2']){const select=form.elements[key];select.replaceChildren(new Option('All / any',''));for(const value of [...new Set((catalog[key.startsWith('final_scoring')?'final_scorings':key]||[]).filter(value=>typeof value==='string'&&value.trim()))].filter(value=>key!=='faction_variant'||value!=='more-balanced'))select.add(new Option(key.startsWith('final_scoring')?GaiaTiles.label('final',value):key==='faction'?GaiaTiles.faction(value):value,value));}
  for(let i=1;i<=6;i++){const label=document.createElement('label');label.textContent='Round '+i;const select=document.createElement('select');select.name='round'+i;select.add(new Option('Any',''));for(const value of catalog.round_scorings)select.add(new Option(GaiaTiles.label('round',value),value));label.append(select);el('rounds').append(label);}
  for(const slot of ['adv-terra','adv-nav','adv-int','adv-gaia','adv-eco','adv-sci',...(mode==='lost-fleet'?['adv-ext']:[])]){const label=document.createElement('label');label.textContent=GaiaTiles.position(slot);const select=document.createElement('select');select.name=slot;select.add(new Option('Any',''));for(const tile of catalog.advanced_technologies)select.add(new Option(GaiaTiles.label('advanced',tile),tile));label.append(select);el('techs').append(label);}
  for(const key of ['auction']){form.elements[key].disabled=mode==='base';form.elements[key].parentElement.hidden=mode==='base';}
  form.elements.faction.disabled=false;form.elements.lf_2p_4qic_mode.disabled=false;form.elements.layout.disabled=false;const saved=memories[mode]||{};for(const [key,value] of Object.entries(saved)){const field=form.elements[key];if(field&&!field.disabled){if(field.tagName!=='SELECT'||[...field.options].some(o=>o.value===value))field.value=value;}}
  el('plot').value=names[saved.plot]?saved.plot:'advanced-tech-frequency';
  el('frequency-view').value=saved.frequency_view==='position'?'position':'tile';
  syncVariantControl();syncLayoutControl();loadedMode=mode;form.querySelector('fieldset').disabled=false;form.elements.faction.disabled=false;el('plot').disabled=false;await update();
 }catch(error){if(current===generation&&error.name!=='AbortError'){el('status').textContent=error.message;el('chart').textContent='Unavailable';el('chart').setAttribute('aria-busy','false');form.querySelector('fieldset').disabled=false;form.elements.faction.disabled=false;el('plot').disabled=false;}}
}
const focusButton=el('chart-focus');
function focusChart(active){for(const child of document.querySelector('main').children){if(child!==el('chart-panel'))child.inert=active;}document.body.classList.toggle('chart-focus',active);focusButton.textContent=active?'Exit chart view':'Expand chart';focusButton.setAttribute('aria-pressed',String(active));draw();focusButton.focus();}
focusButton.onclick=()=>focusChart(!document.body.classList.contains('chart-focus'));
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('chart-focus'))focusChart(false);});
let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(draw,100);});
// Begin metadata and statistics loading without waiting for the large plotting bundle.
const plotlyScript=document.createElement('script');
plotlyScript.src='/classic/assets/plotly.min.js';plotlyScript.async=true;
plotlyScript.onload=()=>draw();
plotlyScript.onerror=()=>{plotlyFailed=true;draw();};
document.head.append(plotlyScript);
loadMode();
