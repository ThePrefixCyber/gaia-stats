#!/usr/bin/env python3
"""Read-only deployment gate. Uses only the standard library and no app imports."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from itertools import zip_longest


def read_json(path):
    with Path(path).open() as handle:
        return json.load(handle)


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def lost_fleet_rows(path, root):
    """Read legacy rows or verify every immutable game object without app code."""
    path, root = Path(path), Path(root).resolve()
    data = read_json(path)
    require(isinstance(data, dict), 'Invalid Lost Fleet dataset')
    if data.get('storage') is None:
        require(data.get('schema_version', 1) == 1 and isinstance(data.get('rows'), list),
                'Unsupported Lost Fleet dataset')
        yield from data['rows']
        return
    require(data.get('schema_version') == 1 and data.get('storage') == 'content-addressed-games-v1',
            'Unsupported Lost Fleet storage')
    require(isinstance(data.get('games'), dict) and 'rows' not in data, 'Invalid LF object index')
    require(path.parent.parent.resolve() == root / 'releases', 'LF object index escapes its store')
    directory = root / 'objects' / 'lost-fleet'
    require(directory.resolve().is_relative_to(root), 'LF object directory escapes its store')
    for slug, sha in sorted(data['games'].items()):
        require(isinstance(slug, str) and bool(slug), 'Invalid LF game identity')
        require(isinstance(sha, str) and re.fullmatch(r'[a-f0-9]{64}', sha), 'Invalid LF object hash')
        target = directory / (sha + '.json')
        require(target.resolve().parent == directory.resolve(), 'LF object escapes its store')
        raw = target.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == sha, 'LF object hash mismatch: ' + slug)
        rows = json.loads(raw)
        require(isinstance(rows, list) and bool(rows) and
                all(isinstance(row, dict) and row.get('game_id') == slug for row in rows),
                'LF object identity mismatch: ' + slug)
        yield from rows


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identifiers(value):
    require(isinstance(value, list) and all(isinstance(x, str) and x for x in value), 'Invalid exclusion/index IDs')
    require(len(value) == len(set(value)), 'Duplicate exclusion/index IDs')
    return set(value)


def selected(root, pointer, field, prefix):
    name = read_json(root / pointer)[field]
    require(isinstance(name, str) and re.fullmatch(prefix + r'[A-Za-z0-9_-]+', name), 'Unsafe data pointer')
    parent = root / ('releases' if field == 'release' else '')
    target = parent / name
    require(target.resolve().parent == parent.resolve(), 'Data pointer escapes its store')
    require(target.is_dir(), 'Selected data generation is missing')
    return target


def metadata(db):
    return dict(db.execute('SELECT key,value FROM metadata'))


def markers(value, contract, label):
    require(str(value.get('eligibility_policy')) == str(contract['eligibility_policy']), label + ': eligibility policy is not ready')
    require(value.get('score_basis_version') == contract['score_basis_version'], label + ': score basis is not ready')


def check_rows(rows, contract, mode, blocked, label):
    # SQLite callers provide complete games in ID order. Retain one table, not
    # the full historical database, while still checking every rank and win.
    seen_games, group = set(), []
    records = 0

    def finish_group():
        if not group:
            return
        game = group[0]['game_id']
        require(game not in seen_games, label + ': repeated/noncontiguous game')
        seen_games.add(game)
        count = group[0]['player_count']
        require(len(group) == count and all(row['player_count'] == count for row in group), label + ': incomplete game ' + game)
        require(len({row['faction'] for row in group}) == count, label + ': duplicate player-game identity')
        scores = [row['score'] for row in group]
        top, ties = max(scores), scores.count(max(scores))
        for row in group:
            rank = 1 + sum(score > row['score'] for score in scores)
            win = 1 / ties if row['score'] == top else 0
            require(type(row.get('rank')) is int and row['rank'] == rank, label + ': rank is not based on pre-bid score')
            require(finite(row.get('win_share')) and math.isclose(row['win_share'], win, rel_tol=0, abs_tol=1e-9), label + ': win credit is not based on pre-bid score')

    for row in rows:
        require(isinstance(row, dict), label + ': invalid observation')
        require(row.get('ruleset') == mode, label + ': mixed rulesets')
        require(row.get('score_basis_version') == contract['score_basis_version'], label + ': unmigrated observation')
        game, faction = row.get('game_id'), row.get('faction')
        require(isinstance(game, str) and game and isinstance(faction, str) and faction, label + ': missing identity')
        require(game not in blocked, label + ': contains an excluded game')
        require(type(row.get('player_count')) is int and row['player_count'] in (2, 3, 4), label + ': invalid player count')
        score, reported, delta = (row.get(key) for key in ('score', 'reported_score', 'bid_delta'))
        require(all(finite(value) for value in (score, reported, delta)), label + ': unknown/non-finite score or auction contribution')
        require(math.isclose(score, reported - delta, rel_tol=0, abs_tol=1e-9), label + ': pre-bid score does not reconcile')
        require(score >= contract['minimum_score'], label + ': score is below the whole-game floor')
        require(row.get('faction_variant') != 'more-balanced' and 'more-balanced' not in (row.get('faction_variant_sources') or {}).values(), label + ': excluded faction variant')
        require('bid' not in (row.get('vp_sources') or {}), label + ': auction contribution remains in analytical VP sources')
        if group and group[0]['game_id'] != game:
            finish_group()
            group = []
        group.append(row)
        records += 1
    finish_group()
    return {'games': len(seen_games), 'records': records}


def check_sqlite(path, contract, blocked, label):
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', label + ': SQLite integrity failure')
        markers(metadata(db), contract, label)
        return check_rows((json.loads(row[0]) for row in db.execute('SELECT payload FROM observations ORDER BY game_id,faction')),
                          contract, 'base', blocked, label)


def contract_value(path):
    value = read_json(path)
    require(isinstance(value, dict) and type(value.get('schema_version')) is int and
            value['schema_version'] in (1,2), 'Unsupported deployment contract')
    require(type(value.get('eligibility_policy')) is int and value['eligibility_policy'] > 0, 'Invalid eligibility requirement')
    require(isinstance(value.get('score_basis_version'), str) and value['score_basis_version'], 'Invalid score-basis requirement')
    require(type(value.get('normalization_version')) is int and value['normalization_version'] > 0, 'Invalid normalization requirement')
    require(finite(value.get('minimum_score', 100)), 'Invalid score floor')
    if value['schema_version']==2:
        require(value.get('base_source_policy')=='original-csv-only-v1', 'Unsupported base source contract')
        require(value.get('lf_storage')=='content-addressed-games-v1', 'Unsupported LF storage contract')
    return dict(value, minimum_score=value.get('minimum_score', 100))


def bundle_paths(path):
    # Match the worker's startup contract before the updater changes code.
    # The preparer validates explicit member paths before marking a bundle ready.
    bundle = Path(path).resolve(strict=True)
    require(read_json(bundle / 'preparation.json').get('state') == 'ready',
            'Selected data bundle has not passed migration preflight')
    members = (bundle / 'releases-store', bundle / 'seeds/base.sqlite', bundle / 'classic-cache')
    require(all(member.resolve().is_relative_to(bundle) for member in members),
            'Selected data bundle member escapes its bundle')
    return members


def check(contract_path, root, seed, cache):
    contract = contract_value(contract_path)
    root, seed, cache = Path(root).resolve(), Path(seed).resolve(), Path(cache).resolve()
    release = selected(root, 'current.json', 'release', 'release-')
    manifest = read_json(release / 'manifest.json')
    require(manifest.get('schema_version') == 1, 'Unsupported release schema')
    markers(manifest, contract, 'Release manifest')
    require(manifest.get('inputs', {}).get('normalization_version') == contract['normalization_version'], 'Release normalization is not ready')
    require(manifest.get('release') == release.name, 'Release manifest identity mismatch')
    registry = read_json(root / 'exclusions.json')
    require(registry.get('eligibility_policy') == contract['eligibility_policy'], 'Exclusion registry policy is not ready')
    blocked = identifiers(registry.get('game_ids'))
    release_blocked = identifiers(manifest.get('excluded_game_ids', []))
    require(blocked <= release_blocked, 'Release lacks current exclusion evidence')
    blocked |= release_blocked
    for name in ('base.sqlite', 'lost-fleet.json'):
        require(digest(release / name) == manifest.get('sha256', {}).get(name), 'Release hash mismatch: ' + name)
    # A raw-excluded game can still exist in the immutable CSV seed. Validate its
    # own score/variant policy, but the serving release and cache must omit it.
    require(digest(seed) == manifest.get('inputs', {}).get('seed'), 'Selected seed hash does not match release inputs')
    seed_counts = check_sqlite(seed, contract, set(), 'Seed')
    with sqlite3.connect(seed.as_uri() + '?mode=ro', uri=True) as db:
        imports = json.loads(metadata(db).get('imports', '{}'))
        seed_games = {}
        for game_id, players in db.execute("SELECT DISTINCT game_id,json_extract(payload,'$.player_count') FROM observations"):
            if game_id not in blocked:
                seed_games.setdefault(str(players), set()).add(game_id)
    require(isinstance(imports, dict) and bool(imports) and all(key in ('2', '3', '4') for key in imports), 'Seed source-player-count provenance is missing')
    require(set(seed_games) <= set(imports), 'Seed source-player-count provenance omits observed games')
    base_counts = check_sqlite(release / 'base.sqlite', contract, blocked, 'Base release')
    if contract['schema_version']==2:
        require(manifest.get('base_source_policy')==contract['base_source_policy'], 'Base source policy is not ready')
        require(read_json(release/'lost-fleet.json').get('storage')==contract['lf_storage'], 'LF storage is not ready')
        with sqlite3.connect(seed.as_uri()+'?mode=ro',uri=True) as source, \
             sqlite3.connect((release/'base.sqlite').as_uri()+'?mode=ro',uri=True) as serving:
            require(metadata(serving).get('base_source_policy')==contract['base_source_policy'], 'Base source metadata is not ready')
            sql='SELECT game_id,faction,payload FROM observations ORDER BY game_id,faction'
            expected=(row for row in source.execute(sql) if row[0] not in blocked)
            require(all(left==right for left,right in zip_longest(expected,serving.execute(sql))),
                    'Base release does not exactly match the original CSV seed minus verified exclusions')
    lf_counts = check_rows(lost_fleet_rows(release / 'lost-fleet.json', root),
                           contract, 'lost-fleet', blocked, 'Lost Fleet release')
    counts = {'base': base_counts, 'lost-fleet': lf_counts}
    require(counts == manifest.get('datasets'), 'Manifest counts do not match checked observations')
    for mode, count in counts.items():
        require(count['records'] or mode in manifest.get('empty_after_exclusion', []), 'Unexpected empty mode')
    build = selected(cache, 'current.json', 'build', 'build-')
    catalogue = read_json(build / 'manifest.json')
    require(catalogue.get('schema_version') == 1, 'Unsupported classic cache schema')
    markers(catalogue, contract, 'Classic cache')
    require(set(catalogue.get('datasets', {})) == set(imports), 'Classic cache omits or changes seed source player counts')
    index = read_json(build / 'eligible-games.json')
    require(index.get('complete') is True, 'Classic cache has incomplete game provenance')
    cached_ids = identifiers(index.get('game_ids'))
    require(not cached_ids & blocked, 'Classic cache contains newly excluded games')
    asset = build / 'plotly.min.js'
    require(asset.is_file() and asset.stat().st_size >= 100000, 'Missing/incomplete Plotly asset')
    observed_ids = set()
    require(bool(catalogue.get('datasets')), 'Missing classic datasets')
    for players, summary in catalogue['datasets'].items():
        require(players in ('2', '3', '4'), 'Unexpected classic player count')
        require(isinstance(imports[players], dict) and re.fullmatch(r'[a-f0-9]{64}', str(imports[players].get('sha256'))) is not None, 'Invalid seed source hash')
        require(summary.get('sha256') == imports[players]['sha256'], 'Classic cache source hash differs from rebuilt seed')
        count = 0
        downloaded_ids = set()
        with (build / 'data' / (players + '.csv')).open(newline='') as handle:
            for game in csv.DictReader(handle):
                require(game.get('id') in cached_ids and game.get('id') not in blocked, 'Classic CSV identity/exclusion mismatch')
                require(game.get('num_players') == players, 'Classic CSV player count mismatch')
                require(game['id'] not in observed_ids, 'Classic CSV repeats a game identity')
                require(all(game.get(f'pos_{p}_dropped') == 'False' for p in range(1, int(players)+1)),
                        'Classic CSV contains dropped or unknown-status players')
                require(game.get('balance_variant') != 'more-balanced', 'Classic CSV contains excluded faction variant')
                for position in range(1, int(players) + 1):
                    try:
                        reported = float(game[f'pos_{position}_score'])
                        bid = float(game[f'pos_{position}_bid'])
                    except (KeyError, TypeError, ValueError):
                        raise ValueError('Classic CSV missing aligned score/auction cost') from None
                    require(math.isfinite(reported) and math.isfinite(bid) and bid >= 0 and reported + bid >= contract['minimum_score'], 'Classic CSV has an ineligible or unknown pre-bid score')
                observed_ids.add(game['id']); downloaded_ids.add(game['id']); count += 1
        require(count == summary.get('games'), 'Classic CSV count mismatch')
        require(downloaded_ids == seed_games.get(players, set()),
                'Classic CSV games do not exactly match the original CSV seed minus verified exclusions')
        for faction, plots in summary.get('available', {}).items():
            require(re.fullmatch(r'[a-z0-9-]+', faction) is not None, 'Invalid cached faction')
            for plot in plots:
                require(isinstance(plot, str) and re.fullmatch(r'[a-z0-9-]+', plot), 'Invalid cached plot')
                chart = build / 'plots' / f'{players}-{faction}-{plot}.html'
                require(chart.is_file() and chart.stat().st_size > 0, 'Missing classic chart')
    require(observed_ids == cached_ids, 'Classic index does not match downloadable games')
    require(observed_ids == set().union(*seed_games.values()),
            'Classic downloads omit original CSV seed games')
    return {'release': release.name, 'cache': build.name, 'datasets': counts, 'seed': seed_counts,
            'eligibility_policy': contract['eligibility_policy'], 'score_basis_version': contract['score_basis_version']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', required=True)
    parser.add_argument('--bundle')
    parser.add_argument('--root', default=os.environ.get('GAIA_RELEASE_ROOT', '/var/lib/gaia-stats/releases-store'))
    parser.add_argument('--seed', default=os.environ.get('GAIA_SEED_BASE', '/var/lib/gaia-stats/seeds/base.sqlite'))
    parser.add_argument('--cache', default=os.environ.get('GAIA_CLASSIC_CACHE', '/var/lib/gaia-stats/classic-cache'))
    args = parser.parse_args()
    if args.bundle:
        root, seed, cache = bundle_paths(args.bundle)
    else:
        root, seed, cache = args.root, args.seed, args.cache
    print(json.dumps(check(args.contract, root, seed, cache), sort_keys=True))


if __name__ == '__main__':
    main()
