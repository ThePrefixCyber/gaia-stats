"""Site-wide game eligibility, independent of optional analysis filters.

Only the literal BGS faction variant identifies an excluded game. Missing,
unknown and other values are never inferred from faction boards or QIC options.
Raw exports and source CSVs are intentionally not modified by these helpers.
"""
EXCLUDED_FACTION_VARIANT = 'more-balanced'
POLICY_VERSION = 1


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


def excluded_export(game):
    return EXCLUDED_FACTION_VARIANT in variant_sources(game).values()


def require_eligible_export(game):
    if excluded_export(game):
        raise ExcludedGame('Excluded faction variant: more-balanced')


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
            EXCLUDED_FACTION_VARIANT in row.get('faction_variant_sources', {}).values())


def excluded_ids(rows):
    return {row['game_id'] for row in rows if excluded_row(row)}


def eligible_rows(rows):
    """Drop the whole game, even if only one persisted row carries its marker."""
    blocked = excluded_ids(rows)
    return [row for row in rows if row['game_id'] not in blocked]


def eligible_frame(frame):
    """Filter historical wide CSVs without mutating the caller's dataframe."""
    if 'balance_variant' not in frame:
        return frame
    blocked = frame['balance_variant'].eq(EXCLUDED_FACTION_VARIANT)
    if 'id' in frame:
        blocked = frame['id'].isin(frame.loc[blocked, 'id'])
    return frame.loc[~blocked]


# Match both persisted metadata locations and exclude every observation of a game.
# Older databases remain safe to serve before the next publication rebuild.
BASE_ELIGIBLE_SQL = """game_id NOT IN (
    SELECT game_id FROM observations WHERE faction_variant = 'more-balanced'
    OR json_extract(payload, '$.faction_variant') = 'more-balanced'
    OR EXISTS (SELECT 1 FROM json_each(json_extract(payload, '$.faction_variant_sources'))
               WHERE value = 'more-balanced'))"""
