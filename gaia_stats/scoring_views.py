"""Rank-conditioned score shares and faction-relative round scoring views.

Accumulators hold scalar round totals and numeric distribution samples only, so
streaming and in-memory reports use identical definitions.
"""
import math
from collections import defaultdict
from statistics import quantiles
from .scoring import complete_ledger, tile_value, BASE_SOURCES

ROUND_FILTERS = tuple(f'round{i}' for i in range(1, 7))


def round_reference_filters(filters):
    return {key: value for key, value in filters.items() if key not in ROUND_FILTERS}


def distribution(values):
    cell = {'samples': len(values)}
    if values:
        q1, median, q3 = quantiles(values, n=4, method='inclusive') if len(values)>1 else (values[0],)*3
        cell.update(q1=q1, median=median, q3=q3, lower=min(values), upper=max(values))
    if len(values)<=2000:
        cell['values'] = values
    return cell


def known_source(row, source):
    if source == 'round':
        parts = [tile_value(row, key) for key in ROUND_FILTERS]
    elif source == 'final':
        parts = [tile_value(row, key) for key in ('final1', 'final2')]
    else:
        value = row['vp_sources'].get(source, 0 if complete_ledger(row) else None)
        parts = [value]
    return math.fsum(parts) if all(isinstance(v, (int,float)) and math.isfinite(v) for v in parts) else None


class ScoringViews:
    def __init__(self, filters):
        self.filters = filters
        self.shares = defaultdict(list)
        self.share_groups = set()
        self.sources = (set(BASE_SOURCES) - set(ROUND_FILTERS) - {'final1','final2'}) | {'round','final'}
        # Missing source in complete ledgers means zero, including sources first
        # encountered in later batches. Track zero counts per rank/count group.
        self.complete_counts = defaultdict(int)
        self.known_counts = defaultdict(int)
        self.invalid_denominators = 0
        self.round_totals = defaultdict(lambda: [0., 0, 0., 0, 0])
        self.baselines = defaultdict(lambda: [0., 0])

    def add_points(self, rows):
        for row in rows:
            score = row['score']
            if not isinstance(score, (int,float)) or not math.isfinite(score) or score<=0:
                self.invalid_denominators += 1
                continue
            group = (row['player_count'], row['rank'])
            self.share_groups.add(group)
            complete = complete_ledger(row)
            self.complete_counts[group] += int(complete)
            sources = (set(row['vp_sources']) - set(ROUND_FILTERS) - {'final1','final2'}) | {'round','final'}
            self.sources.update(sources)
            for source in sources:
                value = known_source(row, source)
                if complete:
                    self.known_counts[(group,source)] += 1
                if value is not None:
                    self.shares[(group, source)].append(100*value/score)

    def points(self):
        cells=[]
        for group in sorted(self.share_groups):
            for source in sorted(self.sources):
                key=(group,source)
                # Do not infer aggregate round/final zeros when tile data is unknown.
                zeros = 0 if source in ('round','final') else self.complete_counts[group]-self.known_counts[key]
                values=self.shares[key]+[0.]*zeros
                cells.append({'label':source,'player_count':group[0],'rank':group[1],**distribution(values)})
        return {'rank_cells':cells,'invalid_share_denominators':self.invalid_denominators,
                'share_note':'Signed contribution / positive final net score × 100, separately by competition rank and player count. Tied ranks stay tied. Round and final tiles are combined. Unknown contributions are excluded per source; complete-ledger absences are zero. Nonpositive scores excluded from shares only. No historical >100 cutoff or bid restoration; charge and bid remain negative. Descriptive distributions, not additive median percentages.'}

    def add_rounds(self, selected, reference):
        for row in reference:
            key=(row['faction'],row['player_count'])
            self.baselines[key][0] += row['win_share']
            self.baselines[key][1] += 1
        for row in selected:
            for index,tile in enumerate(row['round_scorings'],1):
                key=(row['faction'],row['player_count'],index,tile)
                total=self.round_totals[key]
                value=tile_value(row,f'round{index}')
                if value is not None:
                    total[0]+=value;total[1]+=1
                total[2]+=row['win_share'];total[3]+=1
                # One faction appearance per game, as enforced by dataset identity.
                total[4]+=1

    def rounds(self):
        cells=[]
        if self.filters.get('faction'):
            for (faction,count,index,tile),(vp,vp_n,wins,n,games) in sorted(self.round_totals.items()):
                baseline_wins,baseline_n=self.baselines[(faction,count)]
                baseline=baseline_wins/baseline_n if baseline_n else None
                cells.append({'label':f'{count}p: Round {index} / {tile}','x':f'Round {index} · {count}p','y':tile,
                              'round':index,'player_count':count,'faction':faction,'games':games,'samples':n,
                              'score_samples':vp_n,'mean_score':vp/vp_n if vp_n else None,'win_share':wins/n,
                              'win_baseline':baseline,'win_baseline_samples':baseline_n,
                              'win_difference':wins/n-baseline if baseline is not None else None})
        return {'comparison_cells':cells,'round_selection_required':None if self.filters.get('faction') else 'faction',
                'round_note':'Faction round scoring: observed tile VP and shared-win difference from this faction’s baseline, separately by player count. Baseline relaxes round1–round6 filters only; other settings, final-tile filters and Elo stay selected. Net-score wins split ties. Counts include wins independently of missing tile VP. Associations, not causal effects or a predicted optimal setup.'}
