import io
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,unquote,urlsplit

from gaia_stats.archive import collect,listing_cursor,listing_slug
from gaia_stats.fetch import fetch_games
from gaia_stats.identifiers import url_segment,valid_slug
from gaia_stats.releases import current,base_ids
from gaia_stats.wsgi import ReleaseApplication
from test_archive import game
from test_cursor_archive import CursorClient
import test_releases


BRACKET='Gpit-round10[table-5]'
BACKTICK='duker`s-private-game'
DASHES='----------------------'


class EncodedClient(CursorClient):
    def get(self,url):
        if '/gameplay/' not in url:return super().get(url)
        self.calls.append(url)
        payload=self.games[unquote(urlsplit(url).path.rsplit('/',1)[1])]
        return payload,json.dumps(payload).encode()


class PunctuationTests(unittest.TestCase):
    def test_committed_historical_identifiers_all_fit_bounded_vocabulary(self):
        names=Path(__file__).parents[1].joinpath('data/game_names.txt').read_text().splitlines()
        for identifier in (BRACKET,BACKTICK,DASHES):self.assertIn(identifier,names)
        self.assertEqual([name for name in names if not valid_slug(name)],[])
        self.assertEqual(url_segment(BRACKET),'Gpit-round10%5Btable-5%5D')
        self.assertEqual(url_segment(BACKTICK),'duker%60s-private-game')
        for identifier in (BRACKET,BACKTICK,DASHES,'-remote-Christmas-party'):
            self.assertEqual(unquote(url_segment(identifier)),identifier)
            self.assertEqual(listing_slug({'_id':identifier}),identifier)
            self.assertEqual(json.loads(listing_cursor({'_id':identifier,'endedAt':None}))['id'],identifier)

    def test_unsafe_identifiers_still_rejected_before_url_or_file_use(self):
        for identifier in ('../secret','a/../b','a\\b','a%2Fb','%2e%2e','a?b','a#b',
                           'a\x00b','a\nb','a b','é','a.b','[first]','_first','a'*122,
                           'a;touch','a$(cmd)','a|cmd','a"b',None):
            with self.subTest(identifier=identifier):
                self.assertFalse(valid_slug(identifier))
                with self.assertRaises(ValueError):url_segment(identifier)


class PunctuationIntegrationTests(unittest.TestCase):
    setUp=test_releases.ReleaseTests.setUp
    publish=test_releases.ReleaseTests.publish

    def test_explicit_fetch_encodes_and_preserves_exact_files_and_mismatch_is_rejected(self):
        destination=self.root/'fetch'
        for identifier in (BRACKET,BACKTICK,DASHES):
            payload=game(identifier,lf=False)
            with patch('gaia_stats.fetch.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as opened:
                self.assertEqual(fetch_games([identifier],destination),0)
                self.assertEqual(opened.call_args.args[0].full_url,'https://www.boardgamers.space/api/gameplay/'+url_segment(identifier))
            saved=destination/(identifier+'.json');before=saved.read_bytes()
            with patch('gaia_stats.fetch.urlopen',return_value=io.BytesIO(json.dumps(game('Wrong',lf=False)).encode())):
                self.assertEqual(fetch_games([identifier],destination),1)
            self.assertEqual(saved.read_bytes(),before)

    def test_lookahead_next_page_cursor_restart_publication_and_cache_refresh(self):
        self.publish();prior=current(self.store);old_ids=base_ids(prior/'base.sqlite')
        seed=self.seed.read_bytes();app=ReleaseApplication(self.store)
        def stats():
            status=[]
            body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':'/cohort/api/stats',
                'QUERY_STRING':'ruleset=base&plot=point-sources'},lambda s,h:status.append(s)))
            self.assertEqual(status,['200 OK']);return json.loads(body)
        before=stats();old_app=app.app
        slugs=['Row-'+str(i) for i in range(10)]+[BRACKET,BACKTICK,DASHES]
        client=EncodedClient(slugs,lf=False)
        first=collect(self.archive,'base',client=client,pagination='cursor',max_pages=1,max_downloads=0)
        self.assertEqual(first['queued'],10)
        self.assertEqual(first['cursor_checkpoint'][1],0)
        with sqlite3.connect(self.archive/'archive.sqlite3') as db:
            self.assertIsNone(db.execute('SELECT slug FROM exports WHERE slug=?',(BRACKET,)).fetchone())
        second=collect(self.archive,'base',client=client,pagination='cursor',page_size=1,max_pages=1,max_downloads=20)
        self.assertEqual(json.loads(second['cursor_checkpoint'][0])['id'],BRACKET)
        resumed=EncodedClient(slugs,lf=False)
        last=collect(self.archive,'base',client=resumed,pagination='cursor',max_pages=1,max_downloads=20)
        self.assertEqual(json.loads(parse_qs(urlsplit(resumed.calls[0]).query)['after'][0])['id'],BRACKET)
        self.assertEqual(last['cursor_checkpoint'][1],1)
        requests=[url for url in client.calls+resumed.calls if '/gameplay/' in url]
        self.assertEqual([unquote(urlsplit(url).path.rsplit('/',1)[1]) for url in requests],slugs)
        self.assertTrue(any(url.endswith('Gpit-round10%5Btable-5%5D') for url in requests))
        for identifier in (BRACKET,BACKTICK,DASHES):
            self.assertTrue((self.archive/'base/raw'/(identifier+'.json')).is_file())
            provenance=json.loads((self.archive/'base/provenance'/(identifier+'.json')).read_text())
            self.assertTrue(provenance['url'].endswith(url_segment(identifier)))
        self.publish()
        self.assertTrue(old_ids<=base_ids(current(self.store)/'base.sqlite'))
        after=stats();self.assertIsNot(app.app,old_app)
        self.assertEqual(after['samples'],before['samples']+4*len(slugs))
        for identifier in (BRACKET,BACKTICK,DASHES):
            self.assertTrue(any(value.startswith(identifier+':') for value in after['record_ids']))
        self.assertEqual(self.seed.read_bytes(),seed)
        self.assertEqual(self.legacy.read_bytes(),self.legacy_bytes)
