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
from .release_data import load_dataset, write_dataset, encoded
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


def accepted_exports(archive,mode,*,unchanged=None):
    archive=Path(archive)
    if not (archive/'archive.sqlite3').exists():return
    with sqlite3.connect((archive/'archive.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        for slug,sha,status in db.execute('SELECT slug,sha256,status FROM exports WHERE mode=? AND (status IN ("accepted","excluded") OR (status="rejected" AND sha256 IS NOT NULL)) ORDER BY slug',(mode,)):
            if unchanged and unchanged.get(slug) == [sha, status]:continue
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


def validate(path,previous=None,*,allowed_exclusions=(),known_exclusions=(),allow_static_base_migration=False):
    path=Path(path);manifest=json.loads((path/'manifest.json').read_text())
    require_safe_policy(manifest.get('eligibility_policy'))
    for filename in ('base.sqlite','lost-fleet.json'):
        if digest(path/filename)!=manifest['sha256'][filename]:raise ValueError('Release file hash mismatch')
    with sqlite3.connect((path/'base.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity failure')
        base_games,base_records=db.execute('SELECT COUNT(DISTINCT game_id),COUNT(*) FROM observations').fetchone()
        for (payload,) in db.execute('SELECT payload FROM observations'):
            if json.loads(payload)['ruleset']!='base':raise ValueError('Mixed base database')
    lf=load_dataset(path/'lost-fleet.json')['rows']
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
        old_lf=load_dataset(previous/'lost-fleet.json')['rows']
        allowed=set(allowed_exclusions)
        required_lf={(r['game_id'],r['faction']) for r in eligible_rows(old_lf) if r['game_id'] not in allowed}
        required_base={identity for identity in base_ids(previous/'base.sqlite',eligible=True) if identity[0] not in allowed}
        if allow_static_base_migration:
            migration = manifest.get('base_migration', {})
            if (manifest.get('base_source_policy') != BASE_SOURCE_POLICY or
                    migration.get('previous_release') != previous.name or
                    migration.get('previous_base_sha256') != digest(previous/'base.sqlite')):
                raise ValueError('Invalid static base migration provenance')
            required_base = set()  # Prior merged data is retained, not served.
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


BASE_SOURCE_POLICY = 'original-csv-only-v1'


def archive_sources(archive, mode='lost-fleet'):
    database = Path(archive)/'archive.sqlite3'
    if not database.exists():return {}
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        return {slug:[sha,status] for slug,sha,status in db.execute(
            'SELECT slug,sha256,status FROM exports WHERE mode=? AND '
            '(status IN ("accepted","excluded") OR (status="rejected" AND sha256 IS NOT NULL)) ORDER BY slug', (mode,))}


def legacy_source(legacy):
    if not legacy:return {}, set()
    data=json.loads(Path(legacy).read_text())
    require_safe_policy(data.get('eligibility_policy'))
    excluded=stored_exclusions(data.get('excluded_game_ids', [])) | excluded_ids(data['rows'])
    groups=defaultdict(list)
    for row in data['rows']:
        # Historical base observations come only from the original CSV seed.
        if row.get('ruleset') == 'base':continue
        if row.get('ruleset') != 'lost-fleet' or not row.get('score_verified'):
            raise ValueError('Invalid legacy records')
        groups[row['game_id']].append(row)
    return dict(groups), excluded


def source_identity(seed_base,archive,legacy):
    groups,excluded=legacy_source(legacy)
    return {'base_source_policy':BASE_SOURCE_POLICY, 'eligibility_policy':POLICY_VERSION,
            'score_basis_version':SCORE_BASIS_VERSION,'normalization_version':NORMALIZATION_VERSION,
            'seed':digest(seed_base),
            'legacy':hashlib.sha256(encoded({'games':groups,'excluded':sorted(excluded)})).hexdigest(),
            'accepted':hashlib.sha256(encoded(archive_sources(archive))).hexdigest()}


def seed_evidence(seed):
    with sqlite3.connect(Path(seed).resolve().as_uri()+'?mode=ro',uri=True) as db:
        metadata=dict(db.execute('SELECT key,value FROM metadata'))
        require_safe_policy(metadata.get('eligibility_policy'))
        if metadata.get('score_basis_version') != SCORE_BASIS_VERSION:
            raise ValueError('Static base requires a rebuilt original CSV seed with current score provenance')
        excluded=stored_exclusions(json.loads(metadata.get('excluded_game_ids','[]')))
        excluded.update(row[0] for row in db.execute('SELECT DISTINCT game_id FROM observations WHERE NOT ('+BASE_ELIGIBLE_SQL+')'))
        ids={row[0] for row in db.execute('SELECT DISTINCT game_id FROM observations')}
    return ids, excluded


def build_static_base(seed, target, excluded):
    # Never link the mutable seed or write through a link to an earlier release.
    shutil.copyfile(seed,target)
    with sqlite3.connect(target) as db:
        db.executemany('DELETE FROM observations WHERE game_id=?',((slug,) for slug in excluded))
        catalog={k:set() for k in ('faction','layout','auction','faction_variant','round_scorings','final_scorings','advanced_technologies')}
        for (payload,) in db.execute('SELECT payload FROM observations'):
            row=json.loads(payload)
            if row.get('score_basis_version') != SCORE_BASIS_VERSION:
                raise ValueError('Static seed contains unmigrated observation')
            for k in ('faction','layout','auction','faction_variant'):catalog[k].add(str(row[k]))
            for k in ('round_scorings','final_scorings'):catalog[k].update(row[k])
            catalog['advanced_technologies'].update(v for k,v in row['technologies'].items() if k.startswith('adv-'))
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('catalog',json.dumps({k:sorted(v) for k,v in catalog.items()})))
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('base_source_policy',BASE_SOURCE_POLICY))
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('excluded_game_ids',json.dumps(sorted(excluded))))
        return db.execute('SELECT COUNT(DISTINCT game_id),COUNT(*) FROM observations').fetchone()


