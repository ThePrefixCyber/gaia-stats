"""Persistent tables compare factions; charts and exports retain faction selection."""
import copy
import csv
import io
import json
from pathlib import Path
import unittest

from gaia_stats.analysis import normalize
from gaia_stats.cohort import cohort, enrich, report, statistics, PLOTS
from gaia_stats import base_cohort, streaming_cohort
import test_base_cohort as base_fixtures
import test_streaming_cohort as streaming_fixtures


class ComparisonScopeTests(unittest.TestCase):
    assert_equivalent = streaming_fixtures.StreamingTests.assert_equivalent

    @classmethod
    def setUpClass(cls):
        cls.batches = []
        for name in ('Jubilant-rover-3041.json', 'cohort/Admirable-falcon-401.json',
                     'cohort/Eclipsed-council-7948.json'):
            game = json.loads((Path(__file__).parent / 'fixtures' / name).read_text())
            cls.batches.append(enrich(game, normalize(game)))
        cls.dataset = {'rows': [row for batch in cls.batches for row in batch], 'scope': 'test'}

    def test_each_plot_keeps_faction_while_all_four_tables_compare_all_factions(self):
        filters = {'ruleset': 'lost-fleet', 'lf_2p_4qic_mode': 'include-both', 'min_elo': '100'}
        baseline = report(self.dataset, filters)
        for kind in PLOTS:
            with self.subTest(kind=kind):
                selected = {**filters, 'faction': 'tinkeroids', 'plot': kind}
                result = report(self.dataset, selected)
                self.assertEqual(result['comparisons'], baseline['comparisons'])
                self.assertEqual(result['setup_comparisons'], baseline['setup_comparisons'])
                rows = cohort(self.dataset, selected)
                self.assertEqual(result['samples'], len(rows))
                self.assertEqual(result['record_ids'], [r['game_id']+':'+r['faction'] for r in rows])
                if kind != 'final-scoring':
                    self.assertEqual(result['plots'][kind], statistics(rows, kind))
                else:
                    self.assertTrue(all(c['faction'] == 'tinkeroids' for c in result['plots'][kind]['cells']))
                    self.assertTrue(any(c['score_baseline_samples'] > c['score_samples']
                                        for c in result['plots'][kind]['cells']))

    def test_comparisons_relax_only_faction_and_preserve_every_setup_filter(self):
        anchor = copy.deepcopy(self.batches[-1][0])
        filters = {key: str(anchor[key]) for key in ('ruleset', 'player_count', 'layout', 'auction', 'faction_variant')}
        filters.update(faction=anchor['faction'], min_elo=str(anchor['elo']),
                       lf_2p_4qic_mode='variant-only', final_scoring=anchor['final_scorings'][0],
                       final_scoring2=anchor['final_scorings'][1], plot='basic-tech-score')
        filters.update({'round'+str(i+1): tile for i, tile in enumerate(anchor['round_scorings'])})
        filters.update({slot: tile for slot, tile in anchor['technologies'].items() if slot.startswith('adv-')})
        other = copy.deepcopy(anchor); other['faction'] = 'other-faction'
        excluded = []
        for key in ('ruleset', 'player_count', 'layout', 'auction', 'faction_variant', 'elo', 'lf_2p_4qic_effective'):
            row = copy.deepcopy(other)
            row[key] = {'ruleset': 'base', 'player_count': 3, 'elo': anchor['elo']-1,
                        'lf_2p_4qic_effective': False}.get(key, 'different')
            excluded.append(row)
        for index in range(6):
            row = copy.deepcopy(other); row['round_scorings'][index] = 'different'; excluded.append(row)
        for index in range(2):
            row = copy.deepcopy(other); row['final_scorings'][index] = 'different'; excluded.append(row)
        for slot in filters.keys() & anchor['technologies'].keys():
            row = copy.deepcopy(other); row['technologies'][slot] = 'different'; excluded.append(row)
        for i, row in enumerate(excluded):
            row['faction'] = 'excluded-'+str(i); row['game_id'] = 'excluded-game-'+str(i)
        result = report({'rows': [anchor, other, *excluded]}, filters)
        expected = report({'rows': [anchor, other]}, {k: v for k, v in filters.items() if k != 'faction'})
        self.assertEqual(result['samples'], 1)
        self.assertEqual({r['faction'] for r in result['comparisons']}, {anchor['faction'], 'other-faction'})
        self.assertEqual(result['comparisons'], expected['comparisons'])
        self.assertEqual(result['setup_comparisons'], expected['setup_comparisons'])

    def test_streamed_tables_survive_empty_selected_faction_and_match_reference(self):
        for faction in ('tinkeroids', 'not-observed'):
            for kind in PLOTS:
                with self.subTest(faction=faction, kind=kind):
                    filters = {'ruleset': 'lost-fleet', 'lf_2p_4qic_mode': 'include-both',
                               'faction': faction, 'plot': kind}
                    actual = streaming_cohort.statistics(iter(self.batches), filters, 'test')
                    expected = report(self.dataset, filters)
                    self.assert_equivalent(actual, expected)
                    self.assertGreater(len(actual['comparisons']), 1)
                    if faction == 'not-observed':
                        self.assertEqual(actual['samples'], 0)
                        self.assertEqual(actual['plots'][kind]['cells'], [])


class ComparisonApiTests(unittest.TestCase):
    setUp = base_fixtures.BaseCohortTests.setUp
    request = base_fixtures.BaseCohortTests.request
    assert_equivalent = streaming_fixtures.StreamingTests.assert_equivalent

    def test_base_sql_loads_other_factions_for_every_plot_but_export_stays_selected(self):
        for kind in PLOTS:
            with self.subTest(kind=kind):
                filters = {'ruleset': 'base', 'faction': 'terrans', 'faction_variant': 'standard', 'plot': kind}
                status, body = self.request('/cohort/api/stats', filters)
                self.assertEqual(status, '200 OK')
                actual = json.loads(body)
                expected = report(base_cohort.dataset(self.db, {}), filters)
                self.assert_equivalent(actual, json.loads(json.dumps(expected)))
                self.assertEqual(len(actual['comparisons']), 2)
                self.assertEqual(actual['samples'], 1)
                for rows in actual['setup_comparisons'].values():
                    self.assertEqual(len(rows), 2)
                _, exported = self.request('/cohort/api/export', filters)
                records = list(csv.DictReader(io.StringIO(exported.decode())))
                self.assertEqual([r['faction'] for r in records], ['terrans'])

    def test_base_empty_graph_preserves_eligible_other_faction_tables(self):
        filters = {'ruleset': 'base', 'faction': 'terrans', 'faction_variant': 'standard',
                   'plot': 'basic-tech-score', 'min_elo': '200'}
        _, body = self.request('/cohort/api/stats', filters)
        actual = json.loads(body)
        self.assertEqual(actual['samples'], 0)
        self.assertEqual(actual['plots']['basic-tech-score']['cells'], [])
        self.assertEqual([r['faction'] for r in actual['comparisons']], ['xenos'])
        self.assertTrue(all([r['faction'] for r in rows] == ['xenos']
                            for rows in actual['setup_comparisons'].values()))
        _, body = self.request('/cohort/api/stats', {**filters, 'min_elo': '99999'})
        self.assertEqual(json.loads(body)['comparisons'], [])
