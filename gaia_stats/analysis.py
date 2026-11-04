"""Normalize BGS exports without a hardcoded catalogue of tiles or VP sources."""
from collections import Counter, defaultdict
from statistics import mean
import math
import re

from .scoring import phase_views, BASE_SOURCES, NORMALIZATION_VERSION

from .eligibility import eligible_rows, faction_variant

RULESETS = ("base", "lost-fleet")


def ruleset(game):
    """Fail closed on conflicting markers and unrecognized expansions."""
    expansions = game.get("game", {}).get("expansions", [])
    if not isinstance(expansions, list) or set(expansions) - {"lost-fleet"}:
        raise ValueError("Unsupported expansion configuration")
    flags = [options["lostFleet"] for options in (
        game.get("game", {}).get("options", {}),
        game.get("data", {}).get("options", {}),
    ) if "lostFleet" in options]
    if any(type(flag) is not bool for flag in flags):
        raise ValueError("Invalid lostFleet flag")
    if len(set(flags)) > 1 or ("lost-fleet" in expansions and False in flags):
        raise ValueError("Conflicting Lost Fleet markers")
    if game.get("data", {}).get("expansions", 0) and not (True in flags or expansions):
        raise ValueError("Unidentified legacy expansion")
    return "lost-fleet" if True in flags or "lost-fleet" in expansions else "base"


QIC_MODES = ('standard-only', 'include-both', 'variant-only')


def lost_fleet_qic_option(game):
    """Retain observed metadata separately from BGS's documented false default."""
    observed = {source: options['lostFleet2pQicTech'] for source, options in (
        ('game.options', game.get('game', {}).get('options', {})),
        ('data.options', game.get('data', {}).get('options', {})))
        if 'lostFleet2pQicTech' in options}
    values = list(observed.values())
    if any(type(value) is not bool for value in values):
        raise ValueError('Invalid lostFleet2pQicTech flag')
    if len(set(values)) > 1:
        raise ValueError('Conflicting lostFleet2pQicTech flags')
    return (values[0] if values else None), observed


def qic_mode(filters):
    mode = filters.get('lf_2p_4qic_mode', 'standard-only')
    if mode not in QIC_MODES:
        raise ValueError('Choose standard-only, include-both or variant-only for LF 4-QIC')
    return mode


def variant_included(row, filters):
    mode = qic_mode(filters)
    if row['ruleset'] != 'lost-fleet':
        return True  # Original base behavior is unaffected.
    variant = row['player_count'] == 2 and row.get('lf_2p_4qic_effective', False) is True
    return mode == 'include-both' or (variant if mode == 'variant-only' else not variant)


