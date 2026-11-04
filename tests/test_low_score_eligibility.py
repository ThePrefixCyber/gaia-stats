from gaia_stats.release_data import load_dataset
"""Pre-bid-score game eligibility, source preservation and policy migration."""
import copy
import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gaia_stats import eligibility
from gaia_stats.analysis import normalize, select, skill_context
from gaia_stats.archive import collect
from gaia_stats.base_cohort import build as build_base, convert, dataset as base_dataset
from gaia_stats.cohort import enrich, report, export
from gaia_stats.releases import current, digest, known_exclusions, validate
from gaia_stats.wsgi import Application, ReleaseApplication
from test_archive import FakeClient, game
from test_corrected_plots import game as wide_game
import test_game_eligibility as shared
from test_game_eligibility import request


def scored(payload, score, position=0):
    """Change the final result and reconcile its ledger, without adding back bids."""
    payload = copy.deepcopy(payload)
    old = payload['players'][position]['score']
    payload['players'][position]['score'] = score
    payload['data']['advancedLog'].append({'player': position, 'phase': 'endGame',
        'changes': {'spend': {'vp': score-old}}})
    return payload


class LowScoreTests(unittest.TestCase):
    def test_strict_threshold_prebid_score_and_missing_distinction(self):
        for mode in (False, True):
            for score in (-1, 0, 25, 99, 99.9, 100, 100.1, 150):
                raw = scored(game('threshold', mode), score)
                with self.subTest(mode=mode, score=score):
                    self.assertEqual(eligibility.excluded_export(raw), score < 100)
                    rows = normalize(raw)
                    self.assertTrue(all(row['score_verified'] for row in rows))
                    filters = {'ruleset': rows[0]['ruleset']}
                    self.assertEqual(len(select(rows, filters)), 0 if score < 100 else 4)
            running = scored(game('running', mode), 25); running['status'] = 'started'
            self.assertFalse(eligibility.excluded_export(running))
            # Printed 75 with an actual -50 auction event means 125 before bids.
            raw = scored(game('bid', mode), 75)
            raw['data']['players'][0]['data']['bid'] = 50
            raw['data']['advancedLog'].append({'player': 0, 'phase': 'endGame',
                'changes': {'bid': {'vp': -50}, 'spend': {'vp': 50}}})
            self.assertFalse(eligibility.excluded_export(raw))
            self.assertEqual(normalize(raw)[0]['score'], 125)
            for value in (None, '', 'unknown', True, float('nan'), float('inf')):
                raw = game('missing', mode); raw['players'][0]['score'] = value
                self.assertFalse(eligibility.excluded_export(raw))
                with self.assertRaisesRegex(ValueError, 'Missing or invalid final score'):
                    normalize(raw)
            raw = game('absent', mode); del raw['players'][0]['score']
            self.assertFalse(eligibility.excluded_export(raw))
            with self.assertRaisesRegex(ValueError, 'Missing or invalid final score'):
                normalize(raw)

    def test_whole_game_before_faction_elo_qic_and_all_stats_exports(self):
        for lf in (False, True):
            keep = game('keep', lf); low = scored(game('low', lf), 25)
            kept = enrich(keep, normalize(keep)); blocked = enrich(low, normalize(low))
            blocked[0]['elo'] = 0
            for row in blocked[1:]:row['elo'] = 99999
            rows = kept + blocked
            filters = {'ruleset': kept[0]['ruleset'], 'faction': blocked[1]['faction'], 'min_elo': '1'}
            self.assertNotIn('low', {r['game_id'] for r in select(rows, filters)})
            self.assertEqual(skill_context(rows, {'ruleset': kept[0]['ruleset'], 'skill': 'top'}),
                             skill_context(kept, {'ruleset': kept[0]['ruleset'], 'skill': 'top'}))
            for qic in ('standard-only', 'include-both', 'variant-only'):
                for kind in ('advanced-tech-frequency', 'advanced-tech-score', 'basic-tech-frequency',
                             'basic-tech-score', 'basic-tech-setup-score', 'round-one-structures',
                             'round-scoring', 'final-scoring', 'point-sources'):
                    query = dict(filters, plot=kind, lf_2p_4qic_mode=qic)
                    self.assertEqual(report({'rows': rows}, query), report({'rows': kept}, query))
                    self.assertEqual(export({'rows': rows}, query), export({'rows': kept}, query))

    def test_wide_csv_threshold_ignores_missing_and_source_contributions(self):
        import pandas as pd
        games = [wide_game(identifier='keep', score=100), wide_game(identifier='low', other=25),
                 dict(wide_game(identifier='unknown'), pos_2_score=None), wide_game(identifier='negative', other=-1)]
        games[0]['pos_1_score_bid'] = -200  # contributions are not final scores
        frame = pd.DataFrame(games); original = frame.copy(deep=True)
        filtered = eligibility.eligible_frame(frame)
        self.assertEqual(set(filtered.id), {'keep', 'unknown'})
        # The invalid game is not scored as zero or recorded as below-threshold evidence.
        for value in ('', None, 'NaN', 'unknown'):
            row = dict(games[2], pos_2_score=value)
            self.assertFalse(eligibility.excluded_csv_game(row))
            row = {k: str(v) if v is not None else '' for k,v in row.items()}
            self.assertEqual(convert(row, 2), [])
        duplicate = dict(games[0], id='low')
        self.assertNotIn('low', eligibility.eligible_frame(pd.concat([frame, pd.DataFrame([duplicate])])).id.tolist())
        pd.testing.assert_frame_equal(frame, original)

    def test_csv_floor_uses_own_cost_not_misaligned_signed_source(self):
        for reported, cost, excluded in ((75, 50, False), (99, 0, True), (100, 0, False)):
            row = wide_game(identifier='own-cost', score=reported, other=150)
            row.update(pos_1_bid=cost, pos_1_score_bid=0, pos_2_score_bid=-cost)
            self.assertEqual(eligibility.excluded_csv_game(row), excluded)
        # Padded source columns are not extra players in a two-player game.
        row.update(pos_3_score=0, pos_3_bid=0, pos_4_score=0, pos_4_bid=0)
        self.assertFalse(eligibility.excluded_csv_game(row))
        row['pos_1_score'] = 25; row['pos_1_bid'] = None
        self.assertFalse(eligibility.excluded_csv_game(row))  # Unknown cost is not zero.

    def test_archive_both_modes_distinguishes_low_missing_and_retains_raw(self):
        for lf in (False, True):
            with self.subTest(lf=lf), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); mode = 'lost-fleet' if lf else 'base'
                low = scored(game('low', lf), 25); missing = game('missing', lf)
                missing['players'][0].pop('score')
                client = FakeClient({'low': low, 'missing': missing, 'boundary': scored(game('boundary', lf), 100)})
                result = collect(root, mode, client=client, max_pages=1, max_downloads=3)
                self.assertEqual((result['excluded'], result['rejected'], result['accepted']), (1, 1, 1))
                with sqlite3.connect(root/'archive.sqlite3') as db:
                    records = {slug: (status, reason) for slug, status, reason in db.execute('SELECT slug,status,reason FROM exports')}
                self.assertEqual(records['low'][0], 'excluded'); self.assertIn('below 100', records['low'][1])
                self.assertEqual(records['missing'][0], 'rejected'); self.assertIn('Missing or invalid final score', records['missing'][1])
                for slug in client.games:
                    self.assertEqual((root/mode/'raw'/(slug+'.json')).read_bytes(), json.dumps(client.games[slug], indent=1).encode())


