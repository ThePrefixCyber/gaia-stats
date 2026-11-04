"""One mandatory game policy across imports, live/history, queries and publication."""
import copy
import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from gaia_stats import eligibility
from gaia_stats.__main__ import ingest, response_for
from gaia_stats.analysis import normalize, select, skill_context
from gaia_stats.archive import collect
from gaia_stats.base_cohort import build as build_base, dataset as base_dataset, catalog
from gaia_stats.cohort import build as build_lf, enrich, report, response as cohort_response
from gaia_stats.releases import publish, current, validate, digest, release_lock
from gaia_stats.wsgi import Application, ReleaseApplication
from test_archive import FakeClient, game
from test_cursor_archive import CursorClient
from test_corrected_plots import game as wide_game

FIXTURES = Path(__file__).parent / 'fixtures'


def flagged(payload, value='more-balanced', source=None):
    payload = copy.deepcopy(payload)
    for container in ('game', 'data'):
        options = payload[container].setdefault('options', {})
        options.pop('factionVariant', None)
        if source is None or source == container:
            options['factionVariant'] = value
    return payload


def request(app, path, **query):
    status = []
    body = b''.join(app({'REQUEST_METHOD': 'GET', 'PATH_INFO': path,
                        'QUERY_STRING': urlencode(query)}, lambda s, h: status.append(s)))
    return status[0], body


