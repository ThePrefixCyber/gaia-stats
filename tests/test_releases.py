import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from gaia_stats.base_cohort import build as base_build
from gaia_stats.cohort import build as lf_build, enrich
from gaia_stats.analysis import normalize
from gaia_stats.releases import publish,current,validate,release_lock,insert_game
from gaia_stats.refresh import run,RefreshDeadline
from gaia_stats.wsgi import ReleaseApplication
from gaia_stats.archive import collect
from test_archive import FakeClient,game
from test_corrected_plots import game as wide_game

FIXTURES=Path(__file__).parent/'fixtures'


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=self.root/'store';self.seed=self.root/'seed.sqlite';self.archive=self.root/'archive'
        source=self.root/'2.csv';g=wide_game();g.update(balance_variant='standard',map_layout='standard')
        with source.open('w') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(g));writer.writeheader();writer.writerow(g)
        base_build({2:source},self.seed)
        lf=json.loads((FIXTURES/'Jubilant-rover-3041.json').read_text())
        self.legacy=self.root/'legacy.json';self.legacy.write_text(json.dumps({'schema_version':1,'rows':enrich(lf,normalize(lf))}))
        self.legacy_bytes=self.legacy.read_bytes()

    def publish(self,**kwargs):
        with release_lock(self.store):return publish(self.store,self.seed,self.archive,self.legacy,**kwargs)

    def test_atomic_swap_hot_reload_cache_and_rollback(self):
        first=self.publish();app=ReleaseApplication(self.store)
        def request(path,query=''):
            status=[];body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':path,'QUERY_STRING':query},lambda s,h:status.append(s)))
            self.assertEqual(status,['200 OK']);return body
        self.assertIn(b'id="mode"',request('/'))
        health=json.loads(request('/healthz'));self.assertEqual(health['datasets']['base']['records'],2)
        request('/cohort/api/stats','ruleset=base');old=app.app;self.assertTrue(old.cohort_cache)
        self.legacy.write_text(self.legacy.read_text()+' ')
        second=self.publish();health=json.loads(request('/healthz'));self.assertEqual(health['release'],second['release'])
        self.assertIsNot(app.app,old);self.assertFalse(app.app.cohort_cache)
        from gaia_stats.__main__ import atomic_json
        atomic_json(self.store/'current.json',{'release':first['release']})
        self.assertEqual(json.loads(request('/healthz'))['release'],first['release'])
        # Fresh process/restart reads exactly the same pointer, without example seeding.
        self.assertEqual(current(self.store).name,first['release'])
        self.assertEqual(self.legacy.read_bytes(),self.legacy_bytes+b' ')

    def test_failed_and_dry_run_publication_preserve_pointer(self):
        self.publish();before=(self.store/'current.json').read_bytes()
        self.publish(dry_run=True);self.assertEqual((self.store/'current.json').read_bytes(),before)
        self.legacy.write_text(self.legacy.read_text()+' ')
        changed_legacy=self.legacy.read_bytes()
        with patch('gaia_stats.releases.accepted_exports',side_effect=ValueError('bad source')):
            with self.assertRaises(ValueError):self.publish()
        self.assertEqual((self.store/'current.json').read_bytes(),before)
        self.assertEqual(self.legacy.read_bytes(),changed_legacy)

    def test_no_loss_guard_rejects_removed_records(self):
        first=self.publish();prior=current(self.store)
        with patch('gaia_stats.releases.insert_game'):
            # Directly validate a tampered candidate with internally updated manifest hashes.
            import shutil
            candidate=self.root/'candidate';shutil.copytree(prior,candidate)
            with sqlite3.connect(candidate/'base.sqlite') as db:db.execute('DELETE FROM observations WHERE faction="terrans"')
            m=json.loads((candidate/'manifest.json').read_text());m['datasets']['base']['records']=1
            m['sha256']['base.sqlite']=hashlib.sha256((candidate/'base.sqlite').read_bytes()).hexdigest();(candidate/'manifest.json').write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'lose'):validate(candidate,prior)
        self.assertEqual(current(self.store),prior)

    def test_version_change_recomputes_existing_accepted_raw_without_download(self):
        payload=json.loads((FIXTURES/'cohort/Shiny-cypress-1384.json').read_text())
        client=FakeClient({payload['slug']:payload})
        collect(self.archive,'base',client=client,max_pages=1,max_downloads=1)
        def old_normalize(game):
            rows=normalize(game)
            for row in rows:
                for key in ('scoring_vp','vp_ledger_complete','normalization_version'):
                    row.pop(key,None)
            return rows
        with patch('gaia_stats.releases.NORMALIZATION_VERSION',1), patch('gaia_stats.releases.normalize',side_effect=old_normalize):
            first=self.publish()
        second=self.publish()
        self.assertNotEqual(first['release'],second['release'])
        self.assertEqual(first['datasets'],second['datasets'])
        with sqlite3.connect(current(self.store)/'base.sqlite') as db:
            rows=[json.loads(x[0]) for x in db.execute('SELECT payload FROM observations WHERE game_id=?',(payload['slug'],))]
        self.assertEqual(len(rows),4)
        self.assertTrue(all(r['normalization_version']==2 and r['vp_ledger_complete'] for r in rows))
        self.assertEqual(next(r for r in rows if r['faction']=='ivits')['scoring_vp']['final1'],0)
        self.assertEqual(client.exports,[payload['slug']])
        self.assertEqual(self.publish()['release'],second['release'])

    def test_seed_raw_overlap_replaces_not_duplicates(self):
        with sqlite3.connect(self.seed) as db:
            payload=json.loads(db.execute('SELECT payload FROM observations WHERE faction="terrans"').fetchone()[0]);payload['score']=222
            other=json.loads(db.execute('SELECT payload FROM observations WHERE faction="xenos"').fetchone()[0])
            insert_game(db,'g',[payload,other],replace=True)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],2)
            self.assertEqual(json.loads(db.execute('SELECT payload FROM observations WHERE faction="terrans"').fetchone()[0])['score'],222)

    def test_refresh_failure_freshness_and_runtime_bounds(self):
        self.publish();pointer=(self.store/'current.json').read_bytes()
        from gaia_stats.__main__ import atomic_json
        atomic_json(self.store/'refresh-status.json',{'last_success':'prior-success'})
        with patch('gaia_stats.refresh.collect',side_effect=RefreshDeadline('runtime limit')):
            with self.assertRaises(RefreshDeadline):run(self.store,self.seed,self.archive,self.legacy)
        state=json.loads((self.store/'refresh-status.json').read_text())
        self.assertEqual(state['state'],'error');self.assertEqual(state['last_success'],'prior-success')
        self.assertEqual((self.store/'current.json').read_bytes(),pointer)
        with self.assertRaises(ValueError):run(self.store,self.seed,self.archive,max_downloads=501)
        with release_lock(self.store):
            with self.assertRaises(ValueError):run(self.store,self.seed,self.archive)

    def test_successful_refresh_and_preflight_routes(self):
        self.publish()
        result={'listing_error':None,'retry':0,'accepted':0,'rejected':0}
        with patch('gaia_stats.refresh.collect',return_value=result):
            state=run(self.store,self.seed,self.archive,self.legacy)
        self.assertEqual(state['state'],'ok');self.assertTrue(state['last_success'])
        spec=importlib.util.spec_from_file_location('preflight',Path(__file__).parents[1]/'deploy/check-rebuilt.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        cache=self.root/'cache';cache.mkdir();(cache/'current.json').write_text('{"build":"build-test"}')
        (cache/'build-test').mkdir()
        with self.assertRaisesRegex(ValueError,'Plotly'):mod.check(self.store,cache)
        (cache/'build-test/plotly.min.js').write_text('x'*100001)
        self.assertEqual(mod.check(self.store,cache)['base']['records'],2)
        with patch('gaia_stats.releases.digest',side_effect=PermissionError('service user cannot read')):
            with self.assertRaises(PermissionError):mod.check(self.store,cache)

    def test_head_scan_preserves_backfill_cursor_and_prioritizes_recent(self):
        client=FakeClient({'Older':game('Older')})
        collect(self.archive,'lost-fleet',client=client,max_pages=1,max_downloads=0,page_size=1)
        with sqlite3.connect(self.archive/'archive.sqlite3') as db:before=db.execute('SELECT * FROM scans').fetchall()
        client.games['Newest']=game('Newest');client.slugs=['Newest','Older']
        result=collect(self.archive,'lost-fleet',client=client,max_pages=1,max_downloads=1,page_size=1,head_only=True)
        self.assertEqual(result['accepted'],1);self.assertEqual(client.exports,['Newest'])
        with sqlite3.connect(self.archive/'archive.sqlite3') as db:self.assertEqual(db.execute('SELECT * FROM scans').fetchall(),before)

    def test_interruption_after_pointer_swap_preserves_published_generation(self):
        self.publish();self.legacy.write_text(self.legacy.read_text()+' ')
        from gaia_stats.__main__ import atomic_json
        def interrupted(path, value):
            atomic_json(path,value)
            if path==self.store/'current.json':raise RefreshDeadline('after atomic swap')
        with patch('gaia_stats.releases.atomic_json',side_effect=interrupted):
            with self.assertRaises(RefreshDeadline):self.publish()
        self.assertTrue(current(self.store).is_dir());validate(current(self.store))

    def test_generation_swap_shares_work_lock_and_preserves_worker_commit(self):
        import threading
        from gaia_stats.releases import validate as real_validate
        self.publish()
        with patch('gaia_stats.wsgi.running_commit',return_value='worker-start') as identity:
            app=ReleaseApplication(self.store)
            def request(path):
                status=[]
                body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':path,'QUERY_STRING':'ruleset=base'},lambda s,h:status.append(s)))
                self.assertEqual(status,['200 OK']);return body
            request('/healthz');first=app.app
            entered=threading.Event();release=threading.Event();validating=threading.Event()
            def slow(*args):
                entered.set();self.assertTrue(release.wait(3));return b'{}','application/json'
            with patch('gaia_stats.base_cohort.response',side_effect=slow):
                old=threading.Thread(target=request,args=('/cohort/api/stats',));old.start();self.assertTrue(entered.wait(2))
                self.legacy.write_text(self.legacy.read_text()+' ');self.publish()
                def validate_new(path,**kwargs):validating.set();return real_validate(path,**kwargs)
                with patch('gaia_stats.releases.validate',side_effect=validate_new):
                    identity.return_value='checkout-changed'
                    new=threading.Thread(target=request,args=('/healthz',));new.start()
                    self.assertFalse(validating.wait(.1));release.set();old.join(3);new.join(3)
                self.assertFalse(old.is_alive());self.assertFalse(new.is_alive())
            self.assertIs(first.cohort_lock,app.app.cohort_lock)
            self.assertEqual(json.loads(request('/healthz'))['commit'],'worker-start')
            identity.assert_called_once()

    def test_unchanged_sources_do_not_accumulate_releases(self):
        first=self.publish();before=(self.store/'current.json').read_bytes()
        second=self.publish()
        self.assertEqual(first['release'],second['release'])
        self.assertEqual(len(list((self.store/'releases').iterdir())),1)
        self.assertEqual((self.store/'current.json').read_bytes(),before)
        self.legacy.write_text(self.legacy.read_text()+' ')
        with patch('gaia_stats.releases.shutil.disk_usage') as usage:
            usage.return_value.free=0
            with self.assertRaisesRegex(ValueError,'free space'):self.publish()
        self.assertEqual((self.store/'current.json').read_bytes(),before)

    def test_missing_release_fails_closed(self):
        status=[];body=b''.join(ReleaseApplication(self.store)({'REQUEST_METHOD':'GET','PATH_INFO':'/'},lambda s,h:status.append(s)))
        self.assertEqual(status,['503 Service Unavailable']);self.assertFalse((self.store/'analysis.json').exists())


class BuilderSafetyTests(unittest.TestCase):
    def test_empty_invalid_and_conflicting_build_preserve_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'data.json';out.write_text('preserve me')
            for paths in ([],[root/'invalid.json']):
                (root/'invalid.json').write_text('{}')
                with self.assertRaises(ValueError):lf_build(paths,out)
                self.assertEqual(out.read_text(),'preserve me')
            source=FIXTURES/'Jubilant-rover-3041.json';duplicate=root/'duplicate.json';duplicate.write_bytes(source.read_bytes())
            data=lf_build([source,duplicate],out);self.assertEqual(len(data['rows']),4)
            before=out.read_bytes();changed=json.loads(source.read_text());changed['players'][0]['score']+=1;duplicate.write_text(json.dumps(changed))
            with self.assertRaisesRegex(RuntimeError,'Conflicting'):lf_build([source,duplicate],out)
            self.assertEqual(out.read_bytes(),before)


class RebuiltVerifierTests(unittest.TestCase):
    def test_both_routes_assets_counts_and_failure(self):
        spec=importlib.util.spec_from_file_location('verify_rebuilt',Path(__file__).parents[1]/'deploy/verify-health.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        calls=[]
        def fetch(url):
            calls.append(url)
            if url.endswith('/healthz'):return {'status':'ok','commit':'abc','datasets':{m:{'games':1,'records':2} for m in ('base','lost-fleet')}}
            if url.endswith('/'):return '<select id="mode">'
            if url.endswith('.js'):return 'x'*100001
            mode='lost-fleet' if 'ruleset=lost-fleet' in url else 'base'
            return {'ruleset':mode,'games':1,'samples':2}
        mod.verify('abc',fetch)
        self.assertEqual(len(calls),10)
        for bad in ('asset','counts','database'):
            def broken(url):
                result=fetch(url)
                if bad=='asset' and url.endswith('.js'):return ''
                if '/cohort/api/stats' in url:
                    if bad=='database':raise ValueError('no observations table')
                    if bad=='counts':result['samples']=0
                return result
            with self.assertRaises(ValueError):mod.verify('abc',broken)
