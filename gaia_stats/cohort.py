"""Descriptive statistics over one explicit, consistently filtered ruleset.

No inferred expansion IDs: retain BGS tile, track and VP-source identifiers.
"""
import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, quantiles

from .analysis import normalize, select
from .__main__ import atomic_json
from .scoring import complete_ledger, tile_value

PLOTS = ('advanced-tech-frequency', 'advanced-tech-score', 'basic-tech-frequency',
         'basic-tech-score', 'round-one-structures', 'final-scoring',
         'round-scoring', 'point-sources')


def enrich(game, rows):
    data = game['data']
    buildings = defaultdict(dict)
    unsupported = set()
    seen = set()
    initial_structures = {}
    round_number = 0
    for event in data['advancedLog']:
        if event.get('round') == 1:
            initial_structures = {pos: dict(Counter(placed.values())) for pos, placed in buildings.items()}
        round_number = event.get('round', round_number)
        if round_number > 1 or event.get('phase') == 'endGame':
            break
        pos, move_id = event.get('player'), event.get('move')
        if pos is None or move_id is None or move_id in seen:
            continue
        seen.add(move_id)
        move = data['moveHistory'][move_id]
        if not move.startswith(rows[pos]['faction'] + ' '):
            continue
        # Coordinates identify upgrades; setup PI is retained (not two assumed mines).
        for kind, coordinate in re.findall(r'\bbuild\s+(\w+)\s+([\w_-]+)', move):
            if kind in ('m', 'ts', 'lab', 'PI', 'ac1', 'ac2'):
                buildings[pos][coordinate] = kind
        # Count-changing special actions need dedicated reconstruction, not guessed zeros.
        if any(token in move for token in ('swap-PI', 'downgrade', 'space-station')):
            unsupported.add(pos)
    for pos, row in enumerate(rows):
        state = data['players'][pos]['data']
        techs = state.get('tiles', {}).get('techs')
        row['initial_structures'] = initial_structures.get(pos)
        row['owned_technologies'] = ([{'tile': t['tile'], 'slot': t['pos']}
                                      for t in techs] if isinstance(techs, list) else None)
        row['round_one_structures'] = (dict(Counter(buildings[pos].values()))
                                       if buildings[pos] and pos not in unsupported else None)
        row['round_one_unavailable'] = ('Special building action requires reconstruction'
                                        if pos in unsupported else None)
    return rows


