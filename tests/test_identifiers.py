import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from gaia_stats.archive import collect,listing_cursor,listing_slug
from gaia_stats.fetch import fetch_games
from gaia_stats.identifiers import valid_slug
from gaia_stats.releases import current,accepted_exports,base_ids
from gaia_stats.refresh import run
from gaia_stats.__main__ import main
from test_archive import game
from test_cursor_archive import CursorClient
import test_releases


HISTORICAL_ID='-remote-Christmas-party'


class IdentifierTests(unittest.TestCase):
    def test_exact_verified_identifier_and_length_limits(self):
        for value in (HISTORICAL_ID,'A','A'*121,'-'+'A'*120):
            self.assertTrue(valid_slug(value))
        for value in ('','-','--name','_name','A'*122,'-'+'A'*121,None,123,
                      '../secret','-../secret','a/b','a\\b','/absolute','a%2Fb',
                      'a?b','a#b','a\n','a\0','é','a b','a.b'):
            with self.subTest(value=value):
                self.assertFalse(valid_slug(value))
                with self.assertRaises(ValueError):listing_slug({'_id':value})

    def test_fetch_preserves_identifier_and_rejects_traversal_before_network(self):
        payload=game(HISTORICAL_ID,lf=False)
        with tempfile.TemporaryDirectory() as folder:
            with patch('gaia_stats.fetch.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as opened:
                self.assertEqual(fetch_games([HISTORICAL_ID],folder),0)
                self.assertEqual(opened.call_args.args[0].full_url,'https://www.boardgamers.space/api/gameplay/'+HISTORICAL_ID)
            self.assertEqual(json.loads((Path(folder)/(HISTORICAL_ID+'.json')).read_text())['slug'],HISTORICAL_ID)
            with patch('gaia_stats.fetch.urlopen') as opened:
                self.assertEqual(fetch_games(['../secret','-../secret','a/b','a%2Fb'],folder),4)
                opened.assert_not_called()

    def test_explicit_fetch_cli_accepts_leading_hyphen_after_option_separator(self):
        with patch('sys.argv',['gaia_stats','fetch','--directory','/tmp/test-raw','--',HISTORICAL_ID]), \
                patch('gaia_stats.fetch.fetch_games',return_value=0) as fetch:
            main()
            fetch.assert_called_once_with([HISTORICAL_ID],'/tmp/test-raw')

    def test_publisher_rejects_unsafe_database_identifiers_before_file_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with sqlite3.connect(root/'archive.sqlite3') as db:
                db.execute('CREATE TABLE exports (mode TEXT,slug TEXT,status TEXT,sha256 TEXT)')
            for slug in ('../secret','-../secret','a/b','a%2Fb','--unknown'):
                with sqlite3.connect(root/'archive.sqlite3') as db:
                    db.execute('DELETE FROM exports')
                    db.execute('INSERT INTO exports VALUES (?,?,?,?)',('base',slug,'accepted','bad'))
                with patch('gaia_stats.releases.digest') as digest:
                    with self.assertRaisesRegex(ValueError,'Unsafe archive identifier'):list(accepted_exports(root,'base'))
                    digest.assert_not_called()

    def test_invalid_page_diagnostics_are_bounded_and_checkpoint_is_not_advanced(self):
        with tempfile.TemporaryDirectory() as folder:
            client=CursorClient(['A','B','C'],lf=False)
            client.entries[2]={'_id':'x'*1000,'endedAt':None,'players':[{'private':'not diagnostic evidence'}]}
            result=collect(folder,'base',client=client,pagination='cursor',page_size=2,max_pages=1)
            self.assertEqual(result['listing_error'],'Invalid listing identifier')
            evidence=result['listing_error_detail']['entry']
            self.assertEqual(evidence,{'_id':{'type':'str','value':'x'*160,'length':1000},'page_index':2})
            self.assertIsNone(result['cursor_checkpoint'])
            self.assertEqual(result['queued'],0);self.assertEqual(client.exports,[])


class IdentifierPublicationTests(unittest.TestCase):
    setUp=test_releases.ReleaseTests.setUp
    publish=test_releases.ReleaseTests.publish

    def test_reported_tenth_retained_row_becomes_cursor_and_preserves_lookahead(self):
        from urllib.parse import parse_qs,urlsplit
        slugs=['Row-'+str(i) for i in range(9)]+[HISTORICAL_ID,'Correct-heart-5433']
        client=CursorClient(slugs,lf=False)
        client.entries[9]['endedAt']='2021-12-15T05:37:34.775Z'
        first=collect(self.archive,'base',client=client,pagination='cursor',max_pages=1,max_downloads=10)
        expected={'status':'ended','at':'2021-12-15T05:37:34.775Z','id':HISTORICAL_ID}
        self.assertEqual(json.loads(first['cursor_checkpoint'][0]),expected)
        self.assertEqual(first['cursor_checkpoint'][1],0)
        self.assertEqual(client.exports,slugs[:10])
        with sqlite3.connect(self.archive/'archive.sqlite3') as db:
            self.assertIsNone(db.execute('SELECT slug FROM exports WHERE slug="Correct-heart-5433"').fetchone())
        resumed=CursorClient(slugs,lf=False);resumed.entries=client.entries
        second=collect(self.archive,'base',client=resumed,pagination='cursor',max_pages=1,max_downloads=10)
        query=parse_qs(urlsplit(resumed.calls[0]).query)
        self.assertEqual(json.loads(query['after'][0]),expected)
        self.assertEqual(query['skip'],['0'])
        self.assertEqual(resumed.exports,['Correct-heart-5433'])
        self.assertEqual(second['cursor_checkpoint'][1],1)
        self.assertEqual(client.exports+resumed.exports,slugs)

    def test_actual_identifier_in_lookahead_resume_export_and_publication(self):
        before=self.publish();prior=current(self.store);seed=self.seed.read_bytes()
        slugs=['Row-'+str(i) for i in range(10)]+[HISTORICAL_ID,'Older']
        client=CursorClient(slugs,lf=False)
        client.entries[10]['endedAt']='2021-12-15T05:37:34.775Z'
        first=collect(self.archive,'base',client=client,pagination='cursor',max_pages=1,max_downloads=0)
        self.assertEqual(first['queued'],10)
        self.assertEqual(first['cursor_checkpoint'][1],0)
        with sqlite3.connect(self.archive/'archive.sqlite3') as db:
            self.assertIsNone(db.execute('SELECT slug FROM exports WHERE slug=?',(HISTORICAL_ID,)).fetchone())
        second=collect(self.archive,'base',client=client,pagination='cursor',page_size=1,max_pages=1,max_downloads=20)
        self.assertEqual(json.loads(second['cursor_checkpoint'][0]),{'status':'ended','at':'2021-12-15T05:37:34.775Z','id':HISTORICAL_ID})
        last=collect(self.archive,'base',client=client,pagination='cursor',max_pages=1,max_downloads=20)
        self.assertEqual(last['cursor_checkpoint'][1],1)
        self.assertEqual(client.exports,slugs)
        raw=self.archive/'base/raw'/(HISTORICAL_ID+'.json')
        self.assertEqual(json.loads(raw.read_text())['slug'],HISTORICAL_ID)
        candidate=self.publish()
        self.assertNotEqual(candidate['release'],before['release'])
        self.assertTrue(base_ids(prior/'base.sqlite')<=base_ids(current(self.store)/'base.sqlite'))
        with sqlite3.connect(current(self.store)/'base.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations WHERE game_id=?',(HISTORICAL_ID,)).fetchone()[0],4)
        self.assertEqual(self.seed.read_bytes(),seed)
        self.assertEqual(self.legacy.read_bytes(),self.legacy_bytes)

    def test_unknown_identifier_still_fails_refresh_closed(self):
        self.publish();pointer=(self.store/'current.json').read_bytes()
        client=CursorClient(['A']);client.entries[0]['_id']='../unknown'
        with self.assertRaisesRegex(ValueError,'head scan'):
            run(self.store,self.seed,self.archive,self.legacy,client=client)
        self.assertEqual((self.store/'current.json').read_bytes(),pointer)
        self.assertEqual(json.loads((self.store/'refresh-status.json').read_text())['state'],'error')
