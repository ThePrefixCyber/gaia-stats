import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from gaia_stats.archive import ArchiveClient, archive_lock, collect

FIXTURES = Path(__file__).parent / 'fixtures'


def game(slug, lf=True):
    path = FIXTURES / ('Jubilant-rover-3041.json' if lf else 'Modern-riddle-1723.json')
    payload = json.loads(path.read_text())
    payload['slug'] = slug
    return payload


class FakeClient:
    def __init__(self, games):
        self.games = games
        self.slugs = list(games)
        self.calls = []
        self.fail_export = set()
        self.fail_listing = False
        self.envelope = False

    def get(self, url):
        self.calls.append(url)
        if '/status/ended?' in url:
            if self.fail_listing:
                raise URLError('offline')
            query = parse_qs(urlsplit(url).query)
            offset, count = int(query['skip'][0]), int(query['count'][0])
            payload = [{'slug': slug} for slug in self.slugs[offset:offset + count]]
            if self.envelope:
                payload = {'unknown': payload}
        else:
            slug = url.rsplit('/', 1)[-1]
            if slug in self.fail_export:
                raise URLError('temporary export failure')
            payload = self.games[slug]
        return payload, json.dumps(payload, indent=1).encode()

    @property
    def exports(self):
        return [url.rsplit('/', 1)[-1] for url in self.calls if '/gameplay/' in url]


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.live = self.root / 'analysis.json'
        self.live.write_bytes(b'existing-live-data')

    def tearDown(self):
        self.assertEqual(self.live.read_bytes(), b'existing-live-data')

    def test_history_resume_overlap_dedup_and_incremental_new_games(self):
        client = FakeClient({slug: game(slug) for slug in ('a', 'b', 'c', 'd', 'e')})
        first = collect(self.root, 'lost-fleet', client=client, page_size=2, max_pages=2,
                        max_downloads=1, overlap_pages=1)
        self.assertEqual(first['checkpoint'], (4, 0))
        self.assertEqual(first['totals'], {'accepted': 1, 'pending': 3})
        second = collect(self.root, 'lost-fleet', client=client, page_size=2, max_pages=2,
                         max_downloads=10, overlap_pages=1)
        self.assertEqual(second['checkpoint'], (5, 1))
        self.assertEqual(second['totals'], {'accepted': 5})
        self.assertEqual(client.exports, ['a', 'b', 'c', 'd', 'e'])
        client.games['new'] = game('new')
        client.slugs.insert(0, 'new')
        third = collect(self.root, 'lost-fleet', client=client, page_size=2, max_pages=4)
        self.assertEqual(third['accepted'], 1)
        self.assertEqual(client.exports[-1], 'new')
        self.assertEqual(len(client.exports), 6)
        self.assertTrue(all('expansion=lost-fleet' in url for url in client.calls if '/status/' in url))

    def test_listing_failure_and_unknown_envelope_do_not_advance_checkpoint(self):
        client = FakeClient({'a': game('a')})
        client.fail_listing = True
        result = collect(self.root, 'lost-fleet', client=client)
        self.assertIsNone(result['checkpoint'])
        self.assertTrue(result['listing_error'])
        client.fail_listing = False
        client.envelope = True
        result = collect(self.root, 'lost-fleet', client=client)
        self.assertIsNone(result['checkpoint'])
        self.assertIn('Unverified listing envelope', result['listing_error'])

    def test_retry_queue_survives_restart_and_respects_backoff(self):
        client = FakeClient({'a': game('a')}); client.fail_export.add('a')
        first = collect(self.root, 'lost-fleet', client=client, now=lambda: 100)
        self.assertEqual(first['retry'], 1)
        client.fail_export.clear()
        early = collect(self.root, 'lost-fleet', client=client, now=lambda: 110)
        self.assertEqual(early['accepted'], 0)
        later = collect(self.root, 'lost-fleet', client=client, now=lambda: 161)
        self.assertEqual(later['accepted'], 1)
        self.assertEqual(client.exports, ['a', 'a'])

    def test_rejected_exports_keep_raw_and_provenance_without_stat_rows(self):
        games = {slug: game(slug) for slug in ('cancelled', 'dropped', 'unknown', 'badscore', 'conflict', 'solo')}
        games['solo']['players'] = games['solo']['players'][:1]
        games['solo']['data']['players'] = games['solo']['data']['players'][:1]
        games['cancelled']['cancelled'] = True
        games['dropped']['players'][0]['dropped'] = True
        games['unknown']['game']['expansions'] = ['unverified-expansion']
        games['badscore']['players'][0]['score'] += 1
        games['conflict']['game']['options']['lostFleet2pQicTech'] = True
        games['conflict']['data']['options']['lostFleet2pQicTech'] = False
        client = FakeClient(games)
        result = collect(self.root, 'lost-fleet', client=client)
        self.assertEqual(result['rejected'], len(games))
        self.assertFalse((self.root / 'lost-fleet/rows').exists())
        for slug in games:
            raw = (self.root / 'lost-fleet/raw' / (slug + '.json')).read_bytes()
            provenance = json.loads((self.root / 'lost-fleet/provenance' / (slug + '.json')).read_text())
            self.assertEqual(provenance['response_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(json.loads(raw)['slug'], slug)

    def test_base_and_lf_are_explicit_and_mixed_listing_never_combines(self):
        client = FakeClient({'base': game('base', lf=False), 'lf': game('lf')})
        result = collect(self.root, 'base', client=client)
        self.assertEqual((result['accepted'], result['rejected']), (1, 1))
        self.assertNotIn('expansion=', client.calls[0])
        self.assertTrue((self.root / 'base/rows/base.json').exists())
        with self.assertRaises(ValueError):
            collect(self.root, 'all', client=client)

    def test_invalid_slugs_do_not_create_paths_or_downloads(self):
        client = FakeClient({'../../outside': {}})
        result = collect(self.root, 'base', client=client)
        self.assertEqual(result['queued'], 0)
        self.assertEqual(client.exports, [])

    def test_lock_prevents_concurrent_collectors(self):
        with archive_lock(self.root), self.assertRaises(RuntimeError):
            collect(self.root, 'base', client=FakeClient({}))


class TransportTests(unittest.TestCase):
    def response(self, raw, encoding=''):
        response = io.BytesIO(raw)
        response.headers = {'Content-Encoding': encoding}
        return response

    def test_gzip_decoding_and_pacing(self):
        sleeps, requests = [], []
        def opener(request, timeout):
            requests.append(request)
            return self.response(gzip.compress(b'{"slug":"example"}'), 'gzip')
        client = ArchiveClient(opener=opener, sleep=sleeps.append, clock=lambda: 0)
        for _ in range(2):
            payload, raw = client.get('https://boardgamers.space/test')
            self.assertEqual(payload['slug'], 'example')
            self.assertEqual(raw, b'{"slug":"example"}')
        self.assertEqual(sleeps, [1.0])
        self.assertEqual(requests[0].get_header('Accept-encoding'), 'gzip')

    def test_rate_limit_retry_after_and_finite_retries(self):
        sleeps, calls = [], []
        def opener(request, timeout):
            calls.append(request)
            if len(calls) < 3:
                raise HTTPError(request.full_url, 429, 'rate limited', {'Retry-After': '4'}, None)
            return self.response(b'[]')
        client = ArchiveClient(opener=opener, sleep=sleeps.append, clock=lambda: 0)
        self.assertEqual(client.get('https://boardgamers.space/test')[0], [])
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps.count(4), 2)
        with self.assertRaises(ValueError):
            ArchiveClient(interval=0)

    def test_nonretryable_http_error_is_not_retried(self):
        calls = []
        def opener(request, timeout):
            calls.append(request)
            raise HTTPError(request.full_url, 404, 'missing', {}, None)
        with self.assertRaises(HTTPError):
            ArchiveClient(opener=opener, sleep=lambda _: None).get('https://boardgamers.space/test')
        self.assertEqual(len(calls), 1)


class LongRetryTests(unittest.TestCase):
    def test_long_retry_after_defers_without_early_retry(self):
        calls, sleeps = [], []
        def opener(request, timeout):
            calls.append(request)
            raise HTTPError(request.full_url, 429, 'rate limited', {'Retry-After': '900'}, None)
        with self.assertRaises(HTTPError):
            ArchiveClient(opener=opener, sleep=sleeps.append).get('https://boardgamers.space/test')
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])

    def test_persistent_retry_respects_server_delay(self):
        client = FakeClient({'a': game('a')})
        original = client.get
        def get(url):
            if '/gameplay/' in url:
                raise HTTPError(url, 429, 'rate limited', {'Retry-After': '900'}, None)
            return original(url)
        client.get = get
        with tempfile.TemporaryDirectory() as folder:
            result = collect(folder, 'lost-fleet', client=client, now=lambda: 100)
            self.assertEqual(result['retry'], 1)
            with sqlite3.connect(Path(folder) / 'archive.sqlite3') as db:
                self.assertEqual(db.execute('SELECT retry_at FROM exports').fetchone()[0], 1000)


    def test_server_cooldown_blocks_other_modes_and_pending_downloads(self):
        client = FakeClient({'a': game('a')})
        def limited(url):
            raise HTTPError(url, 429, 'slow down', {'Retry-After': '900'}, None)
        with tempfile.TemporaryDirectory() as folder:
            collect(folder, 'lost-fleet', client=client, max_downloads=0, now=lambda: 100)
            client.get = limited
            failed = collect(folder, 'lost-fleet', client=client, now=lambda: 100)
            self.assertEqual(failed['totals'], {'pending': 1})
            other = FakeClient({})
            deferred = collect(folder, 'base', client=other, now=lambda: 200)
            self.assertEqual(deferred['retry_at'], 1000)
            self.assertEqual(other.calls, [])