class LowScorePublicationTests(unittest.TestCase):
    setUp = shared.PublicationEligibilityTests.setUp
    publish = shared.PublicationEligibilityTests.publish
    mark_merged_release = shared.PublicationEligibilityTests.mark_merged_release
    # Reuse fixture preparation without rerunning the variant-only tests.
    def test_late_low_score_replaces_seed_and_lf_then_persists_across_rollback(self):
        first = self.publish(); self.mark_merged_release(); prior = current(self.store)
        old_files = {path.name: path.read_bytes() for path in prior.iterdir()}
        for mode, slug in (('base', 'seed-unknown'), ('lost-fleet', 'lf-keep')):
            client = FakeClient({slug: scored(game(slug, mode == 'lost-fleet'), 25)})
            collect(self.archive, mode, client=client, max_pages=1, max_downloads=1)
        result = self.publish(allow_static_base_migration=True)
        self.assertEqual(result['datasets'], {'base': {'games': 1, 'records': 2}, 'lost-fleet': {'games': 0, 'records': 0}})
        self.assertTrue({'seed-unknown', 'lf-keep'} <= known_exclusions(self.store))
        self.assertEqual({path.name: path.read_bytes() for path in prior.iterdir()}, old_files)
        with self.assertRaisesRegex(ValueError, 'verified source evidence'):
            validate(prior, known_exclusions=known_exclusions(self.store))
        self.assertEqual(self.publish()['release'], result['release'])

    def test_v1_release_and_registry_migrate_and_old_queries_filter_low_game(self):
        self.publish(); prior = current(self.store)
        with sqlite3.connect(prior/'base.sqlite') as db:
            payload = json.loads(db.execute('SELECT payload FROM observations WHERE game_id="seed-unknown" AND faction="xenos"').fetchone()[0])
            payload['score'] = 25
            db.execute('UPDATE observations SET payload=? WHERE game_id="seed-unknown" AND faction="xenos"', (json.dumps(payload),))
        data = load_dataset(prior/'lost-fleet.json'); data.pop('storage',None); data.pop('games',None); data['rows'][0]['score'] = 25
        (prior/'lost-fleet.json').write_text(json.dumps(data))
        manifest = json.loads((prior/'manifest.json').read_text()); manifest['eligibility_policy'] = 1; manifest['inputs']['eligibility_policy'] = 1
        manifest['sha256'] = {name: digest(prior/name) for name in ('base.sqlite', 'lost-fleet.json')}
        (prior/'manifest.json').write_text(json.dumps(manifest))
        (self.store/'exclusions.json').write_text(json.dumps({'eligibility_policy': 1, 'game_ids': ['seed-block']}))
        self.assertEqual(known_exclusions(self.store), {'seed-block'})
        app = ReleaseApplication(self.store)
        for mode, count in (('base', 2), ('lost-fleet', 0)):
            status, body = request(app, '/cohort/api/stats', ruleset=mode, faction='terrans', min_elo='1')
            self.assertEqual(status, '200 OK')
            self.assertNotIn('seed-unknown', json.loads(body)['record_ids'])
            status, body = request(app, '/cohort/api/export', ruleset=mode)
            self.assertEqual(status, '200 OK'); self.assertNotIn(b'seed-unknown', body); self.assertNotIn(b'lf-keep', body)
        result = self.publish()
        self.assertEqual(result['eligibility_policy'], eligibility.POLICY_VERSION)
        self.assertEqual(result['datasets']['base']['games'], 1)
        self.assertEqual(result['datasets']['lost-fleet']['games'], 0)
        self.assertEqual(result['excluded_games'], 3)

    def test_obsolete_net_policy_cannot_reintroduce_wrong_tombstones(self):
        self.publish(); prior = current(self.store)
        manifest_path = prior/'manifest.json'; original = manifest_path.read_bytes()
        manifest = json.loads(original); manifest['eligibility_policy'] = 2
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'net-score eligibility policy 2'):
            validate(prior)
        manifest_path.write_bytes(original)
        registry_path = self.store/'exclusions.json'; registry = registry_path.read_bytes()
        registry_path.write_text(json.dumps({'eligibility_policy': 2, 'game_ids': ['seed-unknown']}))
        with self.assertRaisesRegex(ValueError, 'net-score eligibility policy 2'):
            known_exclusions(self.store)
        registry_path.write_bytes(registry)
        with sqlite3.connect(self.seed) as db:
            db.execute("UPDATE metadata SET value='2' WHERE key='eligibility_policy'")
        with self.assertRaisesRegex(ValueError, 'net-score eligibility policy 2'):
            self.publish()
        self.assertEqual(current(self.store), prior)
        self.assertEqual(registry_path.read_bytes(), registry)

    def test_changed_seed_score_removes_old_game_even_when_new_seed_skips_it(self):
        self.publish()
        with self.source.open() as handle:rows = list(csv.DictReader(handle))
        next(row for row in rows if row['id'] == 'seed-unknown')['pos_2_score'] = '25'
        with self.source.open('w') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        build_base({2: self.source}, self.seed)
        self.assertEqual(self.publish()['datasets']['base']['games'], 1)
        self.assertIn('seed-unknown', known_exclusions(self.store))

    def test_rebuilt_seed_restores_static_csv_and_archives_raw_overlay(self):
        self.publish(); prior = current(self.store)
        with sqlite3.connect(prior/'base.sqlite') as db:
            old = json.loads(db.execute('SELECT payload FROM observations WHERE game_id="seed-unknown" AND faction="terrans"').fetchone()[0])
            for key in ('score_basis_version', 'reported_score', 'bid_delta', 'bid_cost'):
                old.pop(key, None)
            old.update(score=100, bid=-999, score_basis='CSV final score; ledger not reverified')
            db.execute('UPDATE observations SET payload=? WHERE game_id="seed-unknown" AND faction="terrans"', (json.dumps(old),))
            # A rich raw result must survive even when only seed input is available.
            for faction, payload in db.execute('SELECT faction,payload FROM observations WHERE game_id="seed-standard"').fetchall():
                row = json.loads(payload); row.update(score=777, reported_score=777, bid_delta=0,
                    normalization_version=3, vp_sources_raw={'initial': 10, 'spend': 767})
                db.execute('UPDATE observations SET payload=? WHERE game_id="seed-standard" AND faction=?', (json.dumps(row), faction))
        manifest = json.loads((prior/'manifest.json').read_text()); manifest['inputs'].pop('eligibility_policy')
        manifest['sha256']['base.sqlite'] = digest(prior/'base.sqlite')
        (prior/'manifest.json').write_text(json.dumps(manifest))
        old_bytes = (prior/'base.sqlite').read_bytes()
        result = self.publish()
        with sqlite3.connect(current(self.store)/'base.sqlite') as db:
            rows = [json.loads(p[0]) for p in db.execute('SELECT payload FROM observations')]
        repaired = next(row for row in rows if row['game_id'] == 'seed-unknown' and row['faction'] == 'terrans')
        self.assertEqual(repaired['score_basis_version'], 'prebid-v1')
        self.assertEqual(repaired['score'], 120)
        self.assertTrue(all(row['score'] != 777 for row in rows if row['game_id'] == 'seed-standard'))
        self.assertTrue(all('vp_sources_raw' not in row for row in rows))
        self.assertEqual((prior/'base.sqlite').read_bytes(), old_bytes)
        self.assertNotEqual(result['release'], prior.name)


