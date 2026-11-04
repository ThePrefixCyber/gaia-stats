"""Site-wide game eligibility, independent of optional analysis filters.

A game is excluded when its exact BGS faction variant is more-balanced or any
observed score before auction bids is below 100. Missing scores are not zero and do not
create exclusion evidence. Raw normalization still requires complete scores.
Raw exports and source CSVs are intentionally not modified by these helpers.
"""
import math

from .score_basis import BASE_SCORE_SQL, csv_score, raw_scores, row_score, number

EXCLUDED_FACTION_VARIANT = 'more-balanced'
MIN_FINAL_SCORE = 100
POLICY_VERSION = 3
SUPPORTED_POLICY_VERSIONS = (1, POLICY_VERSION)


def require_safe_policy(version):
    # Version 2 used the superseded net-score cutoff and was never deployed.
    # Its tombstones can hide valid pre-bid games and are not monotonic evidence.
    if version in (2, '2'):
        raise ValueError('Unsupported net-score eligibility policy 2; rebuild from preserved original sources into a new release store')


def final_score(value):
    """A numeric final result, distinct from missing/malformed values and booleans."""
    return value if type(value) in (int, float) and math.isfinite(value) else None


def below_minimum(value):
    score = final_score(value)
    return score is not None and score < MIN_FINAL_SCORE


def excluded_csv_game(game):
    count = number(game.get('num_players'))
    positions = range(1, int(count) + 1) if count in (2, 3, 4) else range(1, 5)
    return (game.get('balance_variant') == EXCLUDED_FACTION_VARIANT or
            any(below_minimum(csv_score(game, position)) for position in positions))


class ExcludedGame(ValueError):
    pass


def variant_sources(game):
    observed = {}
    if isinstance(game, dict):
        for container in ('game', 'data'):
            value = game.get(container)
            options = value.get('options') if isinstance(value, dict) else None
            if isinstance(options, dict) and 'factionVariant' in options:
                observed[container + '.options'] = options['factionVariant']
    return observed


def export_exclusion_reasons(game):
    reasons = []
    if EXCLUDED_FACTION_VARIANT in variant_sources(game).values():
        reasons.append('Excluded faction variant: more-balanced')
    if isinstance(game, dict) and any(below_minimum(score) for score in raw_scores(game)):
        reasons.append('Excluded game: score before auction bids below 100 VP')
    return reasons


def excluded_export(game):
    return bool(export_exclusion_reasons(game))


def require_eligible_export(game):
    reasons = export_exclusion_reasons(game)
    if reasons:
        raise ExcludedGame('; '.join(reasons))


def faction_variant(game):
    observed = variant_sources(game)
    values = [value for value in observed.values() if value not in (None, '')]
    if any(not isinstance(value, str) for value in values):
        raise ValueError('Invalid factionVariant metadata')
    known = set(values) - {'unknown'}
    if len(known) > 1:
        raise ValueError('Conflicting factionVariant metadata')
    return (next(iter(known)) if known else 'unknown'), observed


def stored_exclusions(value):
    """Validate persisted exclusion evidence instead of accepting arbitrary JSON."""
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise ValueError('Invalid stored game-exclusion IDs')
    return set(value)


def excluded_row(row):
    return (row.get('faction_variant') == EXCLUDED_FACTION_VARIANT or
            EXCLUDED_FACTION_VARIANT in row.get('faction_variant_sources', {}).values() or
            below_minimum(row_score(row)))


def excluded_ids(rows):
    return {row['game_id'] for row in rows if excluded_row(row)}


def eligible_rows(rows):
    """Drop the whole game, even if only one persisted row carries its marker."""
    blocked = excluded_ids(rows)
    return [row for row in rows if row['game_id'] not in blocked]


def eligible_frame(frame):
    """Filter historical wide CSVs without mutating the caller's dataframe."""
    import pandas as pd
    # Do not expand hundreds of source columns into Python dictionaries for
    # every chart; eligibility only needs the aligned score/cost metadata.
    columns = ['balance_variant', 'num_players'] + [f'pos_{p}_{key}' for p in range(1, 5)
                                     for key in ('score', 'bid', 'score_bid')]
    columns = [key for key in columns if key in frame]
    blocked = pd.Series(False, index=frame.index, dtype=bool)
    if columns:
        records = frame[columns].to_dict(orient='records')
        blocked = pd.Series([excluded_csv_game(row) for row in records], index=frame.index, dtype=bool)
    if 'id' in frame:
        blocked = frame['id'].isin(frame.loc[blocked, 'id'])
    return frame.loc[~blocked]


# Match both persisted metadata locations and exclude every observation of a game.
# Older databases remain safe to serve before the next publication rebuild.
BASE_ELIGIBLE_SQL = f"""game_id NOT IN (
    SELECT game_id FROM observations WHERE faction_variant = 'more-balanced'
    OR json_extract(payload, '$.faction_variant') = 'more-balanced'
    OR ({BASE_SCORE_SQL}) < {MIN_FINAL_SCORE}
    OR EXISTS (SELECT 1 FROM json_each(json_extract(payload, '$.faction_variant_sources'))
               WHERE value = 'more-balanced'))"""