def normalize(game):
    if game.get("status") != "ended" or game.get("cancelled"):
        raise ValueError("Game is not a completed, uncancelled game")
    version = ruleset(game)
    qic_observed, qic_sources = lost_fleet_qic_option(game)
    data = game["data"]
    players = game["players"]
    if qic_observed is True and (version != "lost-fleet" or len(players) != 2):
        raise ValueError("lostFleet2pQicTech is only valid for two-player Lost Fleet")
    states = data["players"]
    if len(players) < 2 or any(p.get("isAutoma") for p in states):
        raise ValueError("Solo and Automa games are excluded")
    if any(p.get("dropped") or p.get("quit") for p in players):
        raise ValueError("Game has a dropped or withdrawn player")
    if len(states) != len(players):
        raise ValueError("Player state count mismatch")
    variant, variant_metadata = faction_variant(game)
    options = {**game.get("game", {}).get("options", {}), **data.get("options", {})}
    tiles = data["tiles"]
    round_tiles = tiles["scorings"]["round"]
    if len(round_tiles) != 6:
        raise ValueError("Expected six round scoring tiles")
    opening = defaultdict(list)
    raw_opening = defaultdict(list)
    vp = defaultdict(Counter)
    seen_moves = set()
    rounds_seen = set()
    current_round = 0
    # Keep source IDs verbatim: expansion scoring must not disappear into base categories.
    for log in data["advancedLog"]:
        if "round" in log:
            current_round = log["round"]
            rounds_seen.add(current_round)
        if log.get("phase") == "endGame":
            current_round = 7
        pos = log.get("player")
        if pos is None:
            continue
        if type(pos) is not int or not 0 <= pos < len(players):
            raise ValueError("Invalid log player")
        for source, changes in log.get("changes", {}).items():
            if "vp" in changes:
                vp[pos][source] += changes["vp"]
        move_id = log.get("move")
        if current_round == 1 and move_id is not None and move_id not in seen_moves:
            seen_moves.add(move_id)
            move = data["moveHistory"][move_id]
            # Do not count passive charging or setup mines as opening actions.
            prefix = players[pos]["faction"] + " "
            if move.startswith(prefix) and not move[len(prefix):].startswith(("charge ", "decline ")):
                raw_opening[pos].append(move)
                opening[pos].extend(re.findall(r"\bbuild\s+(\w+)", move))
    if rounds_seen != set(range(1, 7)):
        raise ValueError("Incomplete round log")
    canonical, tile_scores, scoring_errors, ended = phase_views(data, len(players))
    rows = []
    scores = [p["score"] for p in players]
    top_count = scores.count(max(scores))
    for pos, player in enumerate(players):
        state = states[pos]
        if state["faction"] != player["faction"]:
            raise ValueError("Player and state faction order differ")
        # BGS logs omit the standard initial 10 VP; verify against the actual final score.
        sources = dict(vp[pos])
        sources["initial"] = 10
        delta = player["score"] - sum(sources.values())
        complete = ended and delta == 0
        raw_sources = sources
        if version == 'base':
            sources = dict(canonical[pos])
            if complete:
                for key in BASE_SOURCES:sources.setdefault(key, 0)
            if sum(sources.values()) != sum(raw_sources.values()):
                raise ValueError('Canonical VP categories do not reconcile to raw ledger')
        elo = player.get("elo", {}).get("initial")
        opponents = [p.get("elo", {}).get("initial") for i, p in enumerate(players) if i != pos]
        rows.append({
            "game_id": game.get("slug") or game.get("_id"), "ruleset": version,
            "lf_2p_4qic_observed": qic_observed,
            "lf_2p_4qic_effective": qic_observed if qic_observed is not None else False,
            "lf_2p_4qic_sources": qic_sources,
            "faction": player["faction"], "player_count": len(players),
            "opponents": sorted(p["faction"] for i, p in enumerate(players) if i != pos),
            "score": player["score"], "rank": 1 + sum(s > player["score"] for s in scores),
            "win_share": 1 / top_count if player["score"] == max(scores) else 0,
            "bid": state["data"].get("bid"), "elo": elo,
            "table_elo": mean(p["elo"]["initial"] for p in players)
            if all(p.get("elo", {}).get("initial") is not None for p in players) else None,
            "opponent_elo": mean(opponents) if all(x is not None for x in opponents) else None,
            "round_scorings": round_tiles, "final_scorings": tiles["scorings"]["final"],
            "technologies": {slot: tile["tile"] for slot, tile in tiles["techs"].items()},
            "ship_technologies": tiles.get("spaceshipTechs", {}),
            "boosters": sorted(tiles["boosters"]),
            "layout": options.get("layout", "standard"),
            "auction": options.get("auction", "none"),
            "faction_variant": variant,
            "faction_variant_sources": variant_metadata,
            "faction_variant_version": options.get("factionVariantVersion", 0),
            "official_center_sectors": options.get("officialCenterSectors", False),
            "map": options.get("map"),
            "build_order": " → ".join(opening[pos]) or "No round-one builds",
            "opening_moves": raw_opening[pos], "vp_sources": sources,
            "vp_sources_raw": raw_sources, "vp_ledger_complete": complete,
            "normalization_version": NORMALIZATION_VERSION,
            "vp_source_basis": "historical-base-categories" if version == "base" else "raw-bgs-sources",
            "scoring_vp": tile_scores[pos] if complete and scoring_errors[pos] is None else None,
            "scoring_vp_unavailable": scoring_errors[pos] or (None if complete else "Final scoring phase is not verified"),
            "score_delta": delta, "score_verified": delta == 0,
            "exploration_ships": state["data"].get("explorationShips", {}),
            "artifacts": state["data"].get("artifacts", []),
        })
    return rows


