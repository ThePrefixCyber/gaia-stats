"""Auction-free analytical scores, with original results retained for audit.

BGS state ``bid`` is a positive cost, not a signed VP event. Historical CSV
``score_bid`` bundles use net-rank positions, unlike the main player metadata.
CSV totals use that player’s positive ``bid``; source bundles are remapped below.
"""
from collections import defaultdict
import math

from .scoring import complete_ledger
from .technology_locations import sources as grouped_sources

SCORE_BASIS_VERSION = 'prebid-v1'


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def csv_score(game, position):
    prefix = f'pos_{position}_'
    score, bid = number(game.get(prefix + 'score')), number(game.get(prefix + 'bid'))
    return score + bid if score is not None and bid is not None and bid >= 0 else None


def csv_sources(game, position):
    """Recover untied CSV source ownership; tied overwritten bundles stay unknown."""
    count = int(number(game.get('num_players')) or 0)
    scores = [number(game.get(f'pos_{p}_score')) for p in range(1, count + 1)]
    own = number(game.get(f'pos_{position}_score'))
    aligned = game.get('score_source_layout') == 'player-position-v1'
    if own is None or None in scores or (scores.count(own) != 1 and not aligned):
        return {}, None
    net_rank = 1 + sum(score > own for score in scores)
    bid = number(game.get(f'pos_{position}_bid'))
    research = number(game.get(f'pos_{position}_tech_score'))
    if bid is None or bid < 0 or research is None:
        return {}, None
    candidates = []
    # Historical exports used net rank; newer parsers use aligned metadata
    # positions. Accept only reconciled, unambiguous ownership in either schema.
    for rank in ([position] if aligned else sorted({position, net_rank})):
        prefix = f'pos_{rank}_score_'
        sources = {key.removeprefix(prefix): number(value) for key, value in game.items() if key.startswith(prefix)}
        sources = {key: value for key, value in sources.items() if value is not None}
        if sources.get('bid') == -bid and sum(sources.values()) + research == own:
            candidates.append((sources, rank))
    if not candidates or any(sources != candidates[0][0] for sources, _ in candidates):
        return {}, None
    return candidates[0]


def persisted_number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def row_bid_delta(row):
    # Old CSV SQLite rows lost the aligned positive cost. Reimport the source
    # CSV rather than apply a different player's source-column bid.
    if row.get('ruleset') == 'base' and 'vp_sources_raw' not in row and row.get('score_basis_version') != SCORE_BASIS_VERSION and 'bid_cost' not in row:
        return None
    if 'bid_delta' in row:
        return persisted_number(row['bid_delta'])
    for key in ('vp_sources_raw', 'vp_sources_audit', 'vp_sources'):
        sources = row.get(key) or {}
        if 'bid' in sources:
            return persisted_number(sources['bid'])
    raw = row.get('vp_sources_raw')
    if isinstance(raw, dict) and row.get('score_verified') is True and all(persisted_number(v) is not None for v in raw.values()) and sum(raw.values()) == persisted_number(row.get('reported_score', row.get('score'))):
        return 0.
    # Legacy LF snapshots were accepted only after full raw-ledger verification.
    if row.get('vp_ledger_complete', row.get('ruleset') == 'lost-fleet' and row.get('score_verified') is True):
        return 0.
    return None


def row_score(row):
    if row.get('score_basis_version') == SCORE_BASIS_VERSION:
        return persisted_number(row.get('score'))
    score = persisted_number(row.get('reported_score', row.get('score')))
    bid = row_bid_delta(row)
    return score - bid if score is not None and bid is not None else None


def raw_scores(game):
    """Read only complete reconciled raw ledgers; never infer an absent bid early."""
    if not isinstance(game, dict) or not isinstance(game.get('players', []), list):
        return []
    players = game.get('players', [])
    result = [None] * len(players)
    data = game.get('data') or {}
    if game.get('status') != 'ended' or data.get('phase') not in (None, 'endGame'):
        return result
    totals = [10.] * len(players)
    bids = [0.] * len(players)
    rounds, ended = set(), False
    try:
        for event in data.get('advancedLog', []):
            if 'round' in event:
                rounds.add(event['round'])
            ended |= event.get('phase') == 'endGame'
            pos = event.get('player')
            if pos is None:
                continue
            if type(pos) is not int or not 0 <= pos < len(players):
                return result
            for source, changes in event.get('changes', {}).items():
                if 'vp' not in changes:
                    continue
                value = persisted_number(changes['vp'])
                if value is None:
                    return result
                totals[pos] += value
                if source == 'bid':
                    bids[pos] += value
        if not ended or rounds != set(range(1, 7)):
            return result
        for pos, player in enumerate(players):
            reported = persisted_number(player.get('score'))
            if reported is not None and totals[pos] == reported:
                result[pos] = reported - bids[pos]
    except (TypeError, AttributeError):
        return result
    return result


