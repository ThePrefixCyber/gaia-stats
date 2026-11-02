import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch

from gaia_stats.archive import collect,listing_cursor
from gaia_stats.refresh import run
from test_archive import FakeClient,game
import test_releases


class CursorClient(FakeClient):
    def __init__(self,slugs,lf=True):
        super().__init__({slug:game(slug,lf=lf) for slug in slugs})
        self.entries=[{'_id':slug,'endedAt':f'2026-01-{28-i:02d}T00:00:00.000Z',
                       'lastMove':'2000-01-01T00:00:00Z'} for i,slug in enumerate(slugs)]
        self.fail_after=None

    def get(self,url):
        if '/status/ended?' not in url:return super().get(url)
        self.calls.append(url)
        query=parse_qs(urlsplit(url).query)
        assert query['skip']==['0']
        after=query.get('after',[None])[0]
        if after and self.fail_after:
            raise HTTPError(url,self.fail_after,'failure',{},io.BytesIO(b'cursor error'))
        offset=0
        if after:
            offset=next(i+1 for i,entry in enumerate(self.entries) if listing_cursor(entry)==after)
        entries=self.entries[offset:offset+int(query['count'][0])]
        return entries,json.dumps(entries).encode()


class CursorArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def collect(self,client,mode='base',**kwargs):
        return collect(self.root,mode,client=client,pagination='cursor',page_size=2,**kwargs)

    def test_migration_preserves_offset_and_queue_lookahead_restart_both_modes(self):
        for mode in ('base','lost-fleet'):
            old_complete=int(mode=='lost-fleet')
            old=FakeClient({'A':game('A',lf=mode=='lost-fleet')})
            collect(self.root,mode,client=old,max_pages=1,max_downloads=1)
            original=(self.root/mode/'raw/A.json').read_bytes()
            with sqlite3.connect(self.root/'archive.sqlite3') as db:
                db.execute('UPDATE scans SET cursor=10010,complete=? WHERE mode=?',(old_complete,mode))
            client=CursorClient(['A','B','C','D','E'],lf=mode=='lost-fleet')
            first=self.collect(client,mode,max_pages=1,max_downloads=0)
            self.assertEqual(first['checkpoint'],(10010,old_complete))
            self.assertEqual(first['cursor_checkpoint'],(listing_cursor(client.entries[1]),0,1))
            self.assertEqual(first['queued'],1) # A deduplicated, C is lookahead only.
            with sqlite3.connect(self.root/'archive.sqlite3') as db:
                self.assertIsNone(db.execute('SELECT status FROM exports WHERE mode=? AND slug="C"',(mode,)).fetchone())
            second=self.collect(client,mode,max_pages=1,max_downloads=1)
            self.assertEqual(second['cursor_checkpoint'],(listing_cursor(client.entries[3]),0,2))
            self.assertEqual(client.exports,['B'])
            final=self.collect(client,mode,max_pages=1,max_downloads=10)
            self.assertEqual(final['cursor_checkpoint'][1:],(1,3))
            self.assertEqual(final['totals'],{'accepted':5})
            self.assertEqual((self.root/mode/'raw/A.json').read_bytes(),original)
            self.assertEqual(final['checkpoint'],(10010,old_complete))
            self.assertTrue(all(('expansion=lost-fleet' in url)==(mode=='lost-fleet') for url in client.calls if '/status/ended?' in url))

    def test_ties_null_dates_and_lastmove_are_not_used_as_cursor(self):
        client=CursorClient(['A','B','C','D'])
        client.entries[1]['endedAt']=client.entries[0]['endedAt']
        client.entries[2]['endedAt']=client.entries[3]['endedAt']=None
        result=self.collect(client,max_pages=3,max_downloads=0)
        self.assertEqual(result['queued'],4)
        self.assertEqual(json.loads(result['cursor_checkpoint'][0]),{'status':'ended','at':None,'id':'D'})
        after=json.loads(parse_qs(urlsplit(client.calls[1]).query)['after'][0])
        self.assertEqual(after,{'status':'ended','at':client.entries[1]['endedAt'],'id':'B'})
        self.assertEqual(result['cursor_checkpoint'][1],1)

    def test_failed_page_keeps_last_token_and_never_marks_complete(self):
        client=CursorClient(['A','B','C','D','E']);client.fail_after=400
        result=self.collect(client,max_pages=3,max_downloads=0)
        self.assertEqual(result['pages'],1)
        self.assertEqual(result['cursor_checkpoint'],(listing_cursor(client.entries[1]),0,1))
        self.assertEqual(result['listing_error_detail']['after'],listing_cursor(client.entries[1]))
        client.fail_after=None
        resumed=self.collect(client,max_pages=1,max_downloads=0)
        self.assertEqual(resumed['queued'],2)
        self.assertEqual(resumed['cursor_checkpoint'][1],0)

    def test_invalid_rows_and_lookahead_fail_before_any_advancement(self):
        for bad in ({'_id':'B'}, {'_id':'B','endedAt':'bad'}, {'endedAt':None},
                    {'_id':'../B','endedAt':None},{'_id':'B','endedAt':1}):
            client=CursorClient(['A','B','C']);client.entries[2]=bad
            result=self.collect(client,max_pages=1,max_downloads=0)
            self.assertTrue(result['listing_error']);self.assertEqual(result['queued'],0)
            self.assertIsNone(result['cursor_checkpoint'])

    def test_repeated_boundary_and_cross_run_token_cycle_fail(self):
        client=CursorClient(['A','B','C','D','E'])
        first=self.collect(client,max_pages=1,max_downloads=0)
        boundary=first['cursor_checkpoint']
        class Stuck(CursorClient):
            def get(inner,url):return client.entries[:3],b'[]'
        result=self.collect(Stuck([]),max_pages=1,max_downloads=0)
        self.assertTrue(result['listing_error']);self.assertEqual(result['cursor_checkpoint'],boundary)
        self.collect(client,max_pages=1,max_downloads=0) # Now D, so A/B does not repeat immediate boundary.
        result=self.collect(Stuck([]),max_pages=1,max_downloads=0)
        self.assertIn('did not advance',result['listing_error'])
        self.assertEqual(json.loads(result['cursor_checkpoint'][0])['id'],'D')

    def test_queue_and_token_commit_together_on_storage_failure(self):
        client=CursorClient(['A','B','C','D','E'])
        first=self.collect(client,max_pages=1,max_downloads=0)
        with sqlite3.connect(self.root/'archive.sqlite3') as db:
            db.execute("CREATE TRIGGER fail_cursor BEFORE INSERT ON cursor_scans BEGIN SELECT RAISE(ABORT,'storage failure'); END")
        with self.assertRaises(sqlite3.Error):self.collect(client,max_pages=1,max_downloads=0)
        with sqlite3.connect(self.root/'archive.sqlite3') as db:
            self.assertEqual(db.execute('SELECT after_token,complete,pages FROM cursor_scans').fetchone(),first['cursor_checkpoint'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM exports').fetchone()[0],2)

    def test_head_priority_and_checkpoint_isolation(self):
        client=CursorClient(['A','B','C','D','E'])
        first=self.collect(client,max_pages=2,max_downloads=0)
        client.entries.insert(0,{'_id':'Newest','endedAt':'2026-02-01T00:00:00Z'})
        client.games['Newest']=game('Newest',lf=False)
        result=self.collect(client,max_pages=1,max_downloads=2,head_only=True)
        self.assertEqual(set(client.exports),{'Newest','A'})
        self.assertEqual(result['cursor_checkpoint'],first['cursor_checkpoint'])

    def test_empty_completion_and_completed_scan_restarts_deduplicated(self):
        client=CursorClient([])
        empty=self.collect(client,max_pages=1,max_downloads=0)
        self.assertEqual(empty['cursor_checkpoint'],(None,1,1))
        client=CursorClient(['A','B'])
        done=self.collect(client,max_pages=1,max_downloads=0)
        self.assertEqual(done['cursor_checkpoint'][1],1)
        again=self.collect(client,max_pages=1,max_downloads=0)
        self.assertEqual(again['queued'],0)
        self.assertEqual(again['cursor_checkpoint'][1:],(1,1))

    def test_count_cap_and_saved_token_validation(self):
        client=CursorClient(['A','B','C'])
        with self.assertRaises(ValueError):collect(self.root,'base',client=client,pagination='cursor',page_size=100)
        self.collect(client,max_pages=1,max_downloads=0)
        with sqlite3.connect(self.root/'archive.sqlite3') as db:db.execute("UPDATE cursor_scans SET after_token='{}'")
        calls=len(client.calls)
        with self.assertRaisesRegex(ValueError,'saved listing cursor'):self.collect(client,max_pages=1,max_downloads=0)
        self.assertEqual(len(client.calls),calls)


class CursorRefreshTests(unittest.TestCase):
    setUp=test_releases.ReleaseTests.setUp
    publish=test_releases.ReleaseTests.publish

    def test_partial_cursor_head_failure_never_publishes_or_advances_history(self):
        self.publish();pointer=(self.store/'current.json').read_bytes()
        client=CursorClient(['Head-'+str(i) for i in range(12)])
        client.fail_after=400
        with self.assertRaisesRegex(ValueError,'head scan'):
            run(self.store,self.seed,self.archive,self.legacy,client=client)
        self.assertEqual((self.store/'current.json').read_bytes(),pointer)
        state=json.loads((self.store/'refresh-status.json').read_text())
        self.assertEqual(state['passes']['lost-fleet-head']['pages'],1)
        self.assertIsNone(state['passes']['lost-fleet-head']['cursor_checkpoint'])
        self.assertEqual(state['state'],'error')

    def test_refresh_uses_cursor_by_default_and_publication_preserves_modes(self):
        self.publish()
        clients={'base':CursorClient(['Base'],lf=False),'lost-fleet':CursorClient(['LF'])}
        class Both:
            def get(inner,url):
                if '/status/ended?' in url:mode='lost-fleet' if 'expansion=' in url else 'base'
                else:mode='lost-fleet' if url.endswith('/LF') else 'base'
                return clients[mode].get(url)
        result=run(self.store,self.seed,self.archive,self.legacy,client=Both())
        self.assertEqual(result['state'],'ok')
        for mode in clients:
            self.assertEqual(result['passes'][mode]['pagination'],'cursor')
            self.assertEqual(result['passes'][mode]['cursor_checkpoint'][1],1)
            self.assertEqual(len(clients[mode].exports),1)
        with sqlite3.connect(self.archive/'archive.sqlite3') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scans').fetchone()[0],0)
