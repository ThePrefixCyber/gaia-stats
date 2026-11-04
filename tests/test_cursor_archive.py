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
from gaia_stats.releases import current
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

    def test_tied_and_null_cursor_boundaries_continue_after_restart_without_gaps(self):
        for mode in ('base','lost-fleet'):
            client=CursorClient(['A','B','C','D','E','F'],lf=mode=='lost-fleet')
            tied='2026-01-20T00:00:00.000Z'
            for entry in client.entries[:3]:entry['endedAt']=tied
            for entry in client.entries[3:]:entry['endedAt']=None
            # Stop after B: C has the same timestamp and must not be skipped.
            first=self.collect(client,mode,max_pages=1,max_downloads=2)
            self.assertEqual(json.loads(first['cursor_checkpoint'][0]),{'status':'ended','at':tied,'id':'B'})
            # A fresh client simulates a new collector process using only saved state.
            resumed=CursorClient(client.slugs,lf=mode=='lost-fleet')
            resumed.entries=client.entries
            second=self.collect(resumed,mode,max_pages=1,max_downloads=2)
            request=parse_qs(urlsplit(resumed.calls[0]).query)
            self.assertEqual(request['skip'],['0'])
            self.assertEqual(json.loads(request['after'][0]),{'status':'ended','at':tied,'id':'B'})
            self.assertEqual(resumed.exports,['C','D'])
            self.assertEqual(json.loads(second['cursor_checkpoint'][0]),{'status':'ended','at':None,'id':'D'})
            self.assertEqual(second['cursor_checkpoint'][1],0)
            # Restart at D: explicitly send JSON null and use ID to retain E/F.
            last=CursorClient(client.slugs,lf=mode=='lost-fleet');last.entries=client.entries
            final=self.collect(last,mode,max_pages=1,max_downloads=2)
            request=parse_qs(urlsplit(last.calls[0]).query)
            self.assertEqual(request['skip'],['0'])
            self.assertEqual(json.loads(request['after'][0]),{'status':'ended','at':None,'id':'D'})
            self.assertIn('"at":null',request['after'][0])
            self.assertEqual(last.exports,['E','F'])
            self.assertEqual(final['cursor_checkpoint'][1],1)
            self.assertEqual(client.exports+resumed.exports+last.exports,['A','B','C','D','E','F'])
            with sqlite3.connect(self.root/'archive.sqlite3') as db:
                records=db.execute('SELECT slug,status,attempts FROM exports WHERE mode=? ORDER BY slug',(mode,)).fetchall()
            self.assertEqual(records,[(slug,'accepted',1) for slug in client.slugs])

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

    def test_refresh_collects_only_lost_fleet_and_preserves_base_archive_and_rows(self):
        base=CursorClient(['Base-kept'],lf=False)
        collect(self.archive,'base',client=base,pagination='cursor',max_pages=1,max_downloads=1)
        queued=CursorClient(['Base-pending'],lf=False)
        collect(self.archive,'base',client=queued,pagination='cursor',max_pages=1,max_downloads=0)
        self.publish()
        seed=self.seed.read_bytes()
        base_files={p:p.read_bytes() for p in (self.archive/'base').rglob('*') if p.is_file()}
        with sqlite3.connect(current(self.store)/'base.sqlite') as db:
            base_rows=db.execute('SELECT * FROM observations ORDER BY game_id,faction').fetchall()
        def base_checkpoint():
            with sqlite3.connect(self.archive/'archive.sqlite3') as db:
                return {table:db.execute('SELECT * FROM '+table+' WHERE mode="base" ORDER BY rowid').fetchall()
                        for table in ('exports','scans','cursor_scans','cursor_seen','events')}
        checkpoint=base_checkpoint()
        client=CursorClient(['LF'])
        get=client.get
        def only_lost_fleet(url):
            if '/status/ended?' in url:
                self.assertIn('expansion=lost-fleet',url)
            return get(url)
        client.get=only_lost_fleet
        result=run(self.store,self.seed,self.archive,self.legacy,client=client)
        self.assertEqual(result['state'],'ok')
        self.assertEqual(set(result['passes']),{'lost-fleet-head','lost-fleet'})
        for name in result['passes']:
            self.assertEqual(result['passes'][name]['pagination'],'cursor')
        self.assertEqual(result['passes']['lost-fleet']['cursor_checkpoint'][1],1)
        self.assertEqual(client.exports,['LF'])
        self.assertEqual(base_checkpoint(),checkpoint)
        self.assertEqual(self.seed.read_bytes(),seed)
        self.assertEqual({p:p.read_bytes() for p in (self.archive/'base').rglob('*') if p.is_file()},base_files)
        with sqlite3.connect(current(self.store)/'base.sqlite') as db:
            self.assertEqual(db.execute('SELECT * FROM observations ORDER BY game_id,faction').fetchall(),base_rows)
        lf=json.loads((current(self.store)/'lost-fleet.json').read_text())['rows']
        self.assertEqual(sum(row['game_id']=='LF' for row in lf),4)
        # Later refreshes keep collecting new LF games without redownloading old ones.
        client.games['LF-next']=game('LF-next')
        client.entries.insert(0,{'_id':'LF-next','endedAt':'2026-01-29T00:00:00.000Z'})
        again=run(self.store,self.seed,self.archive,self.legacy,client=client)
        self.assertEqual(again['state'],'ok')
        self.assertEqual(client.exports,['LF','LF-next'])
        self.assertEqual(base_checkpoint(),checkpoint)
