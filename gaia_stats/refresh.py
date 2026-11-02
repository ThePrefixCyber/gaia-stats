"""Bounded, locked archive refresh and atomic release publication; no service mutation."""
import argparse
import json
from pathlib import Path
import signal
import time

from .archive import ArchiveClient,collect
from .__main__ import atomic_json
from .releases import publish,release_lock,utc,current


class RefreshDeadline(BaseException):pass


def run(root,seed_base,archive,legacy=None,*,client=None,max_pages=20,max_downloads=100,max_seconds=720,dry_run=False,pagination='cursor'):
    if not 1<=max_pages<=100 or not 0<=max_downloads<=500 or not 1<=max_seconds<=900:
        raise ValueError('Refresh limits exceed release policy')
    root=Path(root)
    with release_lock(root):
        status_path=root/'refresh-status.json'
        previous=json.loads(status_path.read_text()) if status_path.exists() else {}
        status={'state':'running','started_at':utc(),'last_success':previous.get('last_success'),
                'last_successful_release':previous.get('last_successful_release'),
                'last_publication':previous.get('last_publication'),
                'last_publication_release':previous.get('last_publication_release'),
                'error':None,'passes':{},'warnings':[]}
        if not dry_run:atomic_json(status_path,status)
        old_handler=signal.getsignal(signal.SIGALRM)
        def timeout(*_):raise RefreshDeadline('Data refresh exceeded maximum runtime')
        signal.signal(signal.SIGALRM,timeout);signal.alarm(max_seconds)
        started=time.monotonic()
        try:
            if not dry_run:
                client=client or ArchiveClient(interval=1.1,attempts=3)
                for mode in ('lost-fleet','base'):
                    # Always inspect the newest entries, without moving the historical cursor.
                    head=collect(archive,mode,client=client,max_pages=2,max_downloads=min(20,max_downloads),head_only=True,pagination=pagination)
                    status['passes'][mode+'-head']=head
                    if head['listing_error'] or head['retry']:raise ValueError(mode+' head scan did not complete cleanly')
                    remaining=max_downloads-head['accepted']-head['rejected']-head['retry']
                    result=collect(archive,mode,client=client,max_pages=max_pages,max_downloads=remaining,pagination=pagination)
                    status['passes'][mode]=result
                    if result['listing_error'] and result.get('listing_error_detail',{}).get('http_status')==400 and not result['retry']:
                        # Discovery failure cannot invalidate independently verified exports.
                        # Retain the checkpoint/error; never interpret HTTP 400 as EOF.
                        status['warnings'].append(mode+' historical discovery failed; history remains incomplete')
                    elif result['listing_error'] or result['retry']:
                        raise ValueError(mode+' collector did not complete cleanly')
            prior_release=current(root)
            manifest=publish(root,seed_base,archive,legacy,dry_run=dry_run)
            status['publication_changed']=not dry_run and (prior_release is None or prior_release.name!=manifest['release'])
            degraded=bool(status['warnings'])
            status.update(state='dry-run' if dry_run else ('degraded' if degraded else 'ok'),finished_at=utc(),elapsed_seconds=round(time.monotonic()-started,3),release=manifest['release'])
            if not dry_run:
                if status['publication_changed']:
                    status.update(last_publication=utc(),last_publication_release=manifest['release'])
                if degraded:
                    status['error']='; '.join(status['warnings'])
                else:
                    status.update(last_success=utc(),last_successful_release=manifest['release'])
                atomic_json(status_path,status)
            return status
        except BaseException as error:
            status.update(state='error',finished_at=utc(),error=str(error),elapsed_seconds=round(time.monotonic()-started,3))
            if not dry_run:atomic_json(status_path,status)
            raise
        finally:
            signal.alarm(0);signal.signal(signal.SIGALRM,old_handler)


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--seed-base',required=True);p.add_argument('--archive',required=True);p.add_argument('--legacy');p.add_argument('--max-pages',type=int,default=20);p.add_argument('--max-downloads',type=int,default=100);p.add_argument('--max-seconds',type=int,default=720);p.add_argument('--dry-run',action='store_true')
    a=p.parse_args();result=run(a.root,a.seed_base,a.archive,a.legacy,max_pages=a.max_pages,max_downloads=a.max_downloads,max_seconds=a.max_seconds,dry_run=a.dry_run)
    print(json.dumps(result,indent=2))
    if result['state']=='degraded':raise SystemExit(1)

if __name__=='__main__':main()