class LowScoreClassicTests(unittest.TestCase):
    def test_low_score_csv_and_charts_use_whole_game_before_faction(self):
        import plotly.graph_objects as go
        from gaia_stats.legacy_cache import build_cache, cache_response
        from gaia_stats.legacy_plots import PLOTS
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'2.csv'
            rows = [wide_game(identifier='keep', score=100, other=100),
                    wide_game(identifier='low', score=200, other=25)]
            with source.open('w') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            original = source.read_bytes()
            observed = []
            def plot(kind, frame, **kwargs):
                observed.append((set(frame.id), {row['game'] for row in kwargs['_observations']}))
                return go.Figure()
            with patch('gaia_stats.legacy_plots.make_plot', side_effect=plot), \
                 patch('gaia_stats.legacy_cache.FACTIONS', ('terrans',)), \
                 patch.dict(PLOTS, {'basic-tech-score': PLOTS['basic-tech-score']}, clear=True):
                result = build_cache(root/'cache', {2: source})
            self.assertEqual(observed, [({'keep'}, {'keep'})])
            self.assertEqual(result['datasets']['2']['games'], 1)
            self.assertNotIn(b'low', cache_response(root/'cache', '/classic/data/2.csv', {})[0])
            self.assertEqual(source.read_bytes(), original)
            # A formerly valid policy-1 cache is not safe under the score policy.
            pointer = json.loads((root/'cache/current.json').read_text())
            manifest = root/'cache'/pointer['build']/'manifest.json'
            old = json.loads(manifest.read_text()); old['eligibility_policy'] = 1
            manifest.write_text(json.dumps(old))
            for route in ('/classic/api/catalog', '/classic/data/2.csv', '/2p/base_tech_analysis/pos_on_score/terrans.html'):
                with self.assertRaisesRegex(ValueError, 'unavailable until rebuilt'):
                    cache_response(root/'cache', route, {})
            self.assertTrue(cache_response(root/'cache', '/classic/assets/plotly.min.js', {})[0])
