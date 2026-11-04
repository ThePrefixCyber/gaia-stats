/* Presentation only: query values, grouping keys and downloaded records stay unchanged. */
'use strict';
window.GaiaTiles = (() => {
  const registry = __TILE_REGISTRY__;
  const tracks = {terra:'Terra',nav:'Nav',int:'Artificial Intelligence',gaia:'Gaia',eco:'Econ',sci:'Sci',ext:'Extra',free:'Free',free1:'Free',free2:'Free',free3:'Free',rebellion:'Rebellion',tfmars:'TF Mars',eclipse:'Eclipse',twilight:'Twilight',taken:'Taken',not_taken:'Not taken'};
  function faction(id){return String(id).replaceAll('-', ' ').replace(/\b\w/g,letter=>letter.toUpperCase());}
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
    if (kind === 'round-scoring' && /^[234]p: Round [1-6] \/ /.test(value)) {
      const [round, tile] = value.split(' / ');
      return round.replace(/^([234])p: /, '$1 players: ') + ' / ' + label('round', tile).replace(/ \[[^\]]+\]$/, '');
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
  // Move text is display-only. Replace whole identifier tokens, never substrings
  // inside game IDs, coordinates or other words. Preserve quantities and order.
  const moveTileLabels = {"tinkering-step1":"1tf Action","tinkering-power4":"4pw Action","tinkering-qic1":"1q Action","tinkering-step3":"3tf Action","tinkering-knowledge3":"3k Action","tinkering-qic2":"2q Action","fed1": "12vp (Gray)", "fed2": "8vp1q", "fed3": "8vp2pwt", "fed4": "7vp2o", "fed5": "7vp6c", "fed6": "6vp2k", "ship-fed-credit": "8vp8c", "ship-fed-knowledge": "4vp4k", "ship-fed-orequic": "4vp2o1q", "ship-fed-power": "7vp + 2pwt Area III", "ship-fed-range": "Unlimited Range Mine", "ship-fed-tech": "Tech Tile", "ship-fed-terraform": "3tf Mine", "ship-fed-vp": "12vp (Green)", "artifact-knowledgeore": "1k1o Income", "artifact-credit": "3c3o", "artifact-knowledgeqic": "3k1q", "artifact-creditlarge": "5c2o", "artifact-power": "2pwt Area III Income", "artifact-asteroid": "7vp + Virtual Asteroid Mine", "artifact-protoplanet": "7vp + Virtual Protoplanet Mine", "artifact-researchlevel": "3vp / Sci Level", "artifact-researchtracks": "3vp / Track at Level 3+", "artifact-federation": "Re-score Fed", "artifact-gaiaproject": "3vp / Gaia Level", "artifact-planettypes": "3vp + 1vp / Planet Type", "artifact-deepspace": "3vp / Deep Space Sector"};
  function move(text){
    let result=text.replace(/\bspaceshipAction (rebellion|tfmars|eclipse|twilight) (qic|power|credit)\b/g,(_,ship,action)=>position(ship)+' '+({qic:'QIC',power:'Power',credit:'Credit'})[action]+' action');
    result=result.replace(/\b(tech|cover|up) ((?:adv-|tech-)?(?:free[123]|terra|nav|int|gaia|eco|sci|ext)|tfmars|eclipse|rebellion|twilight)\b/g,(_,command,slot)=>({tech:'Tech',cover:'Cover',up:'Research'})[command]+' '+position(slot));
    return result.replace(/\b[A-Za-z][A-Za-z0-9-]*\b/g,token=>{
      if(moveTileLabels[token])return moveTileLabels[token];
      for(const category of ['basic','advanced','booster','action'])if(registry[category][token])return label(category,token);
      if(['rebellion','tfmars','eclipse','twilight'].includes(token))return position(token);
      return ({chooseTinkeringTile:'Choose tinkering tile',spaceshipAction:'Ship action',examineArtifact:'Examine artifact',chooseArtifactToken:'Choose artifact',gaiaFormTransdim:'Gaiaform Transdim',fedtile:'Federation token'})[token]||token;
    });
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
          if(trace.name)update.name=/^(?:pre-bid-score )?rank[ _]/i.test(trace.name)?trace.name.replace('_',' '):position(trace.name.replace(/^tech_/,'').replace(/^adv-/,'').replace(/^tech_adv-/,''));
        }else if(kind==='point-sources'){// Include every trace on this axis, not just the last rank's sources.
          const axis=trace.xaxis||'x',values=[...new Set(traces.filter(t=>(t.xaxis||'x')===axis).flatMap(t=>t.x||[]))];
          relayout[axis.replace('x','xaxis')]={tickmode:'array',tickvals:values,ticktext:values.map(source)};update.hovertext=[(trace.x||[]).map(source)];update.hovertemplate='%{hovertext}<br>%{y}<extra></extra>'; // Finishing-order series are human-readable methodology, not VP-source IDs.
          if(trace.name&&!/^(?:(?:pre-bid-score )?rank[ _][1-4]\b|bid-restored order [1-4] \(ties broken by original player order\)$)/i.test(trace.name))update.name=source(trace.name);}
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
  return {label,tile,position,metric,source,move,legacy,glossary,faction};
})();
