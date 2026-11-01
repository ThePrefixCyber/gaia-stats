"""Descriptive setup comparisons from Tim's published aggregate data.

These are marginal historical summaries, not predictions for an exact setup.
No missing value or zero-count technology is presented as an observed zero.
"""
import math

ROUND_TILES = ('2vp_per_terra', '2vp_per_research_bump', '2vp_per_mine_place',
               '5vp_per_fed_place', '4vp_per_ts_place', '4vp_per_gaia_place',
               '5vp_per_3pip_place', '3vp_per_ts_place', '3vp_per_gaia_place')
ADVANCED_TILES = ('3vp_per_fed_pass', '2vp_per_tech_bump', '1qic_5c_action',
                  '2vp_per_mine', '3vp_per_rl_pass', '1o_per_sector',
                  '1vp_per_terra_pass', '2vp_per_gaia', '4vp_per_ts',
                  '2vp_per_sector', '3o_action', '5vp_per_fed', '3k_action',
                  '3vp_per_mine_place', '3vp_per_ts_place')
FINAL_TILES = ('planetType', 'structure', 'sector', 'satellite', 'gaia', 'structureFed')
TRACKS = ('terra', 'nav', 'int', 'gaia', 'eco', 'sci')


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def lookup(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def validate_aggregates(data):
    """Accept partial cells but reject an unrelated or malformed top-level file."""
    from .legacy_cache import FACTIONS
    if not isinstance(data, dict) or not data or set(data) - {'2', '3', '4'}:
        raise ValueError('Comparison data must be keyed by player counts 2, 3, 4')
    for players, factions in data.items():
        if not isinstance(factions, dict) or not factions or set(factions) - set(FACTIONS):
            raise ValueError('Invalid comparison faction data for ' + players)
        for values in factions.values():
            if not isinstance(values, dict) or not all(isinstance(values.get(k), dict)
                    for k in ('round_scoring', 'final_scoring', 'advanced_tech')):
                raise ValueError('Comparison data requires round, final and advanced-tech aggregates')


def compare(data, query):
    from .legacy_cache import FACTIONS
    players = query.get('num_players', '4')
    if players not in ('2', '3', '4'):
        raise ValueError('Choose 2, 3 or 4 players')
    if players not in data:
        raise ValueError('Comparison data is unavailable for this player count')
    rounds = [query.get(f'round_{i+1}', ROUND_TILES[i]) for i in range(6)]
    advanced = [query.get(f'adv_{i+1}', ADVANCED_TILES[i]) for i in range(6)]
    finals = [query.get('final_1', 'planetType'), query.get('final_2', 'structure')]
    if (any(x not in ROUND_TILES for x in rounds) or any(rounds.count(x) >
            (2 if x == '5vp_per_3pip_place' else 1) for x in rounds)):
        raise ValueError('Choose legal round tiles; only the PI/academy tile may repeat twice')
    if any(x not in ADVANCED_TILES for x in advanced) or len(set(advanced)) != 6:
        raise ValueError('Choose six distinct advanced technologies')
    if any(x not in FINAL_TILES for x in finals) or len(set(finals)) != 2:
        raise ValueError('Choose two distinct final scoring tiles')
    rows = []
    for faction in FACTIONS:
        source = data[players].get(faction, {})
        round_values = {}
        for field in ('points', 'vict_prob', 'delta_vict_prob'):
            values = [number(lookup(source, 'round_scoring', tile, str(i+1), field))
                      for i, tile in enumerate(rounds)]
            round_values[field] = None if None in values else sum(values) / (1 if field == 'points' else 6)
        final_values = {field: number(lookup(source, 'final_scoring', *finals, field))
                        for field in ('points', 'vict_prob', 'delta_vict_prob')}
        scores, weighted = [], []
        for track, tile in zip(TRACKS, advanced):
            record = lookup(source, 'advanced_tech', tile, 'tech_adv-' + track)
            score, count, missed = (number(lookup(record, k)) for k in ('score', 'count', 'missed'))
            if score is not None and count is not None and count > 0:
                scores.append((score, tile))
                if missed is not None and missed >= 0:
                    weighted.append((score * count / (count + missed), tile))
        def maximum(values):
            if not values:
                return None
            value, tile = max(values, key=lambda item: item[0])
            return {'value': value, 'tile': tile}
        rows.append({'faction': faction, 'round': round_values, 'final': final_values,
                     'advanced': {'max_score': maximum(scores), 'max_weighted_score': maximum(weighted),
                                  'weighted_sum': sum(v for v, _ in weighted) if len(weighted) == 6 else None,
                                  'observed_tracks': len(scores), 'weighted_tracks': len(weighted)}})
    return {'players': int(players), 'rounds': rounds, 'advanced_tiles': advanced,
            'finals': finals, 'rows': rows, 'kind': 'historical-marginal-aggregates'}
