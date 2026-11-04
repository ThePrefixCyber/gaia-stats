"""Merge bounded complete-game batches using the existing statistical definitions.

Retain only scalar group summaries and point-source values, not complete decoded
player records. Whole games stay in a batch so distinct-game counts are additive.
"""
from collections import Counter, defaultdict
import hashlib
import io
import math
from statistics import quantiles

from .cohort import report, export, cohort, final_scoring_comparison
from .scoring import complete_ledger


class Cell:
    def __init__(self):
        self.value = {}
        self.means = defaultdict(list)
        self.weights = Counter()

    def add(self, item, setup=False):
        for key, value in item.items():
            if key == 'rank_counts':
                self.value.setdefault(key, Counter()).update(value)
            elif key in ('samples', 'games', 'available', 'score_samples') or key.endswith('_n'):
                self.value[key] = self.value.get(key, 0) + value
            elif key.startswith('mean_') or key == 'win_share' or (setup and key not in ('faction', 'samples') and not key.endswith('_n')):
                weight_key = key + '_n' if setup or key + '_n' in item else ('score_samples' if key == 'mean_score' and 'score_samples' in item else 'samples')
                weight = item.get(weight_key, 0)
                if value is not None and weight:
                    self.means[key].append(value * weight)
                    self.weights[key] += weight
                else:
                    self.means.setdefault(key, [])
            elif key != 'frequency':
                self.value[key] = value

    def finish(self):
        result = dict(self.value)
        for key, values in self.means.items():
            result[key] = math.fsum(values) / self.weights[key] if self.weights[key] else None
        if 'available' in result:
            result['frequency'] = result['samples'] / result['available'] if result['available'] else None
        return result


def statistics(batches, filters, scope):
    total = Cell()
    comparisons = defaultdict(Cell)
    setup = {kind: defaultdict(Cell) for kind in ('rounds', 'finals', 'technologies')}
    plot_cells = defaultdict(lambda: defaultdict(Cell))
    plot_meta = {}
    tile_cells = defaultdict(lambda: defaultdict(Cell))
    points = {}
    prior_complete = 0
    identifiers = []
    missing_elo = 0
    for batch in batches:
        part = report({'rows': batch, 'scope': scope}, filters, finalize=False)
        # Batch size is below report's raw-identifier/box-value limit.
        identifiers.extend(part['record_ids'])
        missing_elo += part['missing_elo']
        total.add({k: part[k] for k in ('samples', 'games', 'mean_score', 'mean_rank', 'win_share', 'rank_counts')})
        for cell in part['comparisons']:
            comparisons[cell['faction']].add(cell)
        for kind, cells in part['setup_comparisons'].items():
            for cell in cells:
                setup[kind][cell['faction']].add(cell, setup=True)
        for kind, plot in part['plots'].items():
            if kind not in plot_meta:
                plot_meta[kind] = {k: v for k, v in plot.items() if k not in ('cells', 'tile_cells', 'unavailable_records')}
                plot_meta[kind]['unavailable_records'] = 0
            plot_meta[kind]['unavailable_records'] += plot['unavailable_records']
            for cell in plot.get('tile_cells', []):
                tile_cells[kind][cell['label']].add(cell)
            if kind == 'point-sources':
                # Only selected complete ledgers imply zeros for absent sources.
                complete = sum(complete_ledger(row) for row in cohort({'rows': batch}, filters))
                present = {cell['label'] for cell in plot['cells']}
                for label in points.keys() - present:
                    points[label].extend([0] * complete)
            for cell in plot['cells']:
                if kind == 'point-sources':
                    label = cell['label']
                    if label not in points:
                        # The source may first appear after several complete batches.
                        points[label] = [0] * prior_complete
                    points[label].extend(cell['values'])
                else:
                    key = (cell['x'], cell['y']) if 'x' in cell else tuple(cell['label'].split(' / '))
                    plot_cells[kind][key].add(cell)
            if kind == 'point-sources':
                prior_complete += complete
    if not identifiers:
        return report({'rows': [], 'scope': scope}, filters)
    plots = {}
    for kind, meta in plot_meta.items():
        cells = []
        if kind == 'point-sources':
            for label, values in sorted(points.items()):
                cell = {'label': label, 'samples': len(values)}
                if values:
                    q1, median, q3 = quantiles(values, n=4, method='inclusive') if len(values)>1 else (values[0],)*3
                    cell.update(q1=q1, median=median, q3=q3, lower=min(values), upper=max(values))
                if len(values)<=2000:
                    cell['values'] = values
                cells.append(cell)
        else:
            cells = [cell.finish() for _, cell in sorted(plot_cells[kind].items())]
        plots[kind] = {**meta, 'cells': cells}
        if 'tech-' in kind:
            plots[kind]['tile_cells'] = [cell.finish() for _, cell in sorted(tile_cells[kind].items())]
        if kind == 'final-scoring':
            plots[kind] = final_scoring_comparison(plots[kind], filters)
    return {'ruleset': filters['ruleset'], 'filters': filters, **total.finish(),
            'record_ids': identifiers if len(identifiers)<=2000 else None,
            'cohort_hash': hashlib.sha256('\n'.join(sorted(identifiers)).encode()).hexdigest(),
            'missing_elo': missing_elo, 'plots': plots,
            'comparisons': [cell.finish() for _, cell in sorted(comparisons.items())],
            'setup_comparisons': {kind: [cell.finish() for _, cell in sorted(groups.items())] for kind, groups in setup.items()},
            'scope': scope}


def csv_export(batches, filters):
    output = io.BytesIO()
    wrote_header = False
    for batch in batches:
        body = export({'rows': batch}, filters)
        output.write(body if not wrote_header else body.split(b'\r\n', 1)[1])
        wrote_header = True
    return output.getvalue() if wrote_header else export({'rows': []}, filters)