def publish(root,seed_base,archive,legacy=None,*,dry_run=False,allow_static_base_migration=False):
    """Caller holds refresh.lock. Retain every raw, input and prior release file.

    Migration opt-in changes the served base source, not the preserved archive.
    LF remains monotonic except explicit whole-game eligibility exclusions.
    """
    root=Path(root);previous=current(root)
    prior=validate(previous) if previous else None
    migrating=bool(prior and prior.get('base_source_policy') != BASE_SOURCE_POLICY)
    if migrating and not allow_static_base_migration:
        raise ValueError('Merged base release requires explicit static CSV migration into a reviewed bundle')
    known=known_exclusions(root)
    inputs=source_identity(seed_base,archive,legacy)
    if prior and prior.get('inputs')==inputs and known <= stored_exclusions(prior.get('excluded_game_ids', [])):
        return prior
    checkpoint_path=root/'source-checkpoint.json'
    checkpoint=json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {}
    if (prior and checkpoint.get('release')==prior['release'] and checkpoint.get('inputs')==inputs and
            known <= stored_exclusions(prior.get('excluded_game_ids',[]))):
        return prior
    legacy_groups,legacy_exclusions=legacy_source(legacy)
    excluded=known | legacy_exclusions | stored_exclusions(prior.get('excluded_game_ids',[]) if prior else [])
    seed_ids,seed_exclusions=seed_evidence(seed_base)
    excluded.update(seed_exclusions)
    # One-time migration retains verified base exclusion evidence, but imports no
    # base raw observations and never makes base raw part of ongoing identity.
    if migrating or not prior:
        for slug,(sha,status) in archive_sources(archive,'base').items():
            if excluded_export(verified_export(archive,'base',slug,sha,status)):
                excluded.add(slug)
    lf={}
    if previous:
        for row in load_dataset(previous/'lost-fleet.json')['rows']:
            lf.setdefault(row['game_id'],[]).append(row)
    for slug,rows in legacy_groups.items():
        if slug not in lf:lf[slug]=rows
    for rows in lf.values():excluded.update(excluded_ids(rows))
    versions=('normalization_version','eligibility_policy','score_basis_version')
    compatible=bool(prior and all(prior.get('inputs',{}).get(k)==inputs[k] for k in versions))
    unchanged=prior.get('lf_sources',{}) if compatible else {}
    if compatible and checkpoint.get('release')==prior['release']:
        unchanged=checkpoint.get('lf_sources',unchanged)
    sources=archive_sources(archive)
    for slug,rows in accepted_exports(archive,'lost-fleet',unchanged=unchanged):
        if not rows:excluded.add(slug)
        else:lf[slug]=rows
    empty_after_exclusion=[mode for mode,ids in (('base',seed_ids),('lost-fleet',set(lf)))
                           if (ids and ids<=excluded) or
                           (not ids and prior and mode in prior.get('empty_after_exclusion',[]))]
    for slug in excluded:lf.pop(slug,None)
    lf={slug:analysis_rows(rows) for slug,rows in lf.items()}
    base_inputs={'seed':inputs['seed'],'eligibility_policy':POLICY_VERSION,
                 'score_basis_version':SCORE_BASIS_VERSION,'excluded_game_ids':sorted(excluded & seed_ids)}
    reuse=bool(prior and prior.get('base_source_policy')==BASE_SOURCE_POLICY and prior.get('base_inputs')==base_inputs)
    if reuse and compatible and excluded==stored_exclusions(prior.get('excluded_game_ids',[])):
        old_groups={}
        for row in load_dataset(previous/'lost-fleet.json')['rows']:
            old_groups.setdefault(row['game_id'],[]).append(row)
        signatures=lambda groups:{slug:hashlib.sha256(encoded(sorted(rows,key=lambda r:r['faction']))).hexdigest() for slug,rows in groups.items()}
        if signatures(lf)==signatures(old_groups):
            # Source bookkeeping may change without changing a single served
            # observation. Keep the generation/pointer/cache and record a small
            # checkpoint so the same inputs do not need processing next time.
            if not dry_run:atomic_json(checkpoint_path,{'release':prior['release'],'inputs':inputs,'lf_sources':sources})
            return prior
    # Growth is one base snapshot only when its actual source changes, plus new
    # LF objects and tiny indexes. Reserve ample bounded headroom, not 2x base on
    # every LF refresh. Existing artifacts are never pruned here.
    estimate=(0 if reuse else Path(seed_base).stat().st_size)+sum(len(encoded(rows)) for rows in lf.values())+1024**2
    if shutil.disk_usage(root).free < max(64*1024**2,estimate+16*1024**2):
        raise ValueError('Insufficient free space for a safe release; retain current data')
    (root/'releases').mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='release-',dir=root/'releases'))
    try:
        if reuse:
            # Same-filesystem link is mandatory: never silently resume full-copy
            # growth on a misconfigured filesystem. Prior releases are read-only.
            os.link(previous/'base.sqlite',stage/'base.sqlite')
            bg,br=(prior['datasets']['base'][k] for k in ('games','records'))
        else:
            bg,br=build_static_base(seed_base,stage/'base.sqlite',excluded & seed_ids)
        write_dataset(stage/'lost-fleet.json',lf,eligibility_policy=POLICY_VERSION,
                      scope='Incremental public LF archive plus preserved prior records; see health for coverage and freshness')
        manifest={'inputs':inputs,'base_source_policy':BASE_SOURCE_POLICY,'base_inputs':base_inputs,
                  'lf_sources':sources,'schema_version':1,'score_basis_version':SCORE_BASIS_VERSION,
                  'eligibility_policy':POLICY_VERSION,'excluded_games':len(excluded),'excluded_game_ids':sorted(excluded),
                  'empty_after_exclusion':empty_after_exclusion,'created_at':utc(),'release':stage.name,
                  'previous':previous.name if previous else None,
                  'datasets':{'base':{'games':bg,'records':br},'lost-fleet':{'games':len(lf),'records':sum(map(len,lf.values()))}},
                  'raw_accepted_games':{'base':0,'lost-fleet':sum(status=='accepted' and slug in lf for slug,(sha,status) in sources.items())},
                  'coverage':'Static original base CSV only; no base collection or raw overlays. Lost Fleet updates incrementally; archived inputs and prior releases are retained.',
                  'sha256':{name:digest(stage/name) for name in ('base.sqlite','lost-fleet.json')}}
        if migrating:
            old_ids=base_ids(previous/'base.sqlite');new_ids=base_ids(stage/'base.sqlite')
            manifest['base_migration']={'previous_release':previous.name,'previous_base_sha256':prior['sha256']['base.sqlite'],
                                       'previous_counts':prior['datasets']['base'],'seed_sha256':inputs['seed'],
                                       'archived_only_games':len({g for g,f in old_ids-new_ids}),
                                       'archived_only_records':len(old_ids-new_ids)}
        atomic_json(stage/'manifest.json',manifest)
        validate(stage,previous,allowed_exclusions=excluded,allow_static_base_migration=migrating)
        for slug,old in legacy_groups.items():
            if slug not in excluded and not {r['faction'] for r in old}<={r['faction'] for r in lf.get(slug,[])}:
                raise ValueError('Legacy LF record preservation failed')
        if not dry_run:
            atomic_json(root/'exclusions.json',{'eligibility_policy':POLICY_VERSION,'game_ids':sorted(excluded)})
            atomic_json(root/'current.json',{'release':stage.name})
        return manifest
    except BaseException:
        # Keep even incomplete candidates for inspection. Never remove existing
        # data or risk undoing an atomic pointer swap after an interruption.
        raise


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--seed-base',required=True);parser.add_argument('--archive',required=True);parser.add_argument('--legacy');parser.add_argument('--dry-run',action='store_true');parser.add_argument('--rollback');parser.add_argument('--allow-static-base-migration',action='store_true')
    args=parser.parse_args()
    with release_lock(args.root):
        if args.rollback:
            if not re.fullmatch(r'release-[a-zA-Z0-9_-]+',args.rollback):raise ValueError('Invalid rollback release')
            path=Path(args.root)/'releases'/args.rollback;validate(path,known_exclusions=known_exclusions(args.root))
            if not args.dry_run:atomic_json(Path(args.root)/'current.json',{'release':args.rollback})
            print(json.dumps({'rollback':args.rollback,'dry_run':args.dry_run}))
        else:print(json.dumps(publish(args.root,args.seed_base,args.archive,args.legacy,dry_run=args.dry_run,allow_static_base_migration=args.allow_static_base_migration),indent=2))

if __name__=='__main__':main()
