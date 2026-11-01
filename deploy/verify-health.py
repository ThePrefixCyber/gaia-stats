#!/usr/bin/env python3
"""Check the running commit and ruleset isolation through Gunicorn and Nginx."""
import json
import sys
import time
from urllib.request import urlopen


def verify(expected, fetch):
    for base in ('http://127.0.0.1:8000', 'http://127.0.0.1'):
        health = fetch(base + '/healthz')
        if health.get('status') != 'ok' or health.get('commit') != expected:
            raise ValueError('Health does not report the expected running commit')
        if 'datasets' in health:
            root=fetch(base+'/')
            asset=fetch(base+'/classic/assets/plotly.min.js')
            if not isinstance(root,str) or 'id="mode"' not in root or not isinstance(asset,str) or len(asset)<100000:
                raise ValueError('Rebuilt root or Plotly asset is unavailable')
            for mode in ('base','lost-fleet'):
                result=fetch(base+'/cohort/api/stats?ruleset='+mode+'&lf_2p_4qic_mode=include-both&plot=point-sources')
                if result['ruleset']!=mode or result['games']!=health['datasets'][mode]['games'] or result['samples']!=health['datasets'][mode]['records']:
                    raise ValueError('Release mode counts disagree with health')
            continue
        total_games = total_records = 0
        for ruleset in ('base', 'lost-fleet'):
            result = fetch(base + '/api/analysis?lf_2p_4qic_mode=include-both&ruleset=' + ruleset)
            rows = result['rows']
            games = len({row['game_id'] for row in rows})
            if (result['ruleset'] != ruleset
                    or any(row['ruleset'] != ruleset for row in rows)
                    or result['player_records'] != len(rows)
                    or result['games'] != games):
                raise ValueError('Ruleset response or counts are inconsistent')
            total_games += games
            total_records += len(rows)
        if (health.get('games'), health.get('player_records')) != (total_games, total_records):
            raise ValueError('Health and ruleset counts disagree')


def fetch(url):
    with urlopen(url, timeout=90) as response:
        raw=response.read()
        if 'application/json' in response.headers.get('Content-Type',''):
            return json.loads(raw)
        return raw.decode()


if __name__ == '__main__':
    for attempt in range(15):
        try:
            verify(sys.argv[1], fetch)
            break
        except (OSError, ValueError, KeyError, TypeError) as error:
            if attempt == 14:
                sys.exit('Deployment verification failed: ' + str(error))
            time.sleep(2)
