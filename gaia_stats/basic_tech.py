"""Basic-tech observations: setup locations, acquisitions, and non-acquisitions.

Identifiers remain data keys. Remaining pile size is never an opportunity count.
"""
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
import json

from .technology_locations import FREE_SLOTS, location

KINDS = ('basic-tech-frequency', 'basic-tech-score', 'basic-tech-setup-score')
TRACKS = ('terra','nav','int','gaia','eco','sci')
SHIPS = ('rebellion','tfmars','eclipse','twilight')
FREE = FREE_SLOTS


@lru_cache(maxsize=1)
def aliases():
    registry=json.loads((Path(__file__).resolve().parents[1]/'web/cohort/tile-labels.json').read_text())['basic']
    return {alias:key for key,item in registry.items() for alias in [key,*item['aliases']]}


def canonical(tile):
    return aliases().get(tile,tile)


def prepare(rows):
    """Recover exhausted ship piles from evidenced owned positions before filters.

BGS deletes an exhausted spaceshipTechs entry; the tile/position in each player's
owned tiles survives. Conflicting evidence stays unavailable. Never mutate data.
    """
    rows=[{**row, 'technologies':{slot:canonical(tile) for slot,tile in row['technologies'].items()},
           'owned_technologies':[{**item,'tile':canonical(item['tile'])} for item in row['owned_technologies']] if row.get('owned_technologies') is not None else None}
          for row in rows]
    candidates = defaultdict(lambda: defaultdict(set))
    for row in rows:
        if row['ruleset'] != 'lost-fleet':
            continue
        slots = candidates[row['game_id']]
        for slot,item in row.get('ship_technologies',{}).items():
            if slot in SHIPS and item.get('tile'):
                slots[slot].add(canonical(item['tile']))
        for item in row.get('owned_technologies') or []:
            if item['slot'] in SHIPS:
                slots[item['slot']].add(item['tile'])
    result=[]
    for row in rows:
        if row['ruleset'] != 'lost-fleet':
            result.append(row);continue
        mapping={slot:{'tile':next(iter(tiles))} for slot,tiles in candidates[row['game_id']].items() if len(tiles)==1}
        conflicts=any(len(tiles)>1 for tiles in candidates[row['game_id']].values())
        result.append({**row,'ship_technologies':mapping,'basic_setup_conflict':conflicts})
    return result


def statistics(rows, kind):
    from .cohort import summary
    groups=defaultdict(list)
    available=defaultdict(list)
    setup_counts=defaultdict(int)
    unknown=0
    for row in rows:
        setup={slot:canonical(tile) for slot,tile in row['technologies'].items() if slot in TRACKS+FREE}
        setup.update({slot:canonical(item['tile']) for slot,item in row.get('ship_technologies',{}).items() if slot in SHIPS})
        owned=row.get('owned_technologies')
        taken={(canonical(item['tile']),item['slot']) for item in owned} if owned is not None else None
        if (taken is None and kind!='basic-tech-setup-score') or row.get('basic_setup_conflict'):
            unknown+=1
        # A row counts once for each distinct tile/location opportunity.
        opportunities=defaultdict(set)
        for slot,tile in setup.items():
            opportunities[(tile,location(slot))].add(slot)
        for (tile,slot),original_slots in opportunities.items():
            key=(tile,slot);setup_counts[key]+=1
            if kind=='basic-tech-setup-score':
                groups[key].append(row)
            elif taken is not None:
                available[key].append(row)
                if any((tile,source) in taken for source in original_slots):
                    groups[key].append(row)
        if kind=='basic-tech-score' and taken is not None:
            for tile in set(setup.values()):
                acquired=any(t==tile for t,_ in taken)
                groups[(tile,'taken' if acquired else 'not_taken')].append(row)
    cells=[]
    for tile,slot in sorted(set(setup_counts)|set(groups)):
        key=(tile,slot);group=groups[key]
        cell={'label':tile+' / '+slot,'tile_id':tile,'location_id':slot,
              'cohort':'setup' if kind=='basic-tech-setup-score' else 'not_acquired' if slot=='not_taken' else 'acquired',
              **summary(group)}
        if kind=='basic-tech-frequency':
            cell.update(available=len(available[key]),setup_samples=setup_counts[key],
                        unknown_ownership=setup_counts[key]-len(available[key]),
                        frequency=len(group)/len(available[key]) if available[key] else None)
        cells.append(cell)
    if kind=='basic-tech-frequency':
        note='Acquisition frequency by setup bucket; denominator: eligible player-games with this tile at this location and known ownership. Free positions combine here. Exhausted ship piles are recovered from owned tiles; remaining copies are not denominators.'
    elif kind=='basic-tech-score':
        note='Mean pre-bid VP among players who acquired the tile from its original setup location—not the research track advanced. Taken / Not taken pool all setup locations, including free positions, with known ownership. Free positions combine; one player-game per tile/location bucket. Observation-weighted, unlike Tim’s position-weighted means. Dotted line: selected-cohort mean. Associations, not causal impacts.'
    else:
        note='Mean pre-bid VP of every eligible player-game with the tile at this setup location, acquired or not. Free positions combine here. Dotted line: selected-cohort mean. Associations, not causal impacts.'
    return {'kind':kind,'cells':cells,'unavailable_records':unknown,'value_label':'Acquisition frequency' if kind.endswith('frequency') else 'Mean pre-bid VP','note':note}
