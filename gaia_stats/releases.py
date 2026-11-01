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


def accepted_exports(archive,mode):
    archive=Path(archive)
    if not (archive/'archive.sqlite3').exists():return
    with sqlite3.connect((archive/'archive.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        for slug,sha in db.execute('SELECT slug,sha256 FROM exports WHERE mode=? AND status="accepted" ORDER BY slug',(mode,)):
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,120}',slug):raise ValueError('Unsafe archive identifier')
            path=archive/mode/'raw'/(slug+'.json')
            if digest(path)!=sha:raise ValueError('Accepted archive hash mismatch: '+slug)
            payload=json.loads(path.read_text());rows=enrich(payload,normalize(payload))
            if payload.get('slug')!=slug or len(rows) not in (2,3,4) or any(r['ruleset']!=mode or not r['score_verified'] for r in rows):
                raise ValueError('Accepted archive validation failed: '+slug)
            yield slug,rows


def insert_game(db,slug,rows,replace=False):
    if not rows or any(r['game_id']!=slug or r['ruleset']!='base' for r in rows):raise ValueError('Base mode isolation failed')
    if not replace and db.execute('SELECT 1 FROM observations WHERE game_id=?',(slug,)).fetchone():return
    if replace:db.execute('DELETE FROM observations WHERE game_id=?',(slug,))
    for row in rows:
        db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)',tuple(row.get(k,'unknown') for k in ('game_id','faction','player_count','elo','layout','auction','faction_variant'))+(json.dumps(row,separators=(',',':')),))


def base_ids(path):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        return set(db.execute('SELECT game_id,faction FROM observations'))


def validate(path,previous=None):
    path=Path(path);manifest=json.loads((path/'manifest.json').read_text())
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
    if previous:
        old_lf=json.loads((previous/'lost-fleet.json').read_text())['rows']
        if not {(r['game_id'],r['faction']) for r in old_lf}<=lf_ids or not base_ids(previous/'base.sqlite')<=base_ids(path/'base.sqlite'):
            raise ValueError('Publication would lose existing player-game records')
    if not base_records or not lf:raise ValueError('Both release datasets must be nonempty')
    return manifest


def source_identity(seed_base,archive,legacy):
    entries=[]; database=Path(archive)/'archive.sqlite3'
    if database.exists():
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            entries=list(db.execute('SELECT mode,slug,sha256 FROM exports WHERE status="accepted" ORDER BY mode,slug'))
    return {'normalization_version':NORMALIZATION_VERSION,'seed':digest(seed_base),'legacy':digest(legacy) if legacy else None,
            'accepted':hashlib.sha256(json.dumps(entries).encode()).hexdigest()}


def publish(root,seed_base,archive,legacy=None,*,dry_run=False):
    """Caller holds refresh.lock. No prior releases or legacy files are removed."""
    root=Path(root);previous=current(root)
    prior=validate(previous) if previous else None
    inputs=source_identity(seed_base,archive,legacy)
    if prior and prior.get("inputs")==inputs:return prior
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
        if legacy:
            for row in json.loads(Path(legacy).read_text())['rows']:
                if row.get('ruleset') not in ('base','lost-fleet') or not row.get('score_verified'):raise ValueError('Invalid legacy records')
                legacy_groups[(row['ruleset'],row['game_id'])].append(row)
        raw_counts={}
        with sqlite3.connect(stage/'base.sqlite') as db:
            for (mode,slug),rows in legacy_groups.items():
                if mode=='base':insert_game(db,slug,rows)
                elif slug not in lf:lf[slug]=rows
            for mode in ('base','lost-fleet'):
                raw_counts[mode]=0
                for slug,rows in accepted_exports(archive,mode):
                    raw_counts[mode]+=1
                    if mode=='base':insert_game(db,slug,rows,replace=True)
                    else:lf[slug]=rows
            # Rebuild catalogue from this exact merged release, not stale historical options.
            catalog={k:set() for k in ('faction','layout','auction','faction_variant','round_scorings','final_scorings','advanced_technologies')}
            for (payload,) in db.execute('SELECT payload FROM observations'):
                row=json.loads(payload)
                for k in ('faction','layout','auction','faction_variant'):catalog[k].add(str(row[k]))
                for k in ('round_scorings','final_scorings'):catalog[k].update(row[k])
                catalog['advanced_technologies'].update(v for k,v in row['technologies'].items() if k.startswith('adv-'))
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('catalog',json.dumps({k:sorted(v) for k,v in catalog.items()})))
            bg,br=db.execute('SELECT COUNT(DISTINCT game_id),COUNT(*) FROM observations').fetchone()
        rows=[row for slug in sorted(lf) for row in lf[slug]]
        atomic_json(stage/'lost-fleet.json',{'schema_version':1,'rows':rows,'scope':'Public LF archive plus preserved prior records; see health for refresh coverage and freshness'})
        manifest={'inputs':inputs,'schema_version':1,'created_at':utc(),'release':stage.name,'previous':previous.name if previous else None,
                  'datasets':{'base':{'games':bg,'records':br},'lost-fleet':{'games':len(lf),'records':len(rows)}},
                  'raw_accepted_games':raw_counts,'coverage':'Historical base CSV seed plus accepted raw exports; raw backfill may be incomplete. Overlapping game IDs are replaced, never added twice.',
                  'sha256':{name:digest(stage/name) for name in ('base.sqlite','lost-fleet.json')}}
        atomic_json(stage/'manifest.json',manifest)
        validate(stage,previous)
        # Preserve all legacy identities even when the very first release has no predecessor.
        for (mode,slug),old in legacy_groups.items():
            ids={(r['game_id'],r['faction']) for r in old}
            available=base_ids(stage/'base.sqlite') if mode=='base' else {(r['game_id'],r['faction']) for r in rows}
            if not ids<=available:raise ValueError('Legacy record preservation failed')
        if not dry_run:atomic_json(root/'current.json',{'release':stage.name})
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
            path=Path(args.root)/'releases'/args.rollback;validate(path)
            if not args.dry_run:atomic_json(Path(args.root)/'current.json',{'release':args.rollback})
            print(json.dumps({'rollback':args.rollback,'dry_run':args.dry_run}))
        else:print(json.dumps(publish(args.root,args.seed_base,args.archive,args.legacy,dry_run=args.dry_run),indent=2))

if __name__=='__main__':main()