def analysis_rows(rows):
    """Normalize old/new snapshots without mutation, before player-level filters.

    Incomplete old groups cannot establish auction-free ranks; new rows already
    carry ranks calculated over their complete game and may be selected again.
    Unknown auction contributions remain unknown, rather than invented zeros.
    """
    groups = defaultdict(list)
    rerank = set()
    for original in rows:
        row = dict(original)
        score = row_score(row)
        new = row.get('score_basis_version') == SCORE_BASIS_VERSION
        sources = dict(row.get('vp_sources') or {})
        row.setdefault('reported_score', row.get('score'))
        row.setdefault('reported_rank', row.get('rank'))
        row.setdefault('reported_win_share', row.get('win_share'))
        row.setdefault('vp_sources_audit', sources)
        row['bid_delta'] = row_bid_delta(row)
        row['score'] = score
        row['score_basis_version'] = SCORE_BASIS_VERSION
        row['score_basis'] = 'Final VP excluding signed auction contribution'
        row['vp_sources'] = grouped_sources({key: value for key, value in sources.items() if key != 'bid'},
                                           complete=complete_ledger(row))
        if not new:
            rerank.add(row['game_id'])
            row['rank'] = row['win_share'] = None
        groups[row['game_id']].append(row)
    result = []
    for group in groups.values():
        scores = [row['score'] for row in group]
        complete = len(group) == group[0].get('player_count')
        if group[0]['game_id'] in rerank and complete and all(score is not None for score in scores):
            best = max(scores)
            ties = scores.count(best)
            for row in group:
                row['rank'] = 1 + sum(score > row['score'] for score in scores)
                row['win_share'] = 1 / ties if row['score'] == best else 0
        result.extend(group)
    return result


# Same semantics as row_score(), for SQLite payloads predating this normalization.
# JSON numeric types intentionally reject booleans, null, text and malformed data.
_BID_SQL = """CASE
 WHEN json_type(payload, '$.bid_delta') IS NOT NULL THEN CASE WHEN json_type(payload, '$.bid_delta') IN ('integer','real') THEN json_extract(payload, '$.bid_delta') END
 WHEN json_type(payload, '$.vp_sources_raw.bid') IS NOT NULL THEN CASE WHEN json_type(payload, '$.vp_sources_raw.bid') IN ('integer','real') THEN json_extract(payload, '$.vp_sources_raw.bid') END
 WHEN json_type(payload, '$.vp_sources_audit.bid') IS NOT NULL THEN CASE WHEN json_type(payload, '$.vp_sources_audit.bid') IN ('integer','real') THEN json_extract(payload, '$.vp_sources_audit.bid') END
 WHEN json_type(payload, '$.vp_sources.bid') IS NOT NULL THEN CASE WHEN json_type(payload, '$.vp_sources.bid') IN ('integer','real') THEN json_extract(payload, '$.vp_sources.bid') END
 WHEN json_extract(payload, '$.score_verified') = 1 AND json_type(payload, '$.vp_sources_raw') = 'object'
 AND NOT EXISTS (SELECT 1 FROM json_each(json_extract(payload, '$.vp_sources_raw')) WHERE type NOT IN ('integer','real'))
 AND (SELECT SUM(value) FROM json_each(json_extract(payload, '$.vp_sources_raw'))) = COALESCE(json_extract(payload, '$.reported_score'), json_extract(payload, '$.score')) THEN 0
 WHEN json_extract(payload, '$.vp_ledger_complete') = 1 THEN 0
 WHEN json_type(payload, '$.vp_ledger_complete') IS NULL AND json_extract(payload, '$.ruleset') = 'lost-fleet' AND json_extract(payload, '$.score_verified') = 1 THEN 0 END"""
BASE_SCORE_SQL = f"""CASE
 WHEN json_extract(payload, '$.ruleset') = 'base' AND json_type(payload, '$.vp_sources_raw') IS NULL AND json_type(payload, '$.bid_cost') IS NULL AND COALESCE(json_extract(payload, '$.score_basis_version'), '') != '{SCORE_BASIS_VERSION}' THEN NULL
 WHEN json_extract(payload, '$.score_basis_version') = '{SCORE_BASIS_VERSION}' THEN CASE WHEN json_type(payload, '$.score') IN ('integer','real') THEN json_extract(payload, '$.score') END
 WHEN json_type(payload, '$.reported_score') IN ('integer','real') THEN json_extract(payload, '$.reported_score') - ({_BID_SQL})
 WHEN json_type(payload, '$.reported_score') IS NULL AND json_type(payload, '$.score') IN ('integer','real') THEN json_extract(payload, '$.score') - ({_BID_SQL}) END"""