class EligibilityTests(unittest.TestCase):
    def test_exact_metadata_locations_and_unknowns(self):
        for lf in (False, True):
            for source in (None, 'game', 'data'):
                payload = flagged(game('excluded', lf), source=source)
                with self.subTest(lf=lf, source=source):
                    self.assertTrue(eligibility.excluded_export(payload))
                    with self.assertRaises(eligibility.ExcludedGame):
                        eligibility.require_eligible_export(payload)
                    self.assertEqual(select(normalize(payload), {'ruleset': 'lost-fleet' if lf else 'base'}), [])
            for value in (None, '', 'unknown', 'standard', 'beta', 'future-variant', 'More-balanced'):
                payload = flagged(game('kept', lf), value)
                self.assertFalse(eligibility.excluded_export(payload))
                rows = normalize(payload)
                self.assertEqual(rows[0]['faction_variant'], value or 'unknown')
                self.assertEqual(rows[0]['faction_variant_sources']['game.options'], value)
                self.assertEqual(len(select(rows, {'ruleset': rows[0]['ruleset']})), 4)
            payload = game('missing', lf)
            for container in ('game', 'data'):
                payload[container]['options'].pop('factionVariant', None)
            self.assertEqual(normalize(payload)[0]['faction_variant'], 'unknown')
            self.assertFalse(eligibility.excluded_export(payload))

    def test_conflicting_explicit_variant_blocks_either_order(self):
        for source in ('game', 'data'):
            payload = flagged(game('conflict'), 'standard')
            payload[source]['options']['factionVariant'] = 'more-balanced'
            self.assertTrue(eligibility.excluded_export(payload))
            with self.assertRaisesRegex(ValueError, 'Conflicting'):
                normalize(payload)
        payload = flagged(game('invalid'), 1)
        with self.assertRaisesRegex(ValueError, 'Invalid factionVariant'):
            normalize(payload)

    def test_whole_game_exclusion_before_skill_threshold_and_explicit_filters(self):
        kept = normalize(game('kept'))
        blocked = normalize(game('blocked'))
        for row in blocked:
            row['elo'] = 10000
        blocked[0]['faction_variant_sources'] = {'data.options': 'more-balanced'}
        combined = kept + blocked
        filters = {'ruleset': 'lost-fleet', 'skill': 'top'}
        self.assertEqual(skill_context(combined, filters), skill_context(kept, filters))
        self.assertEqual(select(combined, {'ruleset': 'lost-fleet'}), kept)
        self.assertEqual(select(combined, {'ruleset': 'lost-fleet', 'faction_variant': 'more-balanced'}), [])
        self.assertEqual(len(combined), 8)  # audit caller remains unchanged

    def test_qic_filter_remains_independent_in_both_modes(self):
        qic = json.loads((FIXTURES/'cohort/Eclipsed-council-7948.json').read_text())
        normal = json.loads((FIXTURES/'Proper-outpost-7588.json').read_text())
        blocked = flagged(qic); blocked['slug'] = 'excluded-qic'
        rows = normalize(normal) + normalize(qic) + normalize(blocked)
        for mode, count in (('standard-only', 2), ('include-both', 4), ('variant-only', 2)):
            selected = select(rows, {'ruleset': 'lost-fleet', 'lf_2p_4qic_mode': mode})
            self.assertEqual(len(selected), count)
            self.assertNotIn('excluded-qic', {r['game_id'] for r in selected})
            base = normalize(game('base', False)) + normalize(flagged(game('excluded-base', False)))
            self.assertEqual(len(select(base, {'ruleset': 'base', 'lf_2p_4qic_mode': mode})), 4)

    def test_api_stats_exports_and_catalog_never_expose_excluded_rows(self):
        keep = game('keep'); block = flagged(game('block'))
        rows = enrich(keep, normalize(keep)) + enrich(block, normalize(block))
        data = {'schema_version': 1, 'rows': rows, 'rejected': []}
        for route in ('/api/analysis', '/api/export', '/cohort/api/catalog', '/cohort/api/stats', '/cohort/api/export'):
            handler = response_for if route.startswith('/api/') else cohort_response
            body = handler(data, route, {'ruleset': 'lost-fleet'})[0]
            self.assertNotIn(b'more-balanced', body, route)
            self.assertNotIn(b'block', body, route)
        self.assertEqual(report(data, {'ruleset': 'lost-fleet'})['samples'], 4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'old.json'; path.write_text(json.dumps(data)); before = path.read_bytes()
            app = Application(path)
            status, raw = request(app, '/healthz')
            self.assertEqual(status, '200 OK')
            self.assertEqual(json.loads(raw)['player_records'], 4)
            self.assertEqual(path.read_bytes(), before)

    def test_both_builders_preserve_raw_and_skip_explicit_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); paths = []
            for name, payload in (('keep', game('keep')), ('base-block', flagged(game('base-block', False))),
                                  ('lf-block', flagged(game('lf-block')))):
                path = root/(name+'.json'); path.write_text(json.dumps(payload)); paths.append(path)
            before = {p: p.read_bytes() for p in paths}
            ingest(paths, root/'analysis.json')
            data = json.loads((root/'analysis.json').read_text())
            self.assertEqual({r['game_id'] for r in data['rows']}, {'keep'})
            self.assertEqual(len(data['rejected']), 2)
            data = build_lf(paths, root/'lf.json')
            self.assertEqual({r['game_id'] for r in data['rows']}, {'keep'})
            self.assertEqual(len(data['rejected']), 2)
            self.assertEqual({p: p.read_bytes() for p in paths}, before)
            # A later duplicate with explicit evidence must remove a previously kept game.
            p = root/'duplicate.json'; p.write_text(json.dumps(flagged(game('keep'))))
            other = root/'other.json'; other.write_text(json.dumps(game('other')))
            ingest([paths[0], p, other], root/'analysis.json')
            self.assertEqual({r['game_id'] for r in json.loads((root/'analysis.json').read_text())['rows']}, {'other'})

    def test_exclusion_only_rebuild_clears_old_unknown_but_invalid_input_preserves_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'only.json'; bad = root/'bad.json'
            source.write_text(json.dumps(flagged(game('only')))); bad.write_text('{}')
            for builder in (ingest, build_lf):
                target = root/(builder.__name__+'.json')
                old = {'schema_version': 1, 'rows': normalize(flagged(game('only'), 'unknown'))}
                target.write_text(json.dumps(old)); before = target.read_bytes()
                with self.assertRaises(ValueError):builder([source, bad], target)
                self.assertEqual(target.read_bytes(), before)
                builder([source], target)
                data = json.loads(target.read_text())
                self.assertEqual(data['rows'], [])
                self.assertEqual(data['excluded_game_ids'], ['only'])

    def test_corrected_plots_and_dataframe_preserve_unknown_and_remove_whole_games(self):
        import pandas as pd
        from gaia_stats.corrected_plots import observations
        from gaia_stats.legacy_plots import make_plot
        source = pd.DataFrame([dict(wide_game(identifier='standard'), balance_variant='standard'),
                               dict(wide_game(identifier='unknown'), balance_variant=None),
                               dict(wide_game(identifier='excluded', score=10000), balance_variant='more-balanced')])
        original = source.copy(deep=True)
        self.assertEqual({r['game'] for r in observations(source, 2)}, {'standard', 'unknown'})
        fig = make_plot('basic-tech-score', source, players=2, faction='terrans')
        self.assertEqual(fig.data[0].x[0], 120)
        duplicated = pd.concat([source, source.iloc[[-1]].assign(balance_variant='standard')])
        self.assertEqual(set(eligibility.eligible_frame(duplicated).id), {'standard', 'unknown'})
        pd.testing.assert_frame_equal(source, original)


