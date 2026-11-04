/* Presentation only: query values, grouping keys and downloaded records stay unchanged. */
'use strict';
window.GaiaTiles = (() => {
  const registry = __TILE_REGISTRY__;
  const tracks = {terra:'Terra',nav:'Nav',int:'Artificial Intelligence',gaia:'Gaia',eco:'Econ',sci:'Sci',ext:'Extra',free:'Free',free1:'Free 1',free2:'Free 2',free3:'Free 3',rebellion:'Rebellion',tfmars:'TF Mars',eclipse:'Eclipse',twilight:'Twilight',taken:'Taken',not_taken:'Not taken'};
  function label(category, id) {
    const entries = registry[category] || {};
    const entry = entries[id] || Object.values(entries).find(e => e.aliases.includes(id));
    return entry ? entry.short : 'Unknown tile';
  }
  function tile(id){for(const category of ['basic','advanced']){const entries=registry[category];if(entries[id]||Object.values(entries).some(e=>e.aliases.includes(id)))return label(category,id);}return 'Unknown tech';}
  function position(id) {
    const track = id.replace(/^(adv-|tech-)/, '');
    return tracks[track] || 'Unknown location';
  }
  function metric(kind, value) {
    if (kind.includes('tech-')) {
      const [tile, slot] = value.split(' / ');
      return label(kind.startsWith('advanced') ? 'advanced' : 'basic', tile) + (slot ? ' / ' + position(slot) : '');
    }
    if (kind === 'final-scoring' && /^[234]p: /.test(value)) {
      const [pair, faction] = value.split(' / ');
      return pair.slice(0,2) + ': ' + pair.slice(4).split(' + ').map(id=>label('final',id)).join(' + ') + ' / ' + faction;
    }
    if (kind === 'round-scoring' || kind === 'final-scoring') {
      const category = kind === 'round-scoring' ? 'round' : 'final';
      return value.split(' / ').map(id => category === 'round' && /^Round [1-6]$/.test(id) ? id : label(category,id)).join(' / ');
    }
    if (kind === 'point-sources') return source(value);

    return value;
  }
  function source(value) {
    if (registry.action[value]) return label('action',value);
    if (value.startsWith('booster') && value!=='booster') return label('booster',value);
    if (/^(adv-|tech-)/.test(value)) return (/^adv-/.test(value)?'Adv ':'Tech ')+position(value);
    if (/^round[1-6]$/.test(value)) return 'Round '+value.slice(-1);
    if (/^final[12]$/.test(value)) return 'Final '+value.slice(-1);
    return ({terra:'Terra Research',nav:'Nav Research',int:'Artificial Intelligence Research',gaia:'Gaia Research',eco:'Econ Research',sci:'Sci Research',tfmars:'TF Mars',rebellion:'Rebellion',eclipse:'Eclipse',twilight:'Twilight',init:'Starting VP',initial:'Starting VP',bid:'Auction',charge:'Power Charge',research:'Research',tech_score:'Research',resource:'Resources',round:'Round Scoring',final:'Final Scoring',booster:'Booster Pass',tech_basic:'Basic Tech',adv:'Advanced Tech',fed:'Federation',federation:'Federation',qic:'QIC Actions',build:'Building',explore:'Exploration',spend:'Spending',gleens:'Gleens'})[value] || 'Other VP';
  }
  function move(text){
    let result=text.replace(/\b(?:advtech(?:[0-9]+|-[a-z]+)|tech[0-9]+|ship-tech-[a-z]+)\b/g,id=>label(id.startsWith('adv')?'advanced':'basic',id));
    result=result.replace(/\btech (free[123]|terra|nav|int|gaia|eco|sci|tfmars|eclipse|rebellion|twilight)\b/g,(_,slot)=>'Tech '+position(slot));
    return result.replace(/\bup (terra|nav|int|gaia|eco|sci)\b/g,(_,slot)=>'Research '+position(slot));
  }
  function legacy(kind){
    for(const graph of document.querySelectorAll('.js-plotly-plot')){
      if(!graph.data||!window.Plotly)continue;
      const relayout={},traces=graph.data;
      traces.forEach((trace,index)=>{
        const category=kind.startsWith('advanced-tech')?'advanced':kind.startsWith('basic-tech')?'basic':kind==='round-scoring'?'round':kind==='final-scoring'?'final':null;
        const axis=kind.endsWith('frequency')?'x':'y';
        const translate=value=>typeof value==='string'?(category?label(category,value):source(value)):value;
        const update={};
        if(category&&trace.type==='heatmap'){
          for(const a of ['x','y']){const key=(trace[a+'axis']||a).replace(a,a+'axis');relayout[key+'.tickmode']='array';relayout[key+'.tickvals']=trace[a];relayout[key+'.ticktext']=(trace[a]||[]).map(v=>kind==='round-scoring'&&a==='x'?v:translate(v));}
          update.hovertext=[(trace.y||[]).map(y=>(trace.x||[]).map(x=>(kind==='round-scoring'?'Round '+x:translate(x))+' / '+translate(y)))];
          update.hovertemplate='%{hovertext}<br>%{z}<br>score observations n=%{customdata}<extra></extra>';
        }else if(category){
          const key=(trace[axis+'axis']||axis).replace(axis,axis+'axis');relayout[key+'.tickmode']='array';relayout[key+'.tickvals']=trace[axis];relayout[key+'.ticktext']=(trace[axis]||[]).map(translate);
          update.hovertext=[(trace[axis]||[]).map(translate)];update.hovertemplate=(trace.hovertemplate||'%{'+axis+'}').replaceAll('%{'+axis+'}','%{hovertext}');
          if(trace.name)update.name=/^(?:net-score )?rank[ _]/i.test(trace.name)?trace.name.replace('_',' '):position(trace.name.replace(/^tech_/,'').replace(/^adv-/,'').replace(/^tech_adv-/,''));
        }else if(kind==='point-sources'){const values=[...new Set(trace.x||[])];relayout.xaxis={tickmode:'array',tickvals:values,ticktext:values.map(source)};update.hovertext=[(trace.x||[]).map(source)];update.hovertemplate='%{hovertext}<br>%{y}<extra></extra>'; if(trace.name&&!/^rank /i.test(trace.name))update.name=source(trace.name);}
        if(Object.keys(update).length)Plotly.restyle(graph,update,index);
      });
      Plotly.relayout(graph,relayout);
    }
  }
  function glossary(target) {
    const details=document.createElement('details'),summary=document.createElement('summary');
    summary.textContent='Shorthand key';details.append(summary);
    const note=document.createElement('p');note.textContent='o = ore; k = knowledge; c = credits; q = QIC; pw = power charge; pwt = new power tokens; tf = terraforming; PI = planetary institute; AC = academy; TS = trading station. Now = on acquisition; Pass = when passing. Actions are once per round unless stated otherwise.';details.append(note);
    for(const [category,entries] of Object.entries(registry)){
      const heading=document.createElement('h3');heading.textContent=category;details.append(heading);
      const list=document.createElement('ul');for(const entry of Object.values(entries)){const item=document.createElement('li');item.textContent=entry.short+' — '+entry.description;list.append(item);}details.append(list);
    }
    target.append(details);
  }
  return {label,tile,position,metric,source,move,legacy,glossary};
})();
