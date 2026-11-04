"""Immutable two-ruleset releases, switched by one atomic pointer; no live seeding."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from contextlib import contextmanager
import fcntl

from .__main__ import atomic_json
from .analysis import normalize
from .cohort import enrich
from .scoring import NORMALIZATION_VERSION
from .score_basis import SCORE_BASIS_VERSION, analysis_rows
from .identifiers import valid_slug
from .eligibility import (BASE_ELIGIBLE_SQL, POLICY_VERSION, eligible_rows,
                          excluded_export, excluded_ids, stored_exclusions, SUPPORTED_POLICY_VERSIONS, require_safe_policy)


def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def digest(path):
    checksum=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):checksum.update(chunk)
    return checksum.hexdigest()


@contextmanager
def release_lock(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    with (root/'refresh.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another data refresh is running') from None
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def current(root):
    root=Path(root)
    pointer=root/'current.json'
    if not pointer.exists():return None
    name=json.loads(pointer.read_text())['release']
    if not re.fullmatch(r'release-[a-zA-Z0-9_-]+',name):raise ValueError('Invalid release pointer')
    path=root/'releases'/name
    if path.resolve().parent!=(root/'releases').resolve():raise ValueError('Release escapes root')
    return path


def known_exclusions(root):
    """Monotonic exclusion evidence survives an immutable-release rollback."""
    path = Path(root) / 'exclusions.json'
    if not path.exists():
        return set()
    payload = json.loads(path.read_text())
    require_safe_policy(payload.get('eligibility_policy'))
    ids = payload.get('game_ids')
    if payload.get('eligibility_policy') not in SUPPORTED_POLICY_VERSIONS:
        raise ValueError('Invalid game-exclusion registry')
    return stored_exclusions(ids)


def verified_export(archive, mode, slug, sha, status):
    if not valid_slug(slug):raise ValueError('Unsafe archive identifier')
    path = Path(archive)/mode/'raw'/(slug+'.json')
    if digest(path) != sha:raise ValueError('Archive hash mismatch: '+slug)
    try:payload=json.loads(path.read_text())
    except ValueError:
        if status == 'rejected':return None
        raise
    if not isinstance(payload, dict) or payload.get('slug') != slug:
        if status == 'rejected':return None
        raise ValueError('Archive identity mismatch: '+slug)
    return payload


def accepted_exports(archive,mode):
    archive=Path(archive)
    if not (archive/'archive.sqlite3').exists():return
    with sqlite3.connect((archive/'archive.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        for slug,sha,status in db.execute('SELECT slug,sha256,status FROM exports WHERE mode=? AND (status IN ("accepted","excluded") OR (status="rejected" AND sha256 IS NOT NULL)) ORDER BY slug',(mode,)):
            payload = verified_export(archive,mode,slug,sha,status)
            if payload is None:continue
            # An empty row list is an explicit policy exclusion, not a failed import.
            # Previously accepted raw exports are rechecked without downloading/deleting them.
            if excluded_export(payload):
                yield slug,[]
                continue
            if status == 'rejected':continue  # Exclusion evidence only; never admit rejected rows.
            rows=enrich(payload,normalize(payload))
            if payload.get('slug')!=slug or len(rows) not in (2,3,4) or any(r['ruleset']!=mode or not r['score_verified'] for r in rows):
                raise ValueError('Accepted archive validation failed: '+slug)
            yield slug,rows


def insert_game(db,slug,rows,replace=False):
    if not rows or any(r['game_id']!=slug or r['ruleset']!='base' for r in rows):raise ValueError('Base mode isolation failed')
    if excluded_ids(rows):
        db.execute('DELETE FROM observations WHERE game_id=?',(slug,))
        return
    if not replace and db.execute('SELECT 1 FROM observations WHERE game_id=?',(slug,)).fetchone():return
    if replace:db.execute('DELETE FROM observations WHERE game_id=?',(slug,))
    for row in rows:
        db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)',tuple(row.get(k,'unknown') for k in ('game_id','faction','player_count','elo','layout','auction','faction_variant'))+(json.dumps(row,separators=(',',':')),))


def refreshed_seed_games(path):
    """Only a newly rebuilt seed can repair old CSV player/source alignment.

    Read complete games in bounded groups. An old seed is retained as evidence,
    but its misaligned bid columns must never be relabelled as corrected scores.
    """
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        marker = db.execute("SELECT value FROM metadata WHERE key='score_basis_version'").fetchone()
        if not marker or marker[0] != SCORE_BASIS_VERSION:
            return
        group = []
        for (payload,) in db.execute('SELECT payload FROM observations ORDER BY game_id,faction'):
            row = json.loads(payload)
            if row.get('score_basis_version') != SCORE_BASIS_VERSION or row.get('ruleset') != 'base':
                raise ValueError('Rebuilt seed contains inconsistent score provenance')
            if group and row['game_id'] != group[0]['game_id']:
                yield group[0]['game_id'], group
                group = []
            group.append(row)
        if group:
            yield group[0]['game_id'], group


def overlay_refreshed_seed(db, seed, excluded):
    """Repair preserved historical rows without downgrading raw-ledger evidence."""
    for slug, rows in refreshed_seed_games(seed):
        if slug in excluded:
            continue
        if len(rows) != rows[0].get('player_count'):
            raise ValueError('Rebuilt seed has incomplete player-game rows')
        existing = [json.loads(value[0]) for value in db.execute(
            'SELECT payload FROM observations WHERE game_id=?', (slug,))]
        if any('vp_sources_raw' in row or row.get('normalization_version') is not None for row in existing):
            continue  # Preserve richer raw results even if their archive is offline.
        insert_game(db, slug, rows, replace=True)


def base_ids(path,eligible=False):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        return set(db.execute('SELECT game_id,faction FROM observations'+(' WHERE '+BASE_ELIGIBLE_SQL if eligible else '')))


def validate(path,previous=None,*,allowed_exclusions=(),known_exclusions=()):
    path=Path(path);manifest=json.loads((path/'manifest.json').read_text())
    require_safe_policy(manifest.get('eligibility_policy'))
    for filename in ('base.sqlite','lost-fleet.json'):
        if digest(path/filename)!=manifest['sha256'][filename]:raise ValueError('Release file hash mismatch')
    with sqlite3.connect((path/'base.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity failure')
        base_games,base_records=db.execute('SELECT COUNT(DISTINCT game_id),COUNT(*) FROM observations').fetchone()
        for (payload,) in db.execute('SELECT payload FROM observations'):
            if json.loads(payload)['ruleset']!='base':raise ValueError('Mixed base database')
    lf=json.loads((path/'lost-fleet.json').read_text())['rows']
    lf_ids={(r['game_id'],r['faction']) for r in lf}
    if len(lf_ids)!=len(lf) or any(r['ruleset']!='lost-fleet' or not r['score_verified'] for r in lf):raise ValueError('Invalid LF release rows')
    counts={'base':{'games':base_games,'records':base_records},'lost-fleet':{'games':len({x[0] for x in lf_ids}),'records':len(lf)}}
    if counts!=manifest['datasets']:raise ValueError('Manifest counts mismatch')
    policy=manifest.get('eligibility_policy')
    blocked = set(known_exclusions) | stored_exclusions(manifest.get('excluded_game_ids', []))
    if blocked:
        visible_ids = {r['game_id'] for r in eligible_rows(lf)} | {x[0] for x in base_ids(path/'base.sqlite', eligible=True)}
        if visible_ids & blocked:
            raise ValueError('Release contains games excluded by verified source evidence; rebuild before serving or rollback')
    if policy==POLICY_VERSION:
        if len(eligible_rows(lf))!=len(lf) or len(base_ids(path/'base.sqlite',eligible=True))!=base_records:
            raise ValueError('Excluded game in published release')
    if previous:
        old_lf=json.loads((previous/'lost-fleet.json').read_text())['rows']
        allowed=set(allowed_exclusions)
        required_lf={(r['game_id'],r['faction']) for r in eligible_rows(old_lf) if r['game_id'] not in allowed}
        required_base={identity for identity in base_ids(previous/'base.sqlite',eligible=True) if identity[0] not in allowed}
        if not required_lf<=lf_ids or not required_base<=base_ids(path/'base.sqlite'):
            raise ValueError('Publication would lose existing player-game records')
    empty = {mode for mode, counts in counts.items() if not counts['records']}
    if empty and (policy not in SUPPORTED_POLICY_VERSIONS or not empty <= set(manifest.get('empty_after_exclusion', []))):
        raise ValueError('Both release datasets must be nonempty unless verified exclusions removed every game')
    # Old immutable releases may still include excluded rows. Their query paths
    # filter immediately; report the same eligible counts during migration/rollback.
    if policy!=POLICY_VERSION:
        ids=base_ids(path/'base.sqlite',eligible=True);visible=eligible_rows(lf)
        manifest['datasets']={'base':{'games':len({x[0] for x in ids}),'records':len(ids)},
            'lost-fleet':{'games':len({r['game_id'] for r in visible}),'records':len(visible)}}
    return manifest


def source_identity(seed_base,archive,legacy):
    entries=[]; database=Path(archive)/'archive.sqlite3'
    if database.exists():
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            for mode,slug,sha,status in db.execute('SELECT mode,slug,sha256,status FROM exports WHERE status IN ("accepted","excluded") OR (status="rejected" AND sha256 IS NOT NULL) ORDER BY mode,slug'):
                if status == 'rejected' and not excluded_export(verified_export(archive,mode,slug,sha,status)):
                    continue
                entries.append((mode,slug,sha,status))
    return {'eligibility_policy':POLICY_VERSION,'score_basis_version':SCORE_BASIS_VERSION,'normalization_version':NORMALIZATION_VERSION,'seed':digest(seed_base),'legacy':digest(legacy) if legacy else None,
            'accepted':hashlib.sha256(json.dumps(entries).encode()).hexdigest()}


def publish(root,seed_base,archive,legacy=None,*,dry_run=False):
    """Caller holds refresh.lock. No prior releases or legacy files are removed."""
    root=Path(root);previous=current(root)
    prior=validate(previous) if previous else None
    known = known_exclusions(root)
    inputs=source_identity(seed_base,archive,legacy)
    if prior and prior.get("inputs")==inputs and known <= stored_exclusions(prior.get('excluded_game_ids', [])):return prior
    source=previous/"base.sqlite" if previous else Path(seed_base)
    if shutil.disk_usage(root).free < max(512*1024*1024,source.stat().st_size*2):
        raise ValueError("Insufficient free space for a safe release; retain current data and review old generated releases")
    (root/'releases').mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='release-',dir=root/'releases'))
    try:
        shutil.copyfile(previous/'base.sqlite' if previous else seed_base,stage/'base.sqlite')
        lf={}
        if previous:
            for row in json.loads((previous/'lost-fleet.json').read_text())['rows']:lf.setdefault(row['game_id'],[]).append(row)
        legacy_groups=defaultdict(list)
        legacy_exclusions = set()
        if legacy:
            legacy_data = json.loads(Path(legacy).read_text())
            require_safe_policy(legacy_data.get('eligibility_policy'))
            legacy_exclusions.update(stored_exclusions(legacy_data.get('excluded_game_ids', [])))
            legacy_exclusions.update(excluded_ids(legacy_data['rows']))
            for row in legacy_data['rows']:
                if row['game_id'] in legacy_exclusions:continue
                if row.get('ruleset') not in ('base','lost-fleet') or not row.get('score_verified'):raise ValueError('Invalid legacy records')
                legacy_groups[(row['ruleset'],row['game_id'])].append(row)
        raw_counts={}
        excluded=known | legacy_exclusions | stored_exclusions(prior.get('excluded_game_ids', []) if prior else [])
        # Current seed evidence can change even when the staged data preserves the
        # previous release, so read the actual source separately and read-only.
        with sqlite3.connect(Path(seed_base).resolve().as_uri()+'?mode=ro',uri=True) as seed_db:
            seed_policy = seed_db.execute("SELECT value FROM metadata WHERE key='eligibility_policy'").fetchone()
            require_safe_policy(seed_policy[0] if seed_policy else None)
            seed_exclusions = seed_db.execute("SELECT value FROM metadata WHERE key='excluded_game_ids'").fetchone()
            if seed_exclusions:excluded.update(stored_exclusions(json.loads(seed_exclusions[0])))
            excluded.update(row[0] for row in seed_db.execute('SELECT DISTINCT game_id FROM observations WHERE NOT ('+BASE_ELIGIBLE_SQL+')'))
        with sqlite3.connect(stage/'base.sqlite') as db:
            excluded.update(row[0] for row in db.execute('SELECT DISTINCT game_id FROM observations WHERE NOT ('+BASE_ELIGIBLE_SQL+')'))
            for rows in lf.values():excluded.update(excluded_ids(rows))
            for rows in legacy_groups.values():excluded.update(excluded_ids(rows))
            overlay_refreshed_seed(db, seed_base, excluded)
            for (mode,slug),rows in legacy_groups.items():
                if slug in excluded:continue
                if mode=='base':insert_game(db,slug,rows)
                elif slug not in lf:lf[slug]=rows
            for mode in ('base','lost-fleet'):
                raw_counts[mode]=0
                for slug,rows in accepted_exports(archive,mode):
                    if not rows:
                        excluded.add(slug)
                        continue
                    raw_counts[mode]+=1
                    if mode=='base':insert_game(db,slug,rows,replace=True)
                    else:lf[slug]=rows
            # This only edits the new release copy. Seed, archive, legacy inputs
            # and every prior release remain available for recovery.
            prior_base_ids = {r[0] for r in db.execute('SELECT DISTINCT game_id FROM observations')}
            empty_after_exclusion = [mode for mode, ids in (('base', prior_base_ids), ('lost-fleet', set(lf)))
                                     if (ids and ids <= excluded) or
                                     (not ids and prior and mode in prior.get('empty_after_exclusion', []))]
            db.executemany('DELETE FROM observations WHERE game_id=?',((slug,) for slug in excluded))
            for slug in excluded:lf.pop(slug,None)
            # Restore scores/ranks of preserved raw snapshots even when their
            # archive is unavailable. Historical rows still need a rebuilt seed;
            # unknown provenance is retained and fails the activation preflight.
            pending = []
            def normalize_group(group):
                for row in analysis_rows(group):
                    db.execute('UPDATE observations SET payload=? WHERE game_id=? AND faction=?',
                               (json.dumps(row,separators=(',',':')),row['game_id'],row['faction']))
            for (payload,) in db.execute('SELECT payload FROM observations ORDER BY game_id,faction'):
                row=json.loads(payload)
                if pending and pending[0]['game_id'] != row['game_id']:
                    normalize_group(pending);pending=[]
                pending.append(row)
            if pending:normalize_group(pending)
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('score_basis_version',SCORE_BASIS_VERSION))
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('eligibility_policy',str(POLICY_VERSION)))
            # Rebuild catalogue from this exact merged release, not stale historical options.
            catalog={k:set() for k in ('faction','layout','auction','faction_variant','round_scorings','final_scorings','advanced_technologies')}
            for (payload,) in db.execute('SELECT payload FROM observations'):
                row=json.loads(payload)
                for k in ('faction','layout','auction','faction_variant'):catalog[k].add(str(row[k]))
                for k in ('round_scorings','final_scorings'):catalog[k].update(row[k])
                catalog['advanced_technologies'].update(v for k,v in row['technologies'].items() if k.startswith('adv-'))
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('catalog',json.dumps({k:sorted(v) for k,v in catalog.items()})))
            bg,br=db.execute('SELECT COUNT(DISTINCT game_id),COUNT(*) FROM observations').fetchone()
        rows=[row for slug in sorted(lf) for row in analysis_rows(lf[slug])]
        atomic_json(stage/'lost-fleet.json',{'schema_version':1,'rows':rows,'scope':'Public LF archive plus preserved prior records; see health for refresh coverage and freshness'})
        manifest={'inputs':inputs,'schema_version':1,'score_basis_version':SCORE_BASIS_VERSION,'eligibility_policy':POLICY_VERSION,'excluded_games':len(excluded),
                  'excluded_game_ids':sorted(excluded),'empty_after_exclusion':empty_after_exclusion,
                  'created_at':utc(),'release':stage.name,'previous':previous.name if previous else None,
                  'datasets':{'base':{'games':bg,'records':br},'lost-fleet':{'games':len(lf),'records':len(rows)}},
                  'raw_accepted_games':raw_counts,'coverage':'Historical base CSV seed plus accepted raw exports; raw backfill may be incomplete. Overlapping game IDs are replaced, never added twice.',
                  'sha256':{name:digest(stage/name) for name in ('base.sqlite','lost-fleet.json')}}
        atomic_json(stage/'manifest.json',manifest)
        validate(stage,previous,allowed_exclusions=excluded)
        # Preserve all legacy identities even when the very first release has no predecessor.
        for (mode,slug),old in legacy_groups.items():
            if slug in excluded:continue
            ids={(r['game_id'],r['faction']) for r in old}
            available=base_ids(stage/'base.sqlite') if mode=='base' else {(r['game_id'],r['faction']) for r in rows}
            if not ids<=available:raise ValueError('Legacy record preservation failed')
        if not dry_run:
            # Persist evidence first: an interrupted swap may make the old release
            # temporarily unavailable, but cannot expose newly excluded games.
            atomic_json(root/'exclusions.json',{'eligibility_policy':POLICY_VERSION,'game_ids':sorted(excluded)})
            atomic_json(root/'current.json',{'release':stage.name})
        return manifest
    except BaseException:
        # The atomic swap may have completed immediately before an interruption.
        # If its outcome cannot be read, retain the candidate rather than risk a
        # dangling live pointer. Unreferenced candidates can be inspected later.
        try: published = current(root) == stage
        except BaseException: published = True
        if not published:shutil.rmtree(stage)
        raise


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--seed-base',required=True);parser.add_argument('--archive',required=True);parser.add_argument('--legacy');parser.add_argument('--dry-run',action='store_true');parser.add_argument('--rollback')
    args=parser.parse_args()
    with release_lock(args.root):
        if args.rollback:
            if not re.fullmatch(r'release-[a-zA-Z0-9_-]+',args.rollback):raise ValueError('Invalid rollback release')
            path=Path(args.root)/'releases'/args.rollback;validate(path,known_exclusions=known_exclusions(args.root))
            if not args.dry_run:atomic_json(Path(args.root)/'current.json',{'release':args.rollback})
            print(json.dumps({'rollback':args.rollback,'dry_run':args.dry_run}))
        else:print(json.dumps(publish(args.root,args.seed_base,args.archive,args.legacy,dry_run=args.dry_run),indent=2))

if __name__=='__main__':main()
