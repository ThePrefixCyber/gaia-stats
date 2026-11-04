"""Phase-aware VP views. Raw BGS sources remain available for audit."""
from collections import Counter
import re

NORMALIZATION_VERSION = 3
RESEARCH_TRACKS = ('terra', 'nav', 'int', 'gaia', 'eco', 'sci')
TILE_SOURCES = tuple(f'round{i}' for i in range(1, 7)) + ('final1', 'final2')
BASE_SOURCES = ('init', 'bid', 'charge', 'booster', *TILE_SOURCES, 'fed',
                'adv', 'tech_basic', 'qic', 'gaia', 'gleens', 'resource', 'research')


def phase_views(data, player_count):
    """Count each VP event once; never fold final research into in-game Gaia VP."""
    canonical = [Counter(init=10) for _ in range(player_count)]
    tiles = [dict.fromkeys(TILE_SOURCES, 0) for _ in range(player_count)]
    errors = [None] * player_count
    phase, round_number, ended = None, 0, False
    for event in data['advancedLog']:
        phase = event.get('phase', phase)
        round_number = event.get('round', round_number)
        ended |= event.get('phase') == 'endGame'
        pos = event.get('player')
        if pos is None:
            continue
        if type(pos) is not int or not 0 <= pos < player_count:
            raise ValueError('Invalid log player')
        for source, changes in event.get('changes', {}).items():
            if 'vp' not in changes:
                continue
            value = changes['vp']
            category = None
            if source in TILE_SOURCES:
                appropriate = (phase == 'endGame' if source.startswith('final')
                               else phase != 'endGame' and round_number == int(source[5:]))
                if appropriate:
                    tiles[pos][source] += value
                    category = source
                elif value:
                    errors[pos] = 'Scoring-tile VP appears outside its expected round/phase'
            elif phase == 'endGame' and source in RESEARCH_TRACKS:
                category = 'research'
            elif phase == 'endGame' and source == 'spend':
                category = 'resource'
            elif source in ('bid', 'charge', 'gleens'):
                category = source
            elif source == 'gaia' and phase != 'endGame':
                category = 'gaia'
            elif source == 'federation':
                category = 'fed'
            elif source.startswith('booster'):
                category = 'booster'
            elif source.startswith('adv-'):
                category = 'adv'
            elif source.startswith('tech-'):
                category = 'tech_basic'
            elif re.fullmatch(r'qic[1-3]', source):
                category = 'qic'
            if category is not None:
                canonical[pos][category] += value
            elif value:
                # Preserve new/unsupported scoring sources explicitly, never discard VP.
                canonical[pos]['unmapped:' + source] += value
    complete = ended and data.get('phase') == 'endGame'
    return canonical, tiles, errors, complete


def complete_ledger(row):
    # Older LF snapshots already used complete-log zero semantics for source boxes.
    # New explicit False always wins; historical CSV absence remains unknown.
    return row.get('vp_ledger_complete', row['ruleset'] == 'lost-fleet')


def tile_value(row, key):
    if 'scoring_vp' in row:
        values = row['scoring_vp']
        return values.get(key, 0) if values is not None and complete_ledger(row) else None
    if row['ruleset'] == 'base':
        return row['vp_sources'].get(key)  # Historical CSV: absent is unknown.
    return None  # Older LF snapshots must be recomputed from phase-aware raw logs.