class ArchiveEligibilityTests(unittest.TestCase):
    def test_live_head_and_history_base_lf_offset_cursor_raw_preserved(self):
        for mode in ('base', 'lost-fleet'):
            for pagination in ('offset', 'cursor'):
                with self.subTest(mode=mode, pagination=pagination), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    client = CursorClient(['old-block', 'old-keep'], lf=mode=='lost-fleet') if pagination=='cursor' else FakeClient({s: game(s, mode=='lost-fleet') for s in ('old-block', 'old-keep')})
                    client.games['old-block'] = flagged(client.games['old-block'])
                    result = collect(root, mode, client=client, pagination=pagination, page_size=2, max_pages=1, max_downloads=2)
                    self.assertEqual((result['accepted'], result['excluded']), (1, 1))
                    client.games['new-block'] = flagged(game('new-block', mode=='lost-fleet'), source='data')
                    client.slugs.insert(0, 'new-block')
                    if pagination=='cursor':
                        client.entries.insert(0, {'_id': 'new-block', 'endedAt': '2026-02-01T00:00:00.000Z'})
                    with sqlite3.connect(root/'archive.sqlite3') as db:
                        scans = db.execute('SELECT * FROM cursor_scans').fetchall(), db.execute('SELECT * FROM scans').fetchall()
                    head = collect(root, mode, client=client, pagination=pagination, head_only=True, page_size=2, max_pages=1, max_downloads=2)
                    self.assertEqual(head['excluded'], 1)
                    with sqlite3.connect(root/'archive.sqlite3') as db:
                        self.assertEqual(dict(db.execute('SELECT slug,status FROM exports')), {'old-block': 'excluded', 'old-keep': 'accepted', 'new-block': 'excluded'})
                        self.assertEqual((db.execute('SELECT * FROM cursor_scans').fetchall(), db.execute('SELECT * FROM scans').fetchall()), scans)
                    for slug in ('old-block', 'new-block'):
                        raw = root/mode/'raw'/(slug+'.json')
                        self.assertEqual(raw.read_bytes(), json.dumps(client.games[slug], indent=1).encode())
                        self.assertTrue((root/mode/'provenance'/(slug+'.json')).is_file())
                        self.assertFalse((root/mode/'rows'/(slug+'.json')).exists())
                    again = collect(root, mode, client=client, pagination=pagination, head_only=True, page_size=2, max_pages=1, max_downloads=2)
                    self.assertEqual(again['excluded'], 0)


class PublicationEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.store = self.root/'store'; self.seed = self.root/'seed.sqlite'; self.archive = self.root/'archive'
        self.source = self.root/'base.csv'
        games = [dict(wide_game(identifier='seed-standard'), balance_variant='standard'),
                 dict(wide_game(identifier='seed-unknown'), balance_variant=''),
                 dict(wide_game(identifier='seed-block'), balance_variant='more-balanced')]
        with self.source.open('w') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(games[0])); writer.writeheader(); writer.writerows(games)
        self.imports = build_base({2: self.source}, self.seed)
        payload = game('lf-keep'); rows = enrich(payload, normalize(payload))
        self.legacy = self.root/'legacy.json'; self.legacy.write_text(json.dumps({'schema_version': 1, 'rows': rows}))

    def publish(self):
        with release_lock(self.store):
            return publish(self.store, self.seed, self.archive, self.legacy)

    def test_csv_seed_excludes_only_explicit_and_keeps_original(self):
        self.assertEqual(self.imports[2]['accepted_games'], 2)
        self.assertEqual(self.imports[2]['rejected_games'], 1)
        self.assertIn('more-balanced', self.source.read_text())
        self.assertEqual(catalog(self.seed)['faction_variant'], ['standard', 'unknown'])
        self.assertEqual(len(base_dataset(self.seed, {})['rows']), 4)
        self.assertEqual(base_dataset(self.seed, {'faction_variant': 'more-balanced'})['rows'], [])

    def inject_old(self, path):
        """Pre-policy persisted games, with only one of their rows marked excluded."""
        with sqlite3.connect(path/'base.sqlite') as db:
            row = db.execute('SELECT * FROM observations WHERE game_id="seed-standard" LIMIT 1').fetchone()
            for faction, marker in (('terrans', 'standard'), ('xenos', 'more-balanced')):
                payload = json.loads(row[-1]); payload.update(game_id='old-base-block', faction=faction, faction_variant='unknown', faction_variant_sources={'data.options': marker})
                db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)', ('old-base-block', faction, 2, 99999, 'unknown', 'unknown', 'unknown', json.dumps(payload)))
        data = json.loads((path/'lost-fleet.json').read_text())
        payload = game('old-lf-block'); rows = enrich(payload, normalize(payload)); rows[0]['faction_variant'] = 'more-balanced'; data['rows'] += rows
        (path/'lost-fleet.json').write_text(json.dumps(data))
        manifest = json.loads((path/'manifest.json').read_text())
        manifest.pop('eligibility_policy', None); manifest['inputs'].pop('eligibility_policy', None)
        manifest['datasets']['base']['games'] += 1; manifest['datasets']['base']['records'] += 2
        manifest['datasets']['lost-fleet']['games'] += 1; manifest['datasets']['lost-fleet']['records'] += 4
        manifest['sha256'] = {name: digest(path/name) for name in ('base.sqlite', 'lost-fleet.json')}
        (path/'manifest.json').write_text(json.dumps(manifest))

    def test_old_release_read_guard_migration_and_rollback_preserve_archives(self):
        first = self.publish(); prior = current(self.store); self.inject_old(prior)
        original = {p.name: p.read_bytes() for p in prior.iterdir()}
        seed_bytes = self.seed.read_bytes(); legacy_bytes = self.legacy.read_bytes()
        # Old stored counts and files are verified, but health returns only safe counts.
        expected = {'base': {'games': 2, 'records': 4}, 'lost-fleet': {'games': 1, 'records': 4}}
        self.assertEqual(validate(prior)['datasets'], expected)
        for mode in ('base', 'lost-fleet'):
            app = ReleaseApplication(self.store)
            for route in ('/cohort/api/stats', '/cohort/api/export'):
                status, body = request(app, route, ruleset=mode)
                self.assertEqual(status, '200 OK')
                self.assertNotIn(b'old-base-block', body); self.assertNotIn(b'old-lf-block', body)
        second = self.publish(); self.assertNotEqual(second['release'], first['release'])
        self.assertEqual(second['datasets'], expected)
        self.assertEqual(second['eligibility_policy'], eligibility.POLICY_VERSION)
        self.assertEqual(second['excluded_games'], 3)
        self.assertEqual({p.name: p.read_bytes() for p in prior.iterdir()}, original)
        self.assertEqual(self.seed.read_bytes(), seed_bytes); self.assertEqual(self.legacy.read_bytes(), legacy_bytes)
        # Rolling back an old immutable release cannot expose its excluded records.
        (self.store/'current.json').write_text(json.dumps({'release': first['release']}))
        status, body = request(ReleaseApplication(self.store), '/healthz')
        self.assertEqual(status, '200 OK'); self.assertEqual(json.loads(body)['datasets'], expected)

    def test_backfill_resolves_unknown_as_excluded_and_preserves_other_game(self):
        self.publish(); prior = current(self.store); before = (prior/'base.sqlite').read_bytes()
        payload = flagged(game('seed-unknown', False))
        client = FakeClient({'seed-unknown': payload})
        result = collect(self.archive, 'base', client=client, max_pages=1, max_downloads=1)
        self.assertEqual(result['excluded'], 1)
        second = self.publish()
        self.assertEqual(second['datasets']['base'], {'games': 1, 'records': 2})
        self.assertEqual((prior/'base.sqlite').read_bytes(), before)
        self.assertEqual({r['game_id'] for r in base_dataset(current(self.store)/'base.sqlite', {})['rows']}, {'seed-standard'})
        self.assertTrue((self.archive/'base/raw/seed-unknown.json').exists())

    def test_all_existing_games_excluded_publishes_safe_empty_mode(self):
        self.publish()
        client = FakeClient({slug: flagged(game(slug, False))
                             for slug in ('seed-standard', 'seed-unknown')})
        collect(self.archive, 'base', client=client, max_pages=1, max_downloads=2)
        second = self.publish()
        self.assertEqual(second['datasets']['base'], {'games': 0, 'records': 0})
        self.assertEqual(second['empty_after_exclusion'], ['base'])
        self.assertEqual(base_dataset(current(self.store)/'base.sqlite', {})['rows'], [])
        self.assertEqual(self.publish()['release'], second['release'])
        self.legacy.write_text(self.legacy.read_text() + ' ')
        self.assertEqual(self.publish()['datasets']['base'], {'games': 0, 'records': 0})

    def test_builder_exclusion_metadata_survives_publication(self):
        self.publish()
        data = json.loads(self.legacy.read_text()); data['excluded_game_ids'] = ['seed-unknown']
        self.legacy.write_text(json.dumps(data))
        result = self.publish()
        self.assertEqual(result['datasets']['base']['games'], 1)
        self.assertIn('seed-block', result['excluded_game_ids'])
        self.assertIn('seed-unknown', result['excluded_game_ids'])

    def test_changed_seed_tombstones_are_read_from_current_source_not_prior_copy(self):
        self.publish()
        with self.source.open() as handle:games = list(csv.DictReader(handle))
        next(row for row in games if row['id'] == 'seed-unknown')['balance_variant'] = 'more-balanced'
        with self.source.open('w') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(games[0])); writer.writeheader(); writer.writerows(games)
        build_base({2: self.source}, self.seed)
        result = self.publish()
        self.assertEqual(result['datasets']['base']['games'], 1)
        self.assertIn('seed-unknown', result['excluded_game_ids'])

    def test_historical_accepted_archive_gets_rechecked_without_redownload(self):
        client = FakeClient({'base-block': flagged(game('base-block', False))})
        collect(self.archive, 'base', client=client, max_pages=1, max_downloads=1)
        # Old collectors called this accepted. Publication must inspect raw metadata itself.
        with sqlite3.connect(self.archive/'archive.sqlite3') as db:
            db.execute("UPDATE exports SET status='accepted'")
        self.assertEqual(self.publish()['datasets']['base']['games'], 2)
        self.assertEqual(client.exports, ['base-block'])
        self.assertTrue((self.archive/'base/raw/base-block.json').exists())

    def test_historical_rejected_raw_is_exclusion_evidence_only(self):
        self.publish()
        client = FakeClient({'seed-unknown': flagged(game('seed-unknown', False)),
                             'rejected-standard': game('rejected-standard', False)})
        collect(self.archive, 'base', client=client, max_pages=1, max_downloads=2)
        with sqlite3.connect(self.archive/'archive.sqlite3') as db:
            db.execute("UPDATE exports SET status='rejected', reason='Historical ledger rejection'")
        result = self.publish()
        self.assertEqual(result['datasets']['base'], {'games': 1, 'records': 2})
        self.assertEqual({r['game_id'] for r in base_dataset(current(self.store)/'base.sqlite', {})['rows']}, {'seed-standard'})
        self.assertEqual(client.exports, ['seed-unknown', 'rejected-standard'])

    def test_tombstones_prevent_later_unknown_reimport_and_unsafe_rollback(self):
        from gaia_stats.releases import known_exclusions
        first = self.publish(); prior = current(self.store)
        client = FakeClient({'seed-unknown': flagged(game('seed-unknown', False))})
        collect(self.archive, 'base', client=client, max_pages=1, max_downloads=1)
        self.publish()
        self.assertEqual(known_exclusions(self.store), {'seed-unknown', 'seed-block'})
        # Deliberately simulate a rollback even outside the protected CLI.
        (self.store/'current.json').write_text(json.dumps({'release': first['release']}))
        status, body = request(ReleaseApplication(self.store), '/cohort/api/export', ruleset='base')
        self.assertEqual(status, '503 Service Unavailable'); self.assertIn(b'verified source evidence', body)
        with self.assertRaisesRegex(ValueError, 'verified source evidence'):
            validate(prior, known_exclusions=known_exclusions(self.store))
        # Publishing from the rejected rollback can recover without modifying it.
        self.assertEqual(self.publish()['datasets']['base']['games'], 1)
        # A legacy unknown copy cannot resurrect a game whose raw evidence disappears.
        unknown = flagged(game('seed-unknown', False), 'unknown')
        data = json.loads(self.legacy.read_text()); data['rows'] += normalize(unknown)
        self.legacy.write_text(json.dumps(data))
        with sqlite3.connect(self.archive/'archive.sqlite3') as db:
            db.execute("UPDATE exports SET status='pending'")
        self.assertEqual(self.publish()['datasets']['base']['games'], 1)

    def test_registry_swap_interruption_fails_closed_and_recovers(self):
        from gaia_stats.__main__ import atomic_json
        self.publish(); prior = current(self.store); app = ReleaseApplication(self.store)
        self.assertEqual(request(app, '/healthz')[0], '200 OK')
        client = FakeClient({'seed-unknown': flagged(game('seed-unknown', False))})
        collect(self.archive, 'base', client=client, max_pages=1, max_downloads=1)
        def interrupt(path, payload):
            atomic_json(path, payload)
            if path == self.store/'exclusions.json':raise RuntimeError('after registry before pointer')
        with patch('gaia_stats.releases.atomic_json', side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, 'after registry'):self.publish()
        self.assertEqual(current(self.store), prior)
        self.assertEqual(request(app, '/healthz')[0], '503 Service Unavailable')
        self.assertEqual(self.publish()['datasets']['base']['games'], 1)
        self.assertEqual(request(app, '/healthz')[0], '200 OK')

    def test_policy_stamped_release_rejects_tampered_excluded_records(self):
        self.publish(); prior = current(self.store); self.inject_old(prior)
        manifest = json.loads((prior/'manifest.json').read_text()); manifest['eligibility_policy'] = eligibility.POLICY_VERSION
        (prior/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Excluded game'):
            validate(prior)

    def test_refresh_download_budget_counts_excluded_head_games(self):
        from gaia_stats.refresh import run
        self.publish()
        def collected(directory, mode, **kwargs):
            return dict(listing_error=None, retry=0, accepted=0, rejected=0, excluded=2 if kwargs.get('head_only') else 0)
        with patch('gaia_stats.refresh.collect', side_effect=collected) as collect_mock:
            run(self.store, self.seed, self.archive, self.legacy, max_downloads=3)
        for call in collect_mock.call_args_list:
            if not call.kwargs.get('head_only'):
                self.assertEqual(call.kwargs['max_downloads'], 1)


class ClassicEligibilityTests(unittest.TestCase):
    def test_global_csv_evidence_and_new_raw_exclusions_cannot_leak_cached_games(self):
        import plotly.graph_objects as go
        from gaia_stats.legacy_cache import build_cache, cache_response
        from gaia_stats.legacy_plots import PLOTS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); csvs = {}
            for players in (2, 3):
                path = root/f'{players}.csv'; csvs[players] = path
                with path.open('w') as handle:
                    writer = csv.writer(handle)
                    writer.writerow(['id', 'num_players', 'balance_variant'] + [f'pos_{p}_faction' for p in range(1, players+1)])
                    writer.writerow(['same', players, 'more-balanced' if players == 2 else ''] + ['terrans']*players)
                    writer.writerow([f'keep{players}', players, ''] + ['terrans']*players)
            before = {p: p.read_bytes() for p in csvs.values()}
            def build(excluded=()):
                with patch('gaia_stats.corrected_plots.observations', return_value=[]), \
                     patch('gaia_stats.legacy_plots.make_plot', return_value=go.Figure()), \
                     patch('gaia_stats.legacy_cache.FACTIONS', ('terrans',)), \
                     patch.dict(PLOTS, {'basic-tech-score': PLOTS['basic-tech-score']}, clear=True):
                    return build_cache(root/'cache', csvs, excluded_game_ids=excluded)
            result = build()
            self.assertEqual([result['datasets'][str(p)]['games'] for p in (2, 3)], [1, 1])
            for p in (2, 3):
                body = cache_response(root/'cache', f'/classic/data/{p}.csv', {})[0]
                self.assertNotIn(b'same', body)
            # New raw evidence arrives after the cache was built. All data routes fail closed.
            for route, query in (('/classic/api/catalog', {}), ('/classic/data/3.csv', {}),
                                  ('/data/three_players_data.csv', {}),
                                  ('/3p/base_tech_analysis/pos_on_score/terrans.html', {})):
                with self.assertRaisesRegex(ValueError, 'newly excluded'):
                    cache_response(root/'cache', route, query, excluded_game_ids={'keep3'})
            # Unrelated newly excluded IDs don't disable an otherwise safe cache.
            cache_response(root/'cache', '/classic/api/catalog', {}, excluded_game_ids={'not-in-cache'})
            rebuilt = build({'keep3'})
            self.assertEqual(rebuilt['datasets']['3']['games'], 0)
            body = cache_response(root/'cache', '/classic/data/3.csv', {}, excluded_game_ids={'keep3'})[0]
            self.assertNotIn(b'keep3', body)
            self.assertEqual({p: p.read_bytes() for p in csvs.values()}, before)
