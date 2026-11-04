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

from .eligibility import POLICY_VERSION, ExcludedGame, eligible_rows, require_eligible_export
from .analysis import normalize, select
from .__main__ import atomic_json
from .scoring import complete_ledger, tile_value
from .scoring_views import ScoringViews, round_reference_filters
from .chart_groups import technology_id, opening_configuration

PLOTS = ('advanced-tech-frequency', 'advanced-tech-score', 'basic-tech-frequency',
         'basic-tech-score', 'basic-tech-setup-score', 'round-one-structures', 'final-scoring',
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
    excluded = set()
    invalid = False
    for path in sorted(map(Path, paths)):
        raw = path.read_bytes()
        provenance = {'file': path.name, 'sha256': hashlib.sha256(raw).hexdigest()}
        try:
            game = json.loads(raw)
            identifier=game.get('slug') or game.get('_id')
            canonical=hashlib.sha256(json.dumps(game,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if not identifier:raise ValueError('Missing game identifier')
            provenance['game_id'] = identifier
            require_eligible_export(game)
            if identifier in excluded:continue
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
        except ExcludedGame as error:
            excluded.add(identifier)
            rejected.append({**provenance, 'reason': str(error)})
        except (KeyError, ValueError, TypeError) as error:
            invalid = True
            rejected.append({**provenance, 'reason': str(error)})
    rows = [r for r in rows if r['game_id'] not in excluded]
    accepted = [p for p in accepted if p['game_id'] not in excluded]
    dataset = {'schema_version': 1, 'eligibility_policy': POLICY_VERSION, 'rows': rows, 'accepted': accepted, 'rejected': rejected,
               'excluded_game_ids': sorted(excluded),
               'scope': 'Bounded public Lost Fleet sample; not a representative archive'}
    if not rows and (not excluded or invalid):raise ValueError('No accepted complete games; existing dataset preserved')
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
    extra = {}
    if 'tech-' in kind:
        tile_groups = defaultdict(list)
        tile_opportunities, unplaced = Counter(), Counter()
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
            # A tile is one opportunity/acquisition per player-game, even if
            # duplicate setup slots or duplicate/covered ownership records exist.
            available_tiles = {technology_id(tile, advanced) for slot, tile in available.items()
                               if slot.startswith('adv-') == advanced}
            taken_tiles = {technology_id(t['tile'], advanced) for t in owned
                           if t['slot'].startswith('adv-') == advanced}
            tile_opportunities.update(available_tiles)
            unplaced.update(taken_tiles - available_tiles)
            for tile in taken_tiles & available_tiles:
                tile_groups[tile].append(row)
        keys = sorted(set(groups) | set(opportunities))
        cells = [{'label': f'{tile} / {slot}', **summary(groups[(tile, slot)]),
                  'available': opportunities[(tile, slot)],
                  'frequency': len(groups[(tile, slot)]) / opportunities[(tile, slot)]
                  if opportunities[(tile, slot)] else None} for tile, slot in keys]
        extra['tile_cells'] = [
            {'label': tile, **summary(tile_groups[tile]), 'available': tile_opportunities[tile],
             'frequency': len(tile_groups[tile]) / tile_opportunities[tile] if tile_opportunities[tile] else None,
             'unavailable_taken_n': unplaced[tile]}
            for tile in sorted(set(tile_opportunities) | set(unplaced))]
    elif kind == 'round-one-structures':
        configurations = {}
        for row in rows:
            configuration = opening_configuration(row.get('round_one_structures'))
            if configuration is None:
                unavailable += 1
                continue
            category, label, counts = configuration
            configurations[label] = (category, counts)
            groups[label].append(row)
        cells = []
        for label, group in sorted(groups.items()):
            category, counts = configurations[label]
            ratings = [row['elo'] for row in group if row['elo'] is not None]
            cells.append({'label': label, 'structure_class': category, 'structures': counts,
                          **summary(group), 'mean_elo': mean(ratings) if ratings else None,
                          'mean_elo_n': len(ratings)})
    elif kind in ('round-scoring', 'final-scoring'):
        for row in rows:
            if kind == 'round-scoring':
                for index, tile in enumerate(row['round_scorings']):
                    groups[(f'Round {index + 1}', tile)].append(row)
            else:
                pair = tuple(sorted(row['final_scorings']))
                groups[(pair, row['player_count'], row['faction'])].append(row)
        if kind == 'final-scoring':
            cells = [{'label': f"{count}p: {' + '.join(pair)} / {faction}",
                      'x': f"{count}p: {' + '.join(pair)}", 'y': faction,
                      'tiles': list(pair), 'player_count': count, 'faction': faction,
                      **summary(group)}
                     for (pair, count, faction), group in sorted(groups.items())]
            cells.sort(key=lambda cell: (cell['x'], cell['y']))
        else:
            cells = [{'label': ' / '.join(key), 'x': key[0], 'y': key[1], **summary(group)}
                     for key, group in sorted(groups.items())]
    else:
        sources = sorted({key for row in rows for key in row['vp_sources'] if key != 'bid'})
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
    if kind in ('basic-tech-frequency','basic-tech-score','basic-tech-setup-score'):
        from .basic_tech import statistics as basic_statistics
        # Preserve the deduplicated tile summaries for API compatibility; the
        # three requested basic-tech charts use their distinct setup cohorts.
        return {**basic_statistics(rows, kind), **extra}
    value_label='Mean pre-bid VP'
    if kind in ('round-scoring','final-scoring'):
        value_label='Mean VP earned from scoring tile(s)'
        for cell in cells:
            group=groups[(tuple(cell['tiles']),cell['player_count'],cell['faction'])] if kind=='final-scoring' else groups[(cell['x'],cell['y'])]
            keys=[f"round{cell['x'].split()[-1]}"] if kind=='round-scoring' else ['final1','final2']
            values=[sum(tile_value(r,k) for k in keys) for r in group if all(tile_value(r,k) is not None for k in keys)]
            cell['mean_final_score']=cell['mean_score']
            cell['mean_score']=mean(values) if values else None
            cell['score_samples']=len(values)
        required=[f'round{i}' for i in range(1,7)] if kind=='round-scoring' else ['final1','final2']
        unavailable=sum(any(tile_value(r,k) is None for k in required) for r in rows)
    final_note = (' Select a faction to compare final tile pairs. VP difference uses all factions with the same pair and player count; '
                  'win difference uses this faction and player count across all pairs, relaxing final-tile filters only. '
                  'Both baselines retain ruleset, Elo and other selected settings. '
                  'Pre-bid-score shared wins split ties; these descriptive differences are not causal tile effects.') if kind=='final-scoring' else ''
    return {'kind': kind, 'cells': cells, **extra, 'unavailable_records': unavailable,
            'value_label':value_label,
            'note': value_label+('; mean_final_score separately reports conditional pre-bid VP' if kind in ('round-scoring','final-scoring') else '')+'. Pre-bid-score competition ranks and shared wins. Descriptive associations, not causal recommendations.'+final_note}


def final_reference_filters(filters):
    """Relax only the dimensions explicitly required by the comparison baselines."""
    return {k: v for k, v in filters.items() if k not in ('faction','final_scoring','final_scoring2')}


def final_scoring_comparison(plot, filters):
    """Finish after all batches: never average per-batch differences/baselines."""
    cells = plot['cells']
    if not filters.get('faction'):
        return {**plot, 'cells': [], 'selection_required': 'faction'}
    pair_totals = defaultdict(lambda: [0, 0])
    faction_totals = defaultdict(lambda: [0, 0])
    for cell in cells:
        pair = (tuple(cell['tiles']),cell['player_count'])
        if cell['mean_score'] is not None:
            pair_totals[pair][0] += cell['mean_score'] * cell['score_samples']
            pair_totals[pair][1] += cell['score_samples']
        faction = (cell['faction'],cell['player_count'])
        faction_totals[faction][0] += cell['win_share'] * cell['samples']
        faction_totals[faction][1] += cell['samples']
    selected=[]
    for cell in cells:
        if cell['faction'] != filters['faction'] or any(filters.get(k) and filters[k] not in cell['tiles'] for k in ('final_scoring','final_scoring2')):
            continue
        score_total, score_n = pair_totals[(tuple(cell['tiles']),cell['player_count'])]
        wins, win_n = faction_totals[(cell['faction'],cell['player_count'])]
        score_base = score_total / score_n if score_n else None
        win_base = wins / win_n if win_n else None
        selected.append({**cell, 'score_baseline':score_base,'score_baseline_samples':score_n,
                         'win_baseline':win_base,'win_baseline_samples':win_n,
                         'score_difference':cell['mean_score']-score_base if cell['mean_score'] is not None and score_base is not None else None,
                         'win_difference':cell['win_share']-win_base if win_base is not None else None})
    return {**plot, 'cells':selected, 'selection_required':None}


def report(dataset, filters, *, finalize=True):
    if filters.get('plot') in (None,'basic-tech-frequency','basic-tech-score','basic-tech-setup-score'):
        from .basic_tech import prepare
        dataset = {**dataset, 'rows':prepare(dataset['rows'])}
    rows = cohort(dataset, filters)
    # Persistent faction comparisons retain the setup and every other filter,
    # but the chart, selected-cohort summary and export still honor faction.
    comparison_rows = (cohort(dataset, {k: v for k, v in filters.items() if k != 'faction'})
                       if filters.get('faction') else rows)
    groups = defaultdict(list)
    for row in comparison_rows:
        groups[row['faction']].append(row)
    plots = {}
    for kind in ([filters['plot']] if filters.get('plot') else PLOTS):
        if kind == 'final-scoring':
            plot = statistics(cohort(dataset, final_reference_filters(filters)), kind)
            plot['unavailable_records'] = sum(any(tile_value(r,k) is None for k in ('final1','final2')) for r in rows)
            plots[kind] = final_scoring_comparison(plot, filters) if finalize else plot
        else:
            plots[kind] = statistics(rows, kind)
        if finalize and kind in ('point-sources', 'round-scoring'):
            view = ScoringViews(filters)
            if kind == 'point-sources':
                view.add_points(rows)
                plots[kind].update(view.points())
            else:
                view.add_rounds(rows, cohort(dataset, round_reference_filters(filters)))
                plots[kind].update(view.rounds())
    return {'ruleset': filters['ruleset'], 'filters': filters, **summary(rows),
            'record_ids': [f"{r['game_id']}:{r['faction']}" for r in rows] if len(rows)<=2000 else None,
            'cohort_hash': hashlib.sha256('\n'.join(sorted(f"{r['game_id']}:{r['faction']}" for r in rows)).encode()).hexdigest(),
            'missing_elo': sum(r['elo'] is None for r in rows),
            'plots': plots,
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
    fields = ('game_id', 'ruleset', 'faction', 'player_count', 'score', 'reported_score', 'bid_delta', 'bid_cost',
              'score_basis_version', 'rank', 'win_share', 'reported_rank', 'reported_win_share',
              'elo', 'layout', 'auction', 'faction_variant', 'lf_2p_4qic_effective',
              'round_scorings', 'final_scorings', 'owned_technologies', 'round_one_structures', 'vp_sources',
              'vp_sources_raw', 'vp_sources_audit', 'vp_sources_csv_position',
              'csv_source_rank', 'csv_sources_unavailable', 'vp_ledger_complete', 'scoring_vp')
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
    if path == '/cohort/tile-labels.js':
        script = (root / 'tile-labels.js').read_text()
        registry = json.loads((root / 'tile-labels.json').read_text())
        return script.replace('__TILE_REGISTRY__', json.dumps(registry)).encode(), 'application/javascript'
    assets = {'/cohort/basic-tech.js': ('basic-tech.js', 'application/javascript'),
              '/cohort/app.js': ('app.js', 'application/javascript'),
              '/cohort/tables.js': ('tables.js', 'application/javascript'),
              '/cohort/styles.css': ('styles.css', 'text/css; charset=utf-8')}
    if path in assets:
        filename, content_type = assets[path]
        return (root / filename).read_bytes(), content_type
    if path == '/cohort/api/catalog':
        version=filters.get('ruleset','lost-fleet')
        if version not in ('base','lost-fleet'):raise ValueError('Choose base or lost-fleet')
        rows = eligible_rows(dataset['rows'])
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
