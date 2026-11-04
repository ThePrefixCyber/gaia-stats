"""Optional real-browser regressions: python tests/browser/test_cohort_client.py -v.

Requires Playwright, Chromium, and Plotly (from requirements-web.txt). Set
CHROMIUM_EXECUTABLE and PLOTLY_JS when these are not on their usual paths.
Fixtures only: no requests to production or external sites.
"""
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gaia_stats.analysis import normalize
from gaia_stats.cohort import enrich, response, PLOTS
from playwright.sync_api import sync_playwright


class CohortBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = []
        for name in ('Modern-riddle-1723.json', 'Jubilant-rover-3041.json'):
            game = json.loads((ROOT / 'tests/fixtures' / name).read_text())
            rows.extend(enrich(game, normalize(game)))
        cls.dataset = {'rows': rows, 'scope': 'Browser regression fixtures'}
        plotly = os.environ.get('PLOTLY_JS')
        if plotly:
            cls.plotly = Path(plotly).read_bytes()
        else:
            from plotly.offline import get_plotlyjs
            cls.plotly = get_plotlyjs().encode()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_EXECUTABLE', '/usr/bin/chromium'),
            headless=True, args=['--no-sandbox'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.requests = []
        self.fail_stats = False
        self.fail_plotly = False
        self.plotly_gate = threading.Event()
        self.plotly_gate.set()
        self.elo_gates = {}
        test = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                url = urlsplit(self.path)
                filters = {k: v[-1] for k, v in parse_qs(url.query).items()}
                status = 200
                if url.path == '/classic/assets/plotly.min.js':
                    test.plotly_gate.wait(15)
                    status = 503 if test.fail_plotly else 200
                    body, content_type = test.plotly, 'application/javascript'
                elif url.path == '/favicon.ico':
                    body, content_type = b'', 'image/x-icon'
                else:
                    if url.path == '/cohort/api/stats':
                        test.requests.append(filters)
                        gate = test.elo_gates.get(filters.get('min_elo'))
                        if gate:
                            gate.wait(15)
                    if url.path == '/cohort/api/stats' and test.fail_stats:
                        status, body, content_type = 503, b'{"error":"Temporary test failure"}', 'application/json'
                    else:
                        body, content_type = response(test.dataset,
                            '/cohort/' if url.path == '/' else url.path, filters)
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Superseded requests are intentionally aborted.
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 1000})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.plotly_gate.set()
        for gate in self.elo_gates.values():
            gate.set()
        self.context.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.assertEqual(self.errors, [])

    def open(self, rendered=True):
        self.page.goto(f'http://127.0.0.1:{self.server.server_port}/', wait_until='domcontentloaded')
        self.ready()
        if rendered:
            self.page.wait_for_function("document.getElementById('chart').data?.length > 0")

    def ready(self):
        self.page.wait_for_function("document.getElementById('status').textContent.includes(' games · ')")

    def select_plot(self, kind):
        self.page.select_option('#plot', kind)
        self.page.wait_for_function("kind => result?.plots[kind] && document.getElementById('chart').getAttribute('aria-busy') === 'false'", arg=kind)

    def test_statistics_arrive_before_delayed_plotly(self):
        self.plotly_gate.clear()
        self.open(rendered=False)
        self.assertFalse(self.page.evaluate('Boolean(window.Plotly)'))
        self.assertIn('Loading chart library', self.page.locator('#chart').inner_text())
        self.assertGreater(self.page.locator('#comparison tbody tr').count(), 0)
        self.plotly_gate.set()
        self.page.wait_for_function("document.getElementById('chart').data?.length > 0")

    def test_cached_views_reuse_tables_and_apply_refreshes(self):
        self.open()
        self.page.evaluate("window.initialTable=document.querySelector('#comparison table')")
        self.assertEqual(len(self.requests), 1)
        self.select_plot('advanced-tech-score')
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.page.evaluate("initialTable===document.querySelector('#comparison table')"))
        self.select_plot('round-scoring')
        self.assertEqual(len(self.requests), 2)
        self.select_plot('advanced-tech-frequency')
        self.assertEqual(len(self.requests), 2)
        self.page.click('#filters button')
        self.ready()
        self.assertEqual(len(self.requests), 3)
        self.assertIn('advanced-tech-frequency', self.page.locator('#csv').get_attribute('href'))

    def test_duplicate_clicks_and_stale_response_do_not_replace_newer_selection(self):
        self.open()
        gate = self.elo_gates['200'] = threading.Event()
        self.page.fill('[name=min_elo]', '200')
        self.page.click('#filters button')
        self.page.wait_for_function("document.getElementById('chart').getAttribute('aria-busy') === 'true'")
        self.page.click('#filters button')
        self.assertEqual(sum(r.get('min_elo') == '200' for r in self.requests), 1)
        self.assertIsNone(self.page.locator('#csv').get_attribute('href'))
        self.assertGreater(self.page.locator('#comparison tbody tr').count(), 0)
        self.page.fill('[name=min_elo]', '99999')
        self.page.click('#filters button')
        self.ready()
        gate.set()
        self.page.wait_for_timeout(100)
        self.assertTrue(self.page.locator('#status').inner_text().startswith('0 games'))
        self.assertIn('No observations', self.page.locator('#chart').inner_text())
        self.assertIn('min_elo=99999', self.page.locator('#csv').get_attribute('href'))

    def test_invalid_elo_cancels_pending_work_before_native_submit_validation(self):
        self.open()
        for submit in ('click', 'requestSubmit'):
            gate = self.elo_gates['200'] = threading.Event()
            self.page.fill('[name=min_elo]', '200')
            self.page.click('#filters button')
            self.page.wait_for_function("document.getElementById('chart').getAttribute('aria-busy') === 'true'")
            self.page.fill('[name=min_elo]', '0')
            if submit == 'click':
                self.page.click('#filters button')
            else:
                self.page.locator('#filters').evaluate('(form) => form.requestSubmit()')
            self.assertEqual(self.page.locator('#chart').get_attribute('aria-busy'), 'false')
            self.assertIn('positive whole-number Elo', self.page.locator('#status').inner_text())
            self.assertTrue(self.page.locator('#elo-error').is_visible())
            self.assertTrue(self.page.locator('[name=min_elo]').evaluate('(field) => Boolean(field.validationMessage)'))
            self.assertIsNone(self.page.locator('#csv').get_attribute('href'))
            gate.set()
            self.page.wait_for_timeout(100)
            self.assertIn('positive whole-number Elo', self.page.locator('#status').inner_text())
            self.assertIsNone(self.page.locator('#csv').get_attribute('href'))
            self.assertFalse(any(r.get('min_elo') == '0' for r in self.requests))
            self.page.fill('[name=min_elo]', '')
            self.page.click('#filters button')
            self.ready()
            self.assertFalse(self.page.locator('#elo-error').is_visible())
            self.assertIsNotNone(self.page.locator('#csv').get_attribute('href'))

    def test_mode_switch_cancels_pending_base_selection(self):
        self.open()
        gate = self.elo_gates['200'] = threading.Event()
        self.page.fill('[name=min_elo]', '200')
        self.page.click('#filters button')
        self.page.select_option('#mode', 'lost-fleet')
        self.ready()
        gate.set()
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate('result.ruleset'), 'lost-fleet')
        self.assertIn('ruleset=lost-fleet', self.page.locator('#csv').get_attribute('href'))
        self.page.select_option('#mode', 'base')
        self.page.select_option('#mode', 'lost-fleet')
        self.ready()
        self.assertEqual(self.page.evaluate('result.ruleset'), 'lost-fleet')

    def test_library_failure_keeps_tables_and_api_failure_recovers(self):
        self.fail_plotly = True
        self.open(rendered=False)
        self.page.wait_for_function("document.getElementById('chart').textContent.includes('library unavailable')")
        self.assertGreater(self.page.locator('#comparison tbody tr').count(), 0)
        self.fail_stats = True
        self.page.click('#filters button')
        self.page.wait_for_function("document.getElementById('status').textContent === 'Temporary test failure'")
        self.assertEqual(self.page.locator('#comparison tbody tr').count(), 0)
        self.assertIsNone(self.page.locator('#csv').get_attribute('href'))
        self.assertEqual(self.page.locator('#chart').get_attribute('aria-busy'), 'false')
        self.fail_stats = False
        self.page.click('#filters button')
        self.ready()
        self.assertGreater(self.page.locator('#comparison tbody tr').count(), 0)

    def test_all_charts_render_and_expired_cache_refetches(self):
        self.open()
        for kind in PLOTS:
            self.select_plot(kind)
            if kind in ('final-scoring', 'round-scoring'):
                self.assertIn('Choose a faction', self.page.locator('#chart').inner_text())
            else:
                self.page.wait_for_function("document.getElementById('chart').data?.length > 0")
        self.assertEqual(len(self.requests), 8)  # Only paired advanced-tech views share data.
        self.page.evaluate('for(const entry of responses.values())entry.time-=RESPONSE_TTL+1')
        self.select_plot('advanced-tech-frequency')
        self.assertEqual(len(self.requests), 9)
        self.assertLessEqual(self.page.evaluate('responses.size'), 8)
        self.select_plot('round-scoring')
        screenshot = os.environ.get('COHORT_SCREENSHOT')
        if screenshot:
            self.page.locator('#chart').screenshot(path=screenshot)

    def test_actual_treemap_uses_fixed_score_landmarks(self):
        self.open()
        self.select_plot('round-one-structures')
        self.page.wait_for_function("document.getElementById('chart').data?.[0]?.type === 'treemap'")
        marker = self.page.evaluate("document.getElementById('chart').data[0].marker")
        self.assertEqual(marker['cmin'], 0)
        for value, color in ((0, '#ff3b30'), (100, '#d1d5db'), (200, '#081d58')):
            stop = (value - marker['cmin']) / (marker['cmax'] - marker['cmin'])
            self.assertIn([stop, color], marker['colorscale'])
        self.assertEqual(self.page.evaluate("document.getElementById('chart').data[0].branchvalues"), 'total')
        self.page.wait_for_function("document.querySelectorAll('#chart path.surface').length > 1")
        self.page.locator('#chart').screenshot(path='/tmp/gaia-integrated-treemap.png')


    def assert_readable_surfaces(self):
        # Native options, hidden details, chart SVG text and accessible labels all
        # count as display text. Form values and raw Plotly keys intentionally do not.
        text = self.page.evaluate("""() => [
            document.body.innerText,
            ...Array.from(document.querySelectorAll('option'), n => n.textContent),
            ...Array.from(document.querySelectorAll('[aria-label],[title]'),
                n => (n.getAttribute('aria-label') || '') + ' ' + (n.getAttribute('title') || ''))
        ].join('\\n')""")
        self.assertNotRegex(text, r"\[[^\]\n]+\]")
        self.assertNotRegex(text, r"\b(?:advtech[\w-]*|tech[0-9]+|ship-tech-[\w-]+|adv-(?:terra|nav|int|gaia|eco|sci|ext)|tech-free[123])\b|_per_")

    def test_every_cohort_view_has_clean_labels_and_raw_filter_values(self):
        self.open()
        for mode in ('base', 'lost-fleet'):
            self.page.select_option('#mode', mode)
            self.ready()
            self.page.evaluate("for(const d of document.querySelectorAll('details'))d.open=true")
            captions = self.page.locator('#techs > label').evaluate_all(
                "nodes => nodes.map(n => n.firstChild.textContent)")
            self.assertEqual(captions, ['Terra', 'Nav', 'Artificial Intelligence', 'Gaia', 'Econ', 'Sci'] +
                (['Extra'] if mode == 'lost-fleet' else []))
            self.assertEqual(self.page.locator('#techs select').evaluate_all('nodes => nodes.map(n => n.name)'),
                ['adv-terra', 'adv-nav', 'adv-int', 'adv-gaia', 'adv-eco', 'adv-sci'] +
                (['adv-ext'] if mode == 'lost-fleet' else []))
            faction = self.page.locator('[name=faction] option').nth(1).get_attribute('value')
            self.page.select_option('[name=faction]', faction)
            self.ready()
            for kind in PLOTS:
                self.select_plot(kind)
                self.page.wait_for_timeout(80)
                self.assert_readable_surfaces()
                for control in ('#scoring-view', '#frequency-view'):
                    if self.page.locator(control).is_visible():
                        choices = self.page.locator(control + ' option').evaluate_all('nodes => nodes.map(n => n.value)')
                        for choice in choices:
                            self.page.select_option(control, choice)
                            self.page.wait_for_timeout(60)
                            self.assert_readable_surfaces()
                self.page.locator('#metrics th button').first.click()
                self.assert_readable_surfaces()
            self.page.set_viewport_size({'width': 390, 'height': 844})
            self.assert_readable_surfaces()
            self.page.set_viewport_size({'width': 1280, 'height': 1000})

    def test_same_display_point_sources_remain_separate_in_real_plotly(self):
        self.open()
        self.select_plot('point-sources')
        self.page.evaluate("""() => {
            const p=result.plots['point-sources'], c=p.rank_cells.find(c=>c.samples);
            p.cells=p.rank_cells=['research','tech_score'].map((label,i)=>({...c,label,q1:5+i,median:10+i,q3:15+i,lower:1+i,upper:20+i}));
            draw();
        }""")
        for view in ('relative', 'absolute'):
            self.page.select_option('#scoring-view', view)
            self.page.wait_for_timeout(100)
            self.assertEqual(self.page.locator('#chart').evaluate("e=>e._fullLayout.xaxis._categories"),
                ['research', 'tech_score'])
            self.assertEqual(self.page.locator('#chart .xtick text').all_text_contents(), ['Research', 'Research'])
            self.assertEqual(self.page.locator('#chart .boxlayer path.box').count(), 2)
            box = self.page.locator('#chart .boxlayer path.box').first.bounding_box()
            self.page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
            self.page.wait_for_timeout(100)
            hover = self.page.locator('#chart .hoverlayer').text_content()
            self.assertIn('Research', hover)
            self.assertNotIn('tech_score', hover)
            self.assertNotIn('research', hover)
            self.assert_readable_surfaces()


if __name__ == '__main__':
    unittest.main()