def build(paths, destination):
    rows, accepted, rejected = [], [], []
    seen = {}
    for path in sorted(map(Path, paths)):
        raw = path.read_bytes()
        provenance = {'file': path.name, 'sha256': hashlib.sha256(raw).hexdigest()}
        try:
            game = json.loads(raw)
            identifier=game.get('slug') or game.get('_id')
            canonical=hashlib.sha256(json.dumps(game,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if not identifier:raise ValueError('Missing game identifier')
            if identifier in seen:
                if seen[identifier]!=canonical:raise RuntimeError('Conflicting duplicate export: '+identifier)
                rejected.append({**provenance,'reason':'Duplicate game identifier; identical export skipped'})
                continue
            seen[identifier]=canonical
            candidate = enrich(game, normalize(game))
            if not all(r['score_verified'] for r in candidate):
                raise ValueError('VP ledger does not reconcile')
            if any(r['ruleset'] != 'lost-fleet' for r in candidate):
                raise ValueError('This sample build accepts Lost Fleet only')
            rows.extend(candidate)
            accepted.append(provenance)
        except (KeyError, ValueError, TypeError) as error:
            rejected.append({**provenance, 'reason': str(error)})
    dataset = {'schema_version': 1, 'rows': rows, 'accepted': accepted, 'rejected': rejected,
               'scope': 'Bounded public Lost Fleet sample; not a representative archive'}
    if not rows:raise ValueError('No accepted complete games; existing dataset preserved')
    atomic_json(destination, dataset)
    return dataset


def cohort(dataset, filters):
    # Reuse the same filter implementation as the normalized analysis API.
    if filters.get('final_scoring') and filters.get('final_scoring') == filters.get('final_scoring2'):
        raise ValueError('Choose two distinct final scoring tiles')
    rows = select(dataset['rows'], filters)
    return [row for row in rows
            if (not filters.get('final_scoring2') or filters['final_scoring2'] in row['final_scorings'])
            and all(not filters.get(slot) or row['technologies'].get(slot) == filters[slot]
                    for slot in ('adv-terra', 'adv-nav', 'adv-int', 'adv-gaia', 'adv-eco', 'adv-sci', 'adv-ext'))]


def summary(group):
    return {'samples': len(group), 'games': len({r['game_id'] for r in group}),
            'mean_score': mean(r['score'] for r in group) if group else None,
            'mean_rank': mean(r['rank'] for r in group) if group else None,
            'win_share': mean(r['win_share'] for r in group) if group else None,
            'rank_counts': dict(Counter(r['rank'] for r in group))}


def statistics(rows, kind):
    if kind not in PLOTS:
        raise ValueError('Unknown plot')
    groups = defaultdict(list)
    opportunities = Counter()
    unavailable = 0
    if 'tech-' in kind:
        advanced = kind.startswith('advanced')
        for row in rows:
            owned = row.get('owned_technologies')
            if owned is None:
                unavailable += 1
                continue
            available = dict(row['technologies'])
            available.update({slot: item['tile'] for slot, item in row['ship_technologies'].items()})
            for slot, tile in available.items():
                if slot.startswith('adv-') == advanced:
                    opportunities[(tile, slot)] += 1
            for tech in {(t['tile'], t['slot']) for t in owned}:
                if tech[1].startswith('adv-') == advanced:
                    groups[tech].append(row)
        keys = sorted(set(groups) | set(opportunities))
        cells = [{'label': f'{tile} / {slot}', **summary(groups[(tile, slot)]),
                  'available': opportunities[(tile, slot)],
                  'frequency': len(groups[(tile, slot)]) / opportunities[(tile, slot)]
                  if opportunities[(tile, slot)] else None} for tile, slot in keys]
    elif kind == 'round-one-structures':
        for row in rows:
            structures = row.get('round_one_structures')
            if structures is None:
                unavailable += 1
                continue
            label = ', '.join(f'{key}: {value}' for key, value in sorted(structures.items()))
            groups[label].append(row)
        cells = [{'label': label, **summary(group)} for label, group in sorted(groups.items())]
    elif kind in ('round-scoring', 'final-scoring'):
        for row in rows:
            if kind == 'round-scoring':
                for index, tile in enumerate(row['round_scorings']):
                    groups[(f'Round {index + 1}', tile)].append(row)
            else:
                groups[tuple(sorted(row['final_scorings']))].append(row)
        cells = [{'label': ' / '.join(key), 'x': key[0], 'y': key[1], **summary(group)}
                 for key, group in sorted(groups.items())]
    else:
        sources = sorted({key for row in rows for key in row['vp_sources']})
        # Absence in a complete reconciled ledger is an observed zero.
        cells=[]
        for source in sources:
            # Historical CSV absence is unknown, unlike a complete raw VP ledger.
            values=[r['vp_sources'].get(source,0) for r in rows
                    if complete_ledger(r) or source in r['vp_sources']]
            cell={'label':source,'samples':len(values)}
            if values:
                q1,median,q3=quantiles(values,n=4,method='inclusive') if len(values)>1 else (values[0],)*3
                cell.update(q1=q1,median=median,q3=q3,lower=min(values),upper=max(values))
            if len(values)<=2000:cell['values']=values
            cells.append(cell)
    value_label='Mean final net VP'
    if kind in ('round-scoring','final-scoring'):
        value_label='Mean VP earned from scoring tile(s)'
        for cell in cells:
            group=groups[(cell['x'],cell['y'])]
            keys=[f"round{cell['x'].split()[-1]}"] if kind=='round-scoring' else ['final1','final2']
            values=[sum(tile_value(r,k) for k in keys) for r in group if all(tile_value(r,k) is not None for k in keys)]
            cell['mean_final_score']=cell['mean_score']
            cell['mean_score']=mean(values) if values else None
            cell['score_samples']=len(values)
        required=[f'round{i}' for i in range(1,7)] if kind=='round-scoring' else ['final1','final2']
        unavailable=sum(any(tile_value(r,k) is None for k in required) for r in rows)
    return {'kind': kind, 'cells': cells, 'unavailable_records': unavailable,
            'value_label':value_label,
            'note': value_label+('; mean_final_score separately reports conditional final net VP' if kind in ('round-scoring','final-scoring') else '')+'. Net-score competition ranks and shared wins. Descriptive associations, not causal recommendations.'}


def report(dataset, filters):
    rows = cohort(dataset, filters)
    groups = defaultdict(list)
    for row in rows:
        groups[row['faction']].append(row)
    return {'ruleset': filters['ruleset'], 'filters': filters, **summary(rows),
            'record_ids': [f"{r['game_id']}:{r['faction']}" for r in rows] if len(rows)<=2000 else None,
            'cohort_hash': hashlib.sha256('\n'.join(sorted(f"{r['game_id']}:{r['faction']}" for r in rows)).encode()).hexdigest(),
            'missing_elo': sum(r['elo'] is None for r in rows),
            'plots': {kind: statistics(rows, kind) for kind in ([filters['plot']] if filters.get('plot') else PLOTS)},
            'comparisons': [{'faction': faction, **summary(group)} for faction, group in sorted(groups.items())],
            'setup_comparisons': setup_comparisons(groups),
            'scope': dataset.get('scope')}


def setup_comparisons(groups):
    result={'rounds':[], 'finals':[], 'technologies':[]}
    scoring_keys = {'rounds': tuple(f'round{i}' for i in range(1, 7)),
                    'finals': ('final1', 'final2')}
    slots = tuple('adv-' + slot for slot in ('terra', 'nav', 'int', 'gaia', 'eco', 'sci', 'ext'))
    for faction, rows in sorted(groups.items()):
        # Visit each observation once instead of rescanning its technology list
        # for every track and looking up each measured tile value twice.
        values = {key: [] for keys in scoring_keys.values() for key in keys}
        acquired = {slot: [] for slot in slots}
        for row in rows:
            for key, observations in values.items():
                value = tile_value(row, key)
                if value is not None:
                    observations.append(value)
            for slot in {tech['slot'] for tech in (row.get('owned_technologies') or [])}:
                if slot in acquired:
                    acquired[slot].append(row['score'])
        for kind, keys in (*scoring_keys.items(), ('technologies', slots)):
            record = {'faction': faction, 'samples': len(rows)}
            for key in keys:
                observations = acquired[key] if kind == 'technologies' else values[key]
                record[key] = mean(observations) if observations else None
                record[key + '_n'] = len(observations)
            result[kind].append(record)
    return result


def export(dataset, filters):
    rows = cohort(dataset, filters)
    fields = ('game_id', 'ruleset', 'faction', 'player_count', 'score', 'rank', 'win_share',
              'elo', 'layout', 'auction', 'faction_variant', 'lf_2p_4qic_effective',
              'round_scorings', 'final_scorings', 'owned_technologies', 'round_one_structures', 'vp_sources',
              'vp_sources_raw', 'vp_ledger_complete', 'scoring_vp')
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(row.get(key)) if isinstance(row.get(key), (dict, list))
                         else row.get(key) for key in fields})
    return output.getvalue().encode()


