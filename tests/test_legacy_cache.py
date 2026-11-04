import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gaia_stats.eligibility import POLICY_VERSION
from gaia_stats.score_basis import SCORE_BASIS_VERSION
from gaia_stats.legacy_cache import build_cache, cache_response
from gaia_stats.wsgi import Application


class LegacyCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.build = self.cache / 'build-test'
        (self.build / 'plots').mkdir(parents=True)
        (self.build / 'data').mkdir()
        (self.cache / 'current.json').write_text('{"build":"build-test"}')
        self.catalog = {'schema_version': 1, 'eligibility_policy': POLICY_VERSION, 'score_basis_version': SCORE_BASIS_VERSION, 'ruleset': 'base', 'datasets': {'4': {
            'games': 1, 'available': {'terrans': ['basic-tech-frequency']}}}}
        (self.build / 'manifest.json').write_text(json.dumps(self.catalog))
        (self.build / 'plotly.min.js').write_text('window.Plotly={};')
        (self.build / 'data/4.csv').write_text('num_players,example\n4,original\n')
        (self.build / 'plots/4-terrans-basic-tech-frequency.html').write_text(
            '<html><script src="/classic/assets/plotly.min.js"></script><p>Cached chart</p></html>')
        self.app = Application(self.root / 'analysis.json', classic_cache=self.cache)

    def request(self, path, query='', method='GET'):
        captured = {}
        body = b''.join(self.app({'PATH_INFO': path, 'QUERY_STRING': query, 'REQUEST_METHOD': method},
                                lambda status, headers: captured.update(status=status, headers=dict(headers))))
        return captured, body

    def test_home_selectors_and_wrapper_controls(self):
        response, body = self.request('/classic/')
        self.assertEqual(response['status'], '200 OK')
        for control in ('id="players"', 'id="faction"', 'id="plot"', 'New Tab', 'Here', 'Download data',
                        'SMS reminders require', 'Comparison unavailable'):
            self.assertIn(control.encode(), body)
        response, body = self.request('/classic/view_plot', 'players=4&faction=terrans&plot=basic-tech-frequency')
        self.assertEqual(response['status'], '200 OK')
        for control in ('Fullscreen', 'Download', 'Copy Embed Link', 'About this plot'):
            self.assertIn(control.encode(), body)

    def test_catalog_chart_download_and_missing_player_count(self):
        response, body = self.request('/classic/api/catalog')
        self.assertEqual(json.loads(body), self.catalog)
        with patch('gaia_stats.legacy_plots.make_plot', side_effect=AssertionError('No request-time plotting')):
            response, body = self.request('/classic/plot', 'players=4&faction=terrans&plot=basic-tech-frequency')
        self.assertEqual(response['status'], '200 OK')
        self.assertIn(b'Cached chart', body)
        response, body = self.request('/classic/data/4.csv')
        self.assertEqual(body, (self.build / 'data/4.csv').read_bytes())
        self.assertIn('attachment;', response['headers']['Content-Disposition'])
        response, _ = self.request('/classic/data/2.csv')
        self.assertEqual(response['status'], '404 Not Found')

    def test_original_chart_csv_and_wrapper_routes(self):
        response, body = self.request('/4p/base_tech_analysis/taken_freq/terrans.html')
        self.assertEqual(response['status'], '200 OK')
        self.assertIn(b'Cached chart', body)
        response, body = self.request('/data/four_players_data.csv')
        self.assertEqual(response['status'], '200 OK')
        self.assertIn(b'4,original', body)
        response, body = self.request('/view_plot/index.html',
                                      'plot_src=/4p/base_tech_analysis/taken_freq/terrans.html')
        self.assertEqual(response['status'], '200 OK')
        self.assertIn(b"query.has('plot_src')", body)

    def test_plot_download_embeds_javascript_for_standalone_use(self):
        response, body = self.request('/classic/plot', 'players=4&faction=terrans&plot=basic-tech-frequency&download=1')
        self.assertEqual(response['status'], '200 OK')
        self.assertIn(b'window.Plotly={};', body)
        self.assertNotIn(b'src="/classic/assets/', body)
        self.assertIn('attachment;', response['headers']['Content-Disposition'])

    def test_unstamped_caches_never_serve_legacy_aggregates_or_csv(self):
        self.catalog.pop('eligibility_policy')
        (self.build / 'manifest.json').write_text(json.dumps(self.catalog))
        before = {p: p.read_bytes() for p in self.build.rglob('*') if p.is_file()}
        for path, query in (
            ('/classic/api/catalog', ''), ('/classic/api/comparison', ''),
            ('/classic/plot', 'players=4&faction=terrans&plot=basic-tech-frequency'),
            ('/classic/data/4.csv', ''), ('/data/four_players_data.csv', ''),
            ('/4p/base_tech_analysis/taken_freq/terrans.html', '')):
            response, body = self.request(path, query)
            self.assertEqual(response['status'], '400 Bad Request', path)
            self.assertIn(b'unavailable until rebuilt', body)
        response, body = self.request('/classic/assets/plotly.min.js')
        self.assertEqual(response['status'], '200 OK')
        self.assertEqual(body, b'window.Plotly={};')
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_current_policy_cache_without_prebid_calculation_stamp_fails_closed(self):
        self.catalog.pop('score_basis_version')
        (self.build/'manifest.json').write_text(json.dumps(self.catalog))
        for route in ('/classic/api/catalog', '/classic/data/4.csv', '/4p/base_tech_analysis/taken_freq/terrans.html'):
            response, body = self.request(route)
            self.assertEqual(response['status'], '400 Bad Request')
            self.assertIn(b'unavailable until rebuilt', body)
        self.assertEqual(self.request('/classic/assets/plotly.min.js')[0]['status'], '200 OK')

    def test_invalid_selection_and_traversal_are_rejected(self):
        for query in ('players=4&faction=../../secret&plot=basic-tech-frequency',
                      'players=5&faction=terrans&plot=basic-tech-frequency',
                      'players=4&faction=terrans&plot=unknown'):
            response, _ = self.request('/classic/plot', query)
            self.assertEqual(response['status'], '400 Bad Request')
        response, _ = self.request('/classic/data/../../secret')
        self.assertEqual(response['status'], '404 Not Found')
        (self.cache / 'current.json').write_text('{"build":"../../secret"}')
        response, _ = self.request('/classic/api/catalog')
        self.assertEqual(response['status'], '400 Bad Request')

    def test_existing_health_rulesets_and_read_only_behavior_remain(self):
        before = self.app.path.read_bytes()
        response, body = self.request('/healthz')
        self.assertEqual(json.loads(body)['player_records'], 10)
        for ruleset, games in (('base', 0), ('lost-fleet', 3)):
            response, body = self.request('/api/analysis', 'ruleset=' + ruleset)
            self.assertEqual(json.loads(body)['games'], games)
        response, _ = self.request('/classic/api/catalog', method='POST')
        self.assertEqual(response['status'], '405 Method Not Allowed')
        self.assertEqual(self.app.path.read_bytes(), before)

    def test_failed_build_leaves_published_cache_intact(self):
        original_pointer = (self.cache / 'current.json').read_bytes()
        source = self.root / 'incompatible.csv'
        source.write_text('num_players,pos_1_faction,pos_2_faction,pos_3_faction,pos_4_faction\n4,terrans,xenos,itars,nevlas\n')
        with self.assertRaises(ValueError):
            build_cache(self.cache, {4: source})
        self.assertEqual((self.cache / 'current.json').read_bytes(), original_pointer)
        self.assertEqual([p.name for p in self.cache.glob('build-*')], ['build-test'])
        self.assertEqual(json.loads(cache_response(self.cache, '/classic/api/catalog', {})[0]), self.catalog)

    def test_builder_uses_real_plot_and_publishes_complete_snapshot(self):
        from gaia_stats.legacy_plots import PLOTS
        source = Path(__file__).resolve().parents[1] / 'data/remote_four_players_data.csv'
        with patch.dict(PLOTS, {'basic-tech-frequency': PLOTS['basic-tech-frequency']}, clear=True), \
                patch('gaia_stats.legacy_cache.FACTIONS', ('terrans',)):
            catalog = build_cache(self.cache, {4: source})
        self.assertEqual(catalog['datasets']['4']['games'], 3018)
        self.assertEqual(catalog['datasets']['4']['available'], {'terrans': ['basic-tech-frequency']})
        pointer = json.loads((self.cache / 'current.json').read_text())
        self.assertNotEqual(pointer['build'], 'build-test')
        snapshot = self.cache / pointer['build']
        self.assertTrue((snapshot / 'plots/4-terrans-basic-tech-frequency.html').exists())
        import pandas as pd
        published = pd.read_csv(snapshot / 'data/4.csv')
        self.assertEqual(len(published), 3018)
        self.assertFalse(published.balance_variant.eq('more-balanced').any())
        self.assertTrue(published[[f'pos_{p}_dropped' for p in range(1, 5)]].eq(False).all(axis=None))
        from gaia_stats.base_cohort import build
        import sqlite3
        seed = self.root / 'seed.sqlite'
        build({4: source}, seed)
        with sqlite3.connect(seed) as db:
            seed_ids = {row[0] for row in db.execute('SELECT DISTINCT game_id FROM observations')}
        self.assertEqual(set(published.id), seed_ids)
        self.assertEqual(set(json.loads((snapshot/'eligible-games.json').read_text())['game_ids']), seed_ids)
        self.assertEqual(len(pd.read_csv(source)), 5687)
        self.assertEqual(catalog['datasets']['4']['excluded_games'], 2669)

    def test_download_and_seed_share_explicit_completion_rules(self):
        import csv
        import sqlite3
        from gaia_stats.base_cohort import build
        from gaia_stats.corrected_plots import complete_frame
        import pandas as pd
        source = Path(__file__).resolve().parents[1] / 'data/remote_four_players_data.csv'
        with source.open(newline='') as handle:
            template = next(row for row in csv.DictReader(handle)
                            if row['id'] not in ('', None) and
                            all(row[f'pos_{p}_dropped']=='False' and float(row[f'pos_{p}_score'])>=100
                                for p in range(1, 5)) and row.get('balance_variant')!='more-balanced')
        for players in (2, 3, 4):
            with self.subTest(players=players):
                rows=[]
                for name,flag in [('keep','False'),('dropped','True'),('blank',''),
                                  ('lowercase','false'),('upper','FALSE'),('zero','0'),('unknown','unknown')]:
                    row=dict(template,id=f'{players}-{name}',num_players=players)
                    row['pos_1_dropped']=flag
                    rows.append(row)
                missing=dict(rows[0],id=f'{players}-missing-score',pos_1_score='')
                rows.append(missing)
                path=self.root/f'completion-{players}.csv'
                with path.open('w',newline='') as handle:
                    writer=csv.DictWriter(handle,fieldnames=template.keys());writer.writeheader();writer.writerows(rows)
                before=path.read_bytes()
                seed=self.root/f'completion-{players}.sqlite'
                build({players:path},seed)
                with patch('gaia_stats.legacy_cache.FACTIONS', ()):
                    catalogue=build_cache(self.cache,{players:path})
                snapshot=self.cache/json.loads((self.cache/'current.json').read_text())['build']
                with (snapshot/'data'/f'{players}.csv').open(newline='') as handle:
                    exported=list(csv.DictReader(handle))
                with sqlite3.connect(seed) as db:
                    expected={row[0] for row in db.execute('SELECT DISTINCT game_id FROM observations')}
                self.assertEqual(expected,{f'{players}-keep'})
                self.assertEqual({row['id'] for row in exported},expected)
                self.assertEqual(catalogue['datasets'][str(players)]['games'],1)
                self.assertEqual(path.read_bytes(),before)
        # In-memory callers must not treat malformed numeric flags as False.
        frame=pd.DataFrame([dict(template, num_players=4, pos_1_dropped=flag,
                                 **{f'pos_{p}_dropped':False for p in (2,3,4)})
                            for flag in (False,True,None,0,'False')])
        self.assertEqual(len(complete_frame(frame,4)),1)

    def test_legacy_free_plots_require_recomputed_grouped_cache_not_just_new_labels(self):
        from gaia_stats.technology_locations import FREE_GROUPING_VERSION
        for kind in ('basic-tech-score', 'point-sources'):
            (self.build / 'plots' / f'4-terrans-{kind}.html').write_text('<html><body>Combined chart</body></html>')
            response, body = self.request('/classic/plot', f'players=4&faction=terrans&plot={kind}')
            self.assertEqual(response['status'], '400 Bad Request')
            self.assertIn(b'combined Free statistics', body)
        self.catalog['free_grouping_version'] = FREE_GROUPING_VERSION
        (self.build / 'manifest.json').write_text(json.dumps(self.catalog))
        for path, query in (('/classic/plot', 'players=4&faction=terrans&plot=basic-tech-score&download=1'),
                            ('/4p/base_tech_analysis/pos_on_score/terrans.html', ''),
                            ('/classic/plot', 'players=4&faction=terrans&plot=point-sources')):
            response, body = self.request(path, query)
            self.assertEqual(response['status'], '200 OK')
            self.assertIn(b'Combined chart', body)
