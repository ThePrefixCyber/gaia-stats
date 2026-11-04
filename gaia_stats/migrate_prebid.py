"""Prepare, verify and retain a separate pre-bid bundle; never activate it.

Run from the reviewed candidate checkout while both production timers are paused.
The source release lock prevents concurrent publication. Original CSVs, archive,
source release pointer and prior generations remain untouched.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from .__main__ import atomic_json
from .base_cohort import build as build_seed
from .legacy_cache import build_cache
from .archive import archive_lock
from .releases import current, validate, known_exclusions, publish, release_lock, digest, utc, source_identity
from .score_basis import SCORE_BASIS_VERSION
from .eligibility import POLICY_VERSION
from .release_data import object_path


def prepare(destination, source_root, csvs, archive, legacy=None):
    destination, source_root, archive = map(Path, (destination, source_root, archive))
    destination = destination.parent.resolve(strict=True) / destination.name
    legacy = Path(legacy).resolve(strict=True) if legacy is not None else None
    if destination.exists():
        raise ValueError('Destination already exists; use a fresh bundle path, never overwrite a prior attempt')
    if not source_root.is_dir() or not archive.is_dir():
        raise ValueError('Existing release store and preserved archive are required')
    if not csvs or any(count not in (2,3,4) for count in csvs):
        raise ValueError('Supply original 2/3/4-player CSVs, not generated downloads')
    csvs={count:Path(path).resolve(strict=True) for count,path in csvs.items()}
    source_root=source_root.resolve(strict=True)
    archive=archive.resolve(strict=True)
    if destination.resolve().is_relative_to(archive) or archive.is_relative_to(destination.resolve()):
        raise ValueError('Staged bundle and preserved archive must be separate')
    if destination.resolve().is_relative_to(source_root) or source_root.is_relative_to(destination.resolve()):
        raise ValueError('Staged bundle and source release store must be separate')
    with release_lock(source_root), archive_lock(archive):
        original=current(source_root)
        if original is None:raise ValueError('Source has no selected immutable release')
        original_manifest=validate(original,known_exclusions=known_exclusions(source_root))
        source_pointer=(source_root/'current.json').read_bytes()
        registry=source_root/'exclusions.json'
        registry_hash=digest(registry) if registry.exists() else None
        source_hashes={name:digest(original/name) for name in ('base.sqlite','lost-fleet.json','manifest.json')}
        parent=destination.parent
        if not parent.is_dir():raise ValueError('Destination parent must already exist')
        source_index=json.loads((original/'lost-fleet.json').read_text())
        source_objects={sha:object_path(original/'lost-fleet.json',sha) for sha in source_index.get('games',{}).values()} if source_index.get('storage') else {}
        object_bytes=sum(path.stat().st_size for path in source_objects.values())
        source_size=sum((original/name).stat().st_size for name in ('base.sqlite','lost-fleet.json','manifest.json'))+object_bytes
        required=max(1024**3,4*source_size+2*sum(path.stat().st_size for path in csvs.values())+512*1024**2)
        if shutil.disk_usage(parent).free < required:
            raise ValueError(f'Insufficient staging disk space: need at least {required} free bytes; no source data changed')
        destination.mkdir(mode=0o750)
        record={'state':'preparing','started_at':utc(),'source_release':original.name,
                'source_hashes':source_hashes,'required_free_bytes':required,
                'source_lf_object_count':len(source_objects),'source_lf_object_bytes':object_bytes,
                'csvs':{str(count):{'path':str(path),'sha256':digest(path)} for count,path in csvs.items()},
                'score_basis_version':SCORE_BASIS_VERSION,'eligibility_policy':POLICY_VERSION}
        atomic_json(destination/'preparation.json',record)
        try:
            seed=destination/'seeds/base.sqlite'
            build_seed(csvs,seed)
            store=destination/'releases-store'
            baseline=store/'releases'/original.name
            baseline.parent.mkdir(parents=True)
            shutil.copytree(original,baseline)
            # Only selected objects are needed by this preserved baseline. Keep
            # unrelated old/temporary objects in their original store unchanged.
            for sha,path in source_objects.items():
                target=object_path(baseline/'lost-fleet.json',sha)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,target)
                if digest(target)!=sha:raise ValueError('LF object changed during staging')
            atomic_json(store/'current.json',{'release':original.name})
            if registry.exists():shutil.copyfile(registry,store/'exclusions.json')
            expected_inputs=source_identity(seed,archive,legacy)
            with release_lock(store):
                manifest=publish(store,seed,archive,legacy,allow_static_base_migration=True)
            build_cache(destination/'classic-cache',csvs,excluded_game_ids=known_exclusions(store))
            code=Path(__file__).resolve().parents[1]
            check=subprocess.run([sys.executable,str(code/'deploy/check-data-contract.py'),
                                  '--contract',str(code/'deploy/data-contract.json'),
                                  '--root',str(store),'--seed',str(seed),
                                  '--cache',str(destination/'classic-cache')],
                                 capture_output=True,text=True)
            if check.returncode:
                raise ValueError('Staged data-contract preflight failed: '+(check.stderr or check.stdout).strip())
            if any(digest(csvs[int(count)]) != info['sha256'] for count,info in record['csvs'].items()):
                raise ValueError('Original CSV changed during staging; do not activate this bundle')
            if expected_inputs != source_identity(seed,archive,legacy):
                raise ValueError('Archive or legacy inputs changed during staging; do not activate this bundle')
            if (digest(registry) if registry.exists() else None) != registry_hash:
                raise ValueError('Source exclusion registry changed during staging; do not activate this bundle')
            if (source_root/'current.json').read_bytes()!=source_pointer or any(digest(original/name)!=sha for name,sha in source_hashes.items()):
                raise ValueError('Source changed during staging; do not activate this bundle')
            record.update(state='ready',finished_at=utc(),release=manifest['release'],
                          datasets=manifest['datasets'],preflight=check.stdout.strip())
            atomic_json(destination/'preparation.json',record)
            return record
        except BaseException as error:
            record.update(state='failed',finished_at=utc(),error=str(error))
            atomic_json(destination/'preparation.json',record)
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',required=True)
    parser.add_argument('--source-root',required=True)
    parser.add_argument('--csv',action='append',required=True,metavar='PLAYERS=ORIGINAL_CSV')
    parser.add_argument('--archive',required=True)
    parser.add_argument('--legacy')
    args=parser.parse_args();csvs={}
    for entry in args.csv:
        count,path=entry.split('=',1);count=int(count)
        if count in csvs:parser.error('Duplicate player-count CSV')
        csvs[count]=path
    print(json.dumps(prepare(args.destination,args.source_root,csvs,args.archive,args.legacy),indent=2))

if __name__=='__main__':main()
