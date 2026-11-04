import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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
        self.catalog = {'schema_version': 1, 'eligibility_policy': 1, 'ruleset': 'base', 'datasets': {'4': {
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
        self.assertEqual(catalog['datasets']['4']['games'], 4292)
        self.assertEqual(catalog['datasets']['4']['available'], {'terrans': ['basic-tech-frequency']})
        pointer = json.loads((self.cache / 'current.json').read_text())
        self.assertNotEqual(pointer['build'], 'build-test')
        snapshot = self.cache / pointer['build']
        self.assertTrue((snapshot / 'plots/4-terrans-basic-tech-frequency.html').exists())
        import pandas as pd
        published = pd.read_csv(snapshot / 'data/4.csv')
        self.assertEqual(len(published), 4292)
        self.assertFalse(published.balance_variant.eq('more-balanced').any())
        self.assertEqual(len(pd.read_csv(source)), 5687)
        self.assertEqual(catalog['datasets']['4']['excluded_games'], 1395)
