"""Exact-result and request-isolation regressions for cohort performance work."""
import copy
import json
import threading
import unittest
from statistics import mean
from unittest.mock import patch

from gaia_stats.cohort import setup_comparisons
from gaia_stats.scoring import tile_value
import test_base_cohort as fixtures


def reference_setup(groups):
    """Original formula, intentionally independent of the optimized traversal."""
    result = {'rounds': [], 'finals': [], 'technologies': []}
    for faction, rows in sorted(groups.items()):
        for kind, keys in (('rounds', [f'round{i}' for i in range(1, 7)]),
                           ('finals', ['final1', 'final2'])):
            record = {'faction': faction, 'samples': len(rows)}
            for key in keys:
                values = [tile_value(r, key) for r in rows if tile_value(r, key) is not None]
                record[key] = mean(values) if values else None
                record[key + '_n'] = len(values)
            result[kind].append(record)
        record = {'faction': faction, 'samples': len(rows)}
        for slot in ('adv-terra', 'adv-nav', 'adv-int', 'adv-gaia', 'adv-eco', 'adv-sci', 'adv-ext'):
            taken = [r['score'] for r in rows
                     if any(t['slot'] == slot for t in (r.get('owned_technologies') or []))]
            record[slot] = mean(taken) if taken else None
            record[slot + '_n'] = len(taken)
        result['technologies'].append(record)
    return result


class PerformanceTests(unittest.TestCase):
    setUp = fixtures.BaseCohortTests.setUp

    def test_setup_is_exact_with_missing_zero_duplicate_and_expansion_observations(self):
        from gaia_stats.base_cohort import dataset
        rows = dataset(self.db, {})['rows']
        rows += copy.deepcopy(self.app.load()['rows'])
        rows[0]['owned_technologies'] = [{'slot': 'adv-terra', 'tile': 'a'},
                                         {'slot': 'adv-terra', 'tile': 'b'},
                                         {'slot': 'adv-ext', 'tile': 'c'}]
        rows[1]['owned_technologies'] = None
        rows[2]['vp_sources'].pop('round1', None)
        rows[3]['vp_sources']['round1'] = 0
        groups = {'mixed': rows, 'empty': []}
        self.assertEqual(setup_comparisons(groups), reference_setup(groups))

    def test_static_assets_do_not_wait_for_calculations_or_load_dataset(self):
        self.app.cohort_lock.acquire()
        done = threading.Event()
        failures = []
        def request():
            try:
                with patch.object(self.app, 'load_snapshot', side_effect=AssertionError('Dataset decoded')):
                    for path, expected in [('/cohort/', b'Gaia Project Stats'),
                                           ('/cohort/app.js', b'function draw')]:
                        body, _ = self.app.cohort_response(path, {})
                        self.assertIn(expected, body)
            except Exception as error:
                failures.append(error)
            finally:
                done.set()
        thread = threading.Thread(target=request, daemon=True)
        thread.start()
        try:
            self.assertTrue(done.wait(2), 'Static assets blocked behind cohort work')
        finally:
            self.app.cohort_lock.release()
            thread.join(2)
        self.assertEqual(failures, [])

    def test_warm_response_and_catalog_do_not_wait_for_another_cold_query(self):
        filters = {'ruleset': 'base', 'plot': 'round-scoring'}
        expected = self.app.cohort_response('/cohort/api/stats', filters)
        done = threading.Event()
        results = []
        self.app.cohort_lock.acquire()
        def request():
            try:
                results.append(self.app.cohort_response('/cohort/api/stats', filters))
                results.append(self.app.cohort_response('/cohort/api/catalog', {'ruleset': 'base'}))
            finally:
                done.set()
        thread = threading.Thread(target=request, daemon=True)
        thread.start()
        try:
            self.assertTrue(done.wait(2), 'Cached response blocked behind unrelated work')
        finally:
            self.app.cohort_lock.release()
            thread.join(2)
        self.assertEqual(results[0], expected)
        self.assertIn('faction', json.loads(results[1][0]))

    def test_technology_views_have_identical_observations(self):
        for mode in ('base', 'lost-fleet'):
            for family in ('advanced',):
                plots = []
                for view in ('frequency', 'score'):
                    kind = f'{family}-tech-{view}'
                    body, _ = self.app.cohort_response('/cohort/api/stats', {
                        'ruleset': mode, 'plot': kind, 'lf_2p_4qic_mode': 'include-both'})
                    plot = json.loads(body)['plots'][kind]
                    plot.pop('kind')
                    plots.append(plot)
                self.assertEqual(*plots)