def response(dataset, path, filters):
    root = Path(__file__).resolve().parent.parent / 'web' / 'cohort'
    if path == '/cohort/':
        return (root / 'index.html').read_bytes(), 'text/html; charset=utf-8'
    if path == '/cohort/app.js':
        return (root / 'app.js').read_bytes(), 'application/javascript'
    if path == '/cohort/api/catalog':
        version=filters.get('ruleset','lost-fleet')
        if version not in ('base','lost-fleet'):raise ValueError('Choose base or lost-fleet')
        rows = dataset['rows']
        result = {key: sorted({str(r[key]) for r in rows if r['ruleset'] == version})
                  for key in ('faction', 'layout', 'auction', 'faction_variant')}
        result.update({key: sorted({tile for r in rows if r['ruleset'] == version
                                    for tile in r[key]}) for key in ('round_scorings', 'final_scorings')})
        result['advanced_technologies'] = sorted({tile for r in rows if r['ruleset'] == version
                                                  for slot, tile in r['technologies'].items()
                                                  if slot.startswith('adv-')})
        return json.dumps(result).encode(), 'application/json'
    if path == '/cohort/api/stats':
        return json.dumps(report(dataset, filters), allow_nan=False).encode(), 'application/json'
    if path == '/cohort/api/export':
        return export(dataset, filters), 'text/csv; charset=utf-8'
    raise FileNotFoundError(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.raw.glob('*.json'), args.output)
    print(json.dumps({'accepted': len(result['accepted']), 'rejected': result['rejected'],
                      'records': len(result['rows'])}, indent=2))
