"""Compare uncached cohort responses against the original setup-table traversal.

Build a local database first with gaia_stats.base_cohort, then run:
python tools/benchmark_cohort.py /tmp/base.sqlite --repeats 5
No production requests, writes, or serving-data changes are made.
"""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia_stats import base_cohort, cohort


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--baseline', default='868b3f7a0d48dcd4abdcf3d8c3784a5ce6a75696')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    source = subprocess.check_output(['git', 'show', args.baseline + ':gaia_stats/cohort.py'], cwd=ROOT)
    baseline = types.ModuleType('gaia_stats._baseline_cohort')
    baseline.__package__ = 'gaia_stats'
    exec(compile(source, '<baseline cohort>', 'exec'), baseline.__dict__)
    optimized = cohort.setup_comparisons
    results = []
    try:
        for kind in ('advanced-tech-frequency', 'point-sources', 'round-scoring'):
            filters = {'ruleset': 'base', 'plot': kind}
            timings = {'before': [], 'after': []}
            bodies = {}
            for iteration in range(args.repeats):
                variants = [('before', baseline.setup_comparisons), ('after', optimized)]
                if iteration % 2:
                    variants.reverse()
                for label, implementation in variants:
                    cohort.setup_comparisons = implementation
                    start = time.perf_counter()
                    body, _ = base_cohort.response(args.database, '/cohort/api/stats', filters)
                    timings[label].append(time.perf_counter() - start)
                    bodies[label] = body
                if bodies['before'] != bodies['after']:
                    raise AssertionError('Response changed for ' + kind)
            data = json.loads(bodies['after'])
            before, after = (statistics.median(timings[key]) for key in ('before', 'after'))
            results.append({'plot': kind, 'games': data['games'], 'records': data['samples'],
                            'before_seconds': before, 'after_seconds': after,
                            'reduction_percent': (before-after)/before*100,
                            'response_bytes': len(bodies['after']), 'byte_identical': True,
                            'runs': timings})
    finally:
        cohort.setup_comparisons = optimized
    print(json.dumps({'baseline': args.baseline, 'repeats': args.repeats,
                      'method': 'Uncached API computation, alternating before/after; disk cache warm',
                      'results': results}, indent=2))


if __name__ == '__main__':
    main()
