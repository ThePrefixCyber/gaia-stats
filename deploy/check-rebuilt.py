#!/usr/bin/env python3
"""Run AS gaia-stats before switching services; no network, seeding or writes."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gaia_stats.releases import current,validate
from gaia_stats.wsgi import ReleaseApplication


def check(root,cache):
    release=current(root)
    if release is None:raise ValueError('Missing current data release')
    manifest=validate(release)
    cache=Path(cache);build=json.loads((cache/'current.json').read_text())['build']
    asset=cache/build/'plotly.min.js'
    if not asset.is_file() or asset.stat().st_size<100000:raise ValueError('Missing or incomplete Plotly asset')
    # Opening proves access as the service account, not just path existence as root.
    with asset.open('rb') as handle:handle.read(1024)
    app=ReleaseApplication(root,cache)
    for path,query in [('/',''),('/healthz',''),('/cohort/api/catalog','ruleset=base'),('/cohort/api/catalog','ruleset=lost-fleet'),('/cohort/api/stats','ruleset=base&min_elo=999999&plot=point-sources'),('/cohort/api/stats','ruleset=lost-fleet&lf_2p_4qic_mode=include-both&plot=point-sources')]:
        status=[];body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':path,'QUERY_STRING':query},lambda s,h:status.append(s)))
        if status!=['200 OK']:raise ValueError('Unreadable rebuilt route: '+path+' '+body.decode()[:200])
        if path=='/' and b'id="mode"' not in body:raise ValueError('Root is not the rebuilt cohort interface')
    return manifest['datasets']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--cache',required=True);a=p.parse_args()
    print(json.dumps(check(a.root,a.cache),indent=2))