def skill_context(rows, filters):
    """Compute strength thresholds before faction/tile filters to keep the cohort stable.

    The unit is a player-game observation's pregame Elo, not unique people or
    current ratings. Each player count has its own threshold within a ruleset.
    """
    rows = [row for row in eligible_rows(rows) if variant_included(row, filters)]
    mode = filters.get("skill", "custom" if filters.get("min_elo") else "all")
    if mode not in ("all", "top", "custom"):
        raise ValueError("Choose all, top, or custom player skill")
    if mode != "custom" and filters.get("min_elo"):
        raise ValueError("Player Elo cutoff requires custom skill mode")
    minimum = None
    if mode == "custom":
        try:
            minimum = float(filters.get("min_elo", ""))
        except ValueError:
            raise ValueError("Custom skill mode needs a numeric player Elo cutoff") from None
        if not math.isfinite(minimum):
            raise ValueError("Player Elo cutoff must be finite")
    thresholds, rated_counts = {}, {}
    counts = {r["player_count"] for r in rows if r["ruleset"] == filters.get("ruleset")}
    if filters.get("player_count"):
        counts = {int(filters["player_count"])}
    for count in sorted(counts):
        ratings = sorted(r["elo"] for r in rows
                         if r["ruleset"] == filters.get("ruleset") and r["score_verified"]
                         and r["player_count"] == count and r["elo"] is not None)
        rated_counts[count] = len(ratings)
        if mode == "top" and ratings:
            index = (len(ratings) - 1) * .9
            lower = math.floor(index)
            thresholds[count] = ratings[lower] + (ratings[math.ceil(index)] - ratings[lower]) * (index - lower)
        elif mode == "custom":
            thresholds[count] = minimum
    return {"mode": mode, "thresholds": thresholds, "rated_counts": rated_counts,
            "lf_2p_4qic_mode": qic_mode(filters),
            "basis": "Pregame Elo per player-game record; top 10% within each ruleset and player count. Ties included."}


def select(rows, filters):
    version = filters.get("ruleset")
    if version not in RULESETS:
        raise ValueError("Choose base or lost-fleet explicitly")
    rows = eligible_rows(rows)
    skill = skill_context(rows, filters)
    table_minimum = None
    if filters.get("min_table_elo"):
        table_minimum = float(filters["min_table_elo"])
        if not math.isfinite(table_minimum):
            raise ValueError("Table Elo cutoff must be finite")
    result = []
    for row in rows:
        if row["ruleset"] != version or not row["score_verified"] or not variant_included(row, filters):
            continue
        if any((str(row[key]).lower() if isinstance(row[key], bool) else str(row[key]))
               != str(filters[key]) for key in (
            "faction", "player_count", "layout", "auction", "faction_variant",
            "faction_variant_version", "official_center_sectors",
        ) if filters.get(key, "") != ""):
            continue
        if filters.get("opponent") and filters["opponent"] not in row["opponents"]:
            continue
        if filters.get("final_scoring") and filters["final_scoring"] not in row["final_scorings"]:
            continue
        if any(filters.get(f"round{i+1}") and filters[f"round{i+1}"] != tile
               for i, tile in enumerate(row["round_scorings"])):
            continue
        if filters.get("technology") and filters["technology"] not in row["technologies"].values():
            continue
        if skill["mode"] != "all" and (
            row["elo"] is None or row["player_count"] not in skill["thresholds"]
            or row["elo"] < skill["thresholds"][row["player_count"]]
        ):
            continue
        if table_minimum is not None and (row["table_elo"] is None or row["table_elo"] < table_minimum):
            continue
        result.append(row)
    return result


def summarize(rows, minimum=5):
    rows = eligible_rows(rows)
    groups = defaultdict(list)
    for row in rows:
        # Factions and setup variants remain separate even when viewing all factions.
        key = tuple(row[k] for k in ("ruleset", "faction", "player_count", "layout", "auction",
                                    "faction_variant", "faction_variant_version",
                                    "official_center_sectors", "build_order"))
        key += (row.get("lf_2p_4qic_effective", False),)
        groups[key].append(row)
    result = []
    for group in groups.values():
        first = group[0]
        result.append({
            **{k: first[k] for k in ("faction", "player_count", "layout", "auction",
                                    "faction_variant", "faction_variant_version",
                                    "official_center_sectors", "build_order")},
            "lf_2p_4qic_effective": first.get("lf_2p_4qic_effective", False),
            "samples": len(group), "games": len({r["game_id"] for r in group}),
            "average_score": mean(r["score"] for r in group),
            "win_share": mean(r["win_share"] for r in group),
            "average_elo": mean(r["elo"] for r in group if r["elo"] is not None)
            if any(r["elo"] is not None for r in group) else None,
            "enough_samples": len(group) >= minimum,
        })
    return sorted(result, key=lambda r: (-r["samples"], r["faction"], r["build_order"]))
