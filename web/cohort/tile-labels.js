/* Presentation only: query values, grouping keys and downloaded records stay unchanged. */
'use strict';
window.GaiaTiles = (() => {
  const registry = __TILE_REGISTRY__;
  const tracks = {terra:'Terraforming',nav:'Navigation',int:'Artificial intelligence',gaia:'Gaia project',eco:'Economy',sci:'Science',ext:'Expansion',free1:'Free position 1',free2:'Free position 2',free3:'Free position 3'};
  function label(category, id) {
    const entries = registry[category] || {};
    const entry = entries[id] || Object.values(entries).find(e => e.aliases.includes(id));
    return entry ? `${entry.description} [${id}]` : `Unmapped ${category} tile [${id}]`;
  }
  function position(id) {
    const track = id.replace(/^(adv-|tech-)/, '');
    return (tracks[track] ? tracks[track] + ' position' : 'Position') + ` [${id}]`;
  }
  function metric(kind, value) {
    if (kind.includes('tech-')) {
      const [tile, slot] = value.split(' / ');
      return label(kind.startsWith('advanced') ? 'advanced' : 'basic', tile) + (slot ? ' / ' + position(slot) : '');
    }
    if (kind === 'round-scoring' || kind === 'final-scoring') {
      const category = kind === 'round-scoring' ? 'round' : 'final';
      return value.split(' / ').map(id => category === 'round' && /^Round [1-6]$/.test(id) ? id : label(category,id)).join(' / ');
    }
    if (kind === 'point-sources') {
      if (registry.action[value]) return label('action',value);
      if (value.startsWith('booster') && value !== 'booster') return label('booster', value);
      // Aggregated position sources combine randomized tiles: never assign one tile's effect.
      if (/^(adv-|tech-)/.test(value)) return 'VP from ' + position(value);
    }
    return value;
  }
  function glossary(target) {
    const details = document.createElement('details'), summary = document.createElement('summary');
    summary.textContent = 'Tile effects and identifier key'; details.append(summary);
    const note=document.createElement('p');note.textContent='Immediate means when acquired; pass means when passing; actions are once per round unless stated otherwise. Position IDs are locations, not fixed tile effects. Space-sector effects follow BGS, which excludes Deep Space for base sector tiles.';details.append(note);
    for (const [category, entries] of Object.entries(registry)) {
      const heading=document.createElement('h3');heading.textContent=category;details.append(heading);
      const list=document.createElement('ul');for(const [id,entry] of Object.entries(entries)){const item=document.createElement('li');item.textContent=label(category,id)+(entry.aliases.length?' · historical: '+entry.aliases.join(', '):'');list.append(item);}details.append(list);
    }
    target.append(details);
  }
  return {label,position,metric,glossary};
})();
