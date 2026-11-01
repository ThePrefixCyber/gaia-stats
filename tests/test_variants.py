import copy
import csv
import io
import json
from pathlib import Path
import unittest

from gaia_stats.analysis import normalize, select, skill_context, summarize
from gaia_stats.__main__ import response_for

FIXTURES = Path(__file__).parent / 'fixtures'


def two_player(flag='missing'):
    game = json.loads((FIXTURES / 'Proper-outpost-7588.json').read_text())
    game['slug'] += '-' + str(flag)
    if flag != 'missing':
        game['game']['options']['lostFleet2pQicTech'] = flag
        game['data']['options']['lostFleet2pQicTech'] = flag
    return game


class VariantTests(unittest.TestCase):
    def setUp(self):
        self.normal = normalize(two_player())
        self.explicit_false = normalize(two_player(False))
        self.variant = normalize(two_player(True))
        self.rows = self.normal + self.explicit_false + self.variant

    def test_missing_observation_is_distinct_from_false_with_same_effective_default(self):
        self.assertIsNone(self.normal[0]['lf_2p_4qic_observed'])
        self.assertEqual(self.normal[0]['lf_2p_4qic_sources'], {})
        self.assertIs(self.explicit_false[0]['lf_2p_4qic_observed'], False)
        self.assertIs(self.normal[0]['lf_2p_4qic_effective'], False)
        self.assertEqual(len(self.explicit_false[0]['lf_2p_4qic_sources']), 2)

    def test_conflicting_and_nonboolean_flags_rejected(self):
        conflicting = two_player(True)
        conflicting['data']['options']['lostFleet2pQicTech'] = False
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            normalize(conflicting)
        for flag in (1, 'true', None):
            with self.assertRaisesRegex(ValueError, 'Invalid'):
                normalize(two_player(flag))

    def test_enabled_flag_outside_two_player_lost_fleet_is_rejected(self):
        for filename in ('Jubilant-rover-3041.json', 'Modern-riddle-1723.json'):
            game = json.loads((FIXTURES / filename).read_text())
            game['data']['options']['lostFleet2pQicTech'] = True
            with self.assertRaisesRegex(ValueError, 'only valid for two-player'):
                normalize(game)

    def test_three_modes_and_api_csv_partition_are_consistent(self):
        dataset = {'schema_version': 1, 'rows': self.rows, 'rejected': []}
        for mode, count in (('standard-only', 4), ('include-both', 6), ('variant-only', 2)):
            filters = {'ruleset': 'lost-fleet', 'lf_2p_4qic_mode': mode}
            api = json.loads(response_for(dataset, '/api/analysis', filters)[0])
            exported = list(csv.DictReader(io.StringIO(response_for(dataset, '/api/export', filters)[0].decode())))
            self.assertEqual((api['player_records'], len(exported)), (count, count))
            self.assertEqual(api['variant_filter']['mode'], mode)
            self.assertEqual(api['variant_filter']['excluded_records_before_other_filters'], 6 - count)
            self.assertEqual({row['game_id'] for row in exported}, {row['game_id'] for row in api['rows']})
        self.assertEqual(len(select(self.rows, {'ruleset': 'lost-fleet'})), 4)

    def test_elo_thresholds_use_selected_mode_and_missing_ratings_remain_missing(self):
        rows = copy.deepcopy(self.rows)
        rows[0]['elo'] = None
        for row in rows[-2:]:
            row['elo'] = 9999
        normal = skill_context(rows, {'ruleset': 'lost-fleet', 'skill': 'top'})
        inclusive = skill_context(rows, {'ruleset': 'lost-fleet', 'skill': 'top', 'lf_2p_4qic_mode': 'include-both'})
        self.assertLess(normal['thresholds'][2], inclusive['thresholds'][2])
        self.assertEqual(normal['rated_counts'][2], 3)
        self.assertIn(rows[0], select(rows, {'ruleset': 'lost-fleet'}))
        custom = select(rows, {'ruleset': 'lost-fleet', 'skill': 'custom', 'min_elo': '0'})
        self.assertTrue(all(row['elo'] is not None for row in custom))
        game = two_player()
        game['players'][0].pop('elo', None)
        self.assertIsNone(normalize(game)[0]['elo'])

    def test_variant_only_excludes_non_two_player_lf_and_preserves_base(self):
        four = normalize(json.loads((FIXTURES / 'Jubilant-rover-3041.json').read_text()))
        base = normalize(json.loads((FIXTURES / 'Modern-riddle-1723.json').read_text()))
        self.assertEqual(len(select(self.rows + four, {'ruleset': 'lost-fleet', 'lf_2p_4qic_mode': 'variant-only'})), 2)
        for mode in ('standard-only', 'include-both', 'variant-only'):
            self.assertEqual(select(base, {'ruleset': 'base', 'lf_2p_4qic_mode': mode}), base)
        with self.assertRaises(ValueError):
            select(self.rows, {'ruleset': 'lost-fleet', 'lf_2p_4qic_mode': 'unexpected'})

    def test_include_both_does_not_merge_variant_summary_groups(self):
        grouped = summarize(select(self.rows, {'ruleset': 'lost-fleet', 'lf_2p_4qic_mode': 'include-both'}))
        self.assertEqual({group['lf_2p_4qic_effective'] for group in grouped}, {True, False})

    def test_existing_layout_auction_and_faction_variant_filters_compose(self):
        target = self.variant[0]
        filters = {'ruleset': 'lost-fleet', 'lf_2p_4qic_mode': 'variant-only',
                   'layout': target['layout'], 'auction': target['auction'],
                   'faction_variant': target['faction_variant'], 'faction': target['faction']}
        self.assertEqual(select(self.rows, filters), [target])


    def test_deployment_health_counts_include_variants_even_when_default_views_exclude(self):
        import importlib.util
        import tempfile
        from urllib.parse import urlsplit, parse_qs
        from gaia_stats.__main__ import atomic_json
        from gaia_stats.wsgi import Application
        spec = importlib.util.spec_from_file_location('variant_health', FIXTURES.parents[1] / 'deploy/verify-health.py')
        health = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(health)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'analysis.json'
            atomic_json(path, {'schema_version': 1, 'rows': self.rows, 'rejected': []})
            app = Application(path)
            def fetch(url):
                parsed = urlsplit(url)
                status = []
                body = b''.join(app({'PATH_INFO': parsed.path, 'QUERY_STRING': parsed.query, 'REQUEST_METHOD': 'GET'},
                                    lambda code, headers: status.append(code)))
                self.assertEqual(status, ['200 OK'])
                return json.loads(body)
            health.verify(app.commit, fetch)
