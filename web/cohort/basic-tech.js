/* Explicit coordinates are data keys; shorthand is presentation only. */
'use strict';
window.GaiaBasicTech = (() => {
 const locations=['terra','nav','int','gaia','eco','sci','rebellion','tfmars','eclipse','twilight','free'];
 const colors={terra:'#a52a2a',nav:'#708090',int:'#26a65b',gaia:'#bf55ec',eco:'#d4ad00',sci:'#038aff',rebellion:'#a97c50',tfmars:'#bfc5cf',eclipse:'#d1c792',twilight:'#9872a2',free:'#8c929a',taken:'#15803d',not_taken:'#b91c1c'};
 const headingColors={terra:'#7f1d1d',nav:'#475569',int:'#166534',gaia:'#7e22ce',eco:'#715500',sci:'#0369a1',rebellion:'#79502f',tfmars:'#475569',eclipse:'#6b5900',twilight:'#6b4580',free:'#4b5563'};
 const name=location=>GaiaTiles.position(location);
 function build(kind,cells,result,width,height){
  const layout={width,height,margin:{l:120,r:40,t:65,b:110},xaxis:{automargin:true},yaxis:{automargin:true},legend:{orientation:'h',y:-.14},hovermode:'closest',shapes:[],annotations:[],title:kind==='basic-tech-frequency'?'Basic tech acquisition by setup location':kind==='basic-tech-score'?'Basic Tech Impact on Average Score by Track Taken':'Basic Tech Average Score by Setup Location'};
  if(width<600)layout.title={text:kind==='basic-tech-frequency'?'Basic tech · Acquisition by setup':kind==='basic-tech-score'?'Basic tech · Score when taken':'Basic tech · Score by setup',font:{size:15}};
  let traces=[];
  if(kind==='basic-tech-frequency'){
   const order=result.ruleset==='base'?locations.filter(x=>!['rebellion','tfmars','eclipse','twilight'].includes(x)):locations;
   const points=[];let cursor=0;const ticks=[],labels=[];
   for(const location of order){
    const group=cells.filter(c=>c.location_id===location),start=cursor;
    for(const c of group){points.push({...c,coordinate:cursor});ticks.push(cursor++);labels.push(GaiaTiles.label('basic',c.tile_id));}
    if(!group.length){ticks.push(cursor);labels.push('N/A');cursor+=2;}
    const end=cursor-1;
    layout.shapes.push({type:'rect',xref:'x',yref:'paper',x0:start-.45,x1:end+.45,y0:0,y1:1,fillcolor:colors[location],opacity:.12,line:{width:0},layer:'below'});
    layout.annotations.push({xref:'x',yref:'paper',x:(start+end)/2,y:1.04,text:name(location).replace('Artificial Intelligence','Artificial<br>Intelligence'),showarrow:false,font:{color:headingColors[location],size:13}});
    if(!group.length)layout.annotations.push({xref:'x',yref:'paper',x:(start+end)/2,y:.5,text:location==='twilight'?'No tech slot':location==='rebellion'&&String(result.filters.player_count)==='2'?'Not in 2p':'No observations',showarrow:false,textangle:-90,font:{size:12}});
    cursor+=1.4;
   }
   traces=[1,2,3,4].map(rank=>({type:'bar',name:'Rank '+rank,x:points.map(c=>c.coordinate),y:points.map(c=>c.available?100*(c.rank_counts[rank]||0)/c.available:null),
    customdata:points.map(c=>[GaiaTiles.label('basic',c.tile_id),name(c.location_id),c.samples,c.available,c.samples?100*(c.rank_counts[rank]||0)/c.samples:null,result.samples?100*(result.rank_counts[rank]||0)/result.samples:null,c.unknown_ownership]),
    hovertemplate:'%{customdata[0]} · %{customdata[1]}<br>Rank '+rank+' and taken / available: %{y:.2f}%<br>Rank '+rank+' / taken: %{customdata[4]:.2f}%<br>Cohort rank '+rank+': %{customdata[5]:.2f}%<br>Taken=%{customdata[2]}; known inventory=%{customdata[3]}; unknown=%{customdata[6]}<extra></extra>'}));
   layout.barmode='stack';layout.width=Math.max(width,ticks.length*30);layout.margin={l:65,r:25,t:70,b:145};layout.xaxis={tickmode:'array',tickvals:ticks,ticktext:labels,tickangle:-60,range:[-.7,cursor-.6],fixedrange:false};layout.yaxis={title:'Player-games taken (%)',range:[0,100]};
  }else{
   const tiles=[...new Set(cells.map(c=>c.tile_id))],series=[...locations,...(kind==='basic-tech-score'?['taken','not_taken']:[])];
   traces=series.filter(slot=>cells.some(c=>c.location_id===slot&&c.samples)).map(slot=>{
    const group=tiles.map(tile=>cells.find(c=>c.tile_id===tile&&c.location_id===slot));
    return {type:'scatter',mode:'markers',name:name(slot),x:group.map(c=>c?.mean_score??null),y:tiles,
     marker:{color:colors[slot],size:slot==='taken'||slot==='not_taken'?11:9,symbol:group.map(c=>slot==='taken'?'triangle-up':slot==='not_taken'?'triangle-down':c&&c.samples<10?'circle-open':'circle')},
     customdata:group.map((c,i)=>[GaiaTiles.label('basic',tiles[i]),c?.samples||0,c?.games||0]),
     hovertemplate:'%{customdata[0]} · '+name(slot)+'<br>Mean pre-bid VP=%{x:.2f}<br>Player-games=%{customdata[1]}; games=%{customdata[2]}<extra></extra>'};
   });
   if(width<600){layout.margin.b=225;layout.legend={orientation:'h',xref:'container',yref:'container',x:0,y:0,yanchor:'bottom',entrywidth:120,entrywidthmode:'pixels',font:{size:11}};}
   layout.yaxis={tickmode:'array',tickvals:tiles,ticktext:tiles.map(t=>GaiaTiles.label('basic',t)),autorange:'reversed',automargin:true};layout.xaxis={title:{text:'Mean pre-bid VP',standoff:width<600?0:15,font:{size:width<600?12:14}},automargin:true};
   if(result.mean_score!=null){layout.shapes.push({type:'line',xref:'x',yref:'paper',x0:result.mean_score,x1:result.mean_score,y0:0,y1:1,line:{dash:'dot',width:2,color:'#475569'}});layout.annotations.push({xref:'x',yref:'paper',x:result.mean_score,y:1.02,text:'Cohort mean '+result.mean_score.toFixed(1),showarrow:false});}
  }
  return {traces,layout};
 }
 return {build,locations,colors};
})();
