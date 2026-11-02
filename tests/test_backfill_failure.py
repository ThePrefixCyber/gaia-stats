import io
import importlib.util
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from gaia_stats.archive import collect
from gaia_stats.refresh import run
from gaia_stats.releases import current,validate
from gaia_stats.wsgi import ReleaseApplication
from gaia_stats.__main__ import atomic_json
from test_archive import FakeClient, game
import test_releases


class BackfillFailureTests(unittest.TestCase):
    setUp = test_releases.ReleaseTests.setUp
    publish = test_releases.ReleaseTests.publish

    def release_rows(self):
        path=current(self.store)
        with sqlite3.connect(path/'base.sqlite') as db:
            base=[json.loads(x[0]) for x in db.execute('SELECT payload FROM observations')]
        lf=json.loads((path/'lost-fleet.json').read_text())['rows']
        return {(r['ruleset'],r['game_id'],r['faction']):r for r in base+lf}

    def test_both_modes_keep_all_prior_rows_seed_and_raw_and_noop_metadata(self):
        for mode in ('base','lost-fleet'):
            client=FakeClient({'Kept-'+mode:game('Kept-'+mode,lf=mode=='lost-fleet')})
            collect(self.archive,mode,client=client,max_pages=1,max_downloads=1)
        first=self.publish();before=self.release_rows()
        raw={p:p.read_bytes() for p in self.archive.glob('*/raw/*.json')}
        seed=self.seed.read_bytes()
        atomic_json(self.store/'refresh-status.json',{'last_success':'old-success',
            'last_successful_release':first['release'],'last_publication':'old-publication',
            'last_publication_release':first['release']})
        clean={'listing_error':None,'retry':0,'accepted':0,'rejected':0}
        failed={**clean,'listing_error':'HTTP 400','listing_error_detail':{'http_status':400},'checkpoint':(10010,0)}
        with patch('gaia_stats.refresh.collect',side_effect=[clean,failed,clean,failed]):
            result=run(self.store,self.seed,self.archive,self.legacy)
        self.assertEqual(result['state'],'degraded');self.assertEqual(len(result['warnings']),2)
        self.assertFalse(result['publication_changed'])
        self.assertEqual(result['last_publication'],'old-publication')
        self.assertEqual(result['last_publication_release'],first['release'])
        self.assertEqual(result['last_successful_release'],first['release'])
        self.assertEqual(result['last_success'],'old-success')
        self.assertEqual(self.release_rows(),before)
        self.assertEqual(self.seed.read_bytes(),seed)
        self.assertTrue(all(p.read_bytes()==data for p,data in raw.items()))
        validate(current(self.store))
        # A clean recovery clears degradation without pretending to republish data.
        with patch('gaia_stats.refresh.collect',return_value=clean):
            recovered=run(self.store,self.seed,self.archive,self.legacy)
        self.assertEqual(recovered['state'],'ok');self.assertIsNone(recovered['error'])
        self.assertNotEqual(recovered['last_success'],'old-success')
        self.assertEqual(recovered['last_publication'],'old-publication')

    def test_second_head_page_failure_is_fatal_for_either_mode(self):
        self.publish();pointer=(self.store/'current.json').read_bytes()
        for mode in ('base','lost-fleet'):
            class Client(FakeClient):
                def get(self,url):
                    if '/status/ended?' in url:
                        query=parse_qs(urlsplit(url).query)
                        actual='lost-fleet' if 'expansion' in query else 'base'
                        if actual==mode:
                            if int(query['skip'][0])>=10:
                                raise HTTPError(url,400,'second head page failed',{},io.BytesIO(b'bad'))
                            return [{'slug':'Head-'+str(i)} for i in range(10)],b'[]'
                        return [],b'[]'
                    return super().get(url)
            client=Client({'Head-'+str(i):game('Head-'+str(i),lf=mode=='lost-fleet') for i in range(10)})
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError,'head scan'):run(self.store,self.seed,self.archive,self.legacy,client=client)
                self.assertEqual((self.store/'current.json').read_bytes(),pointer)
                state=json.loads((self.store/'refresh-status.json').read_text())
                self.assertEqual(state['passes'][mode+'-head']['pages'],1)
                self.assertEqual(state['state'],'error')

    def test_degraded_health_passes_code_verifier_but_corrupt_counts_do_not(self):
        self.publish()
        atomic_json(self.store/'refresh-status.json',{'state':'degraded','error':'historical discovery failed',
            'last_success':'2020-01-01T00:00:00+00:00','last_publication':'2026-11-02T06:00:00+00:00'})
        app=ReleaseApplication(self.store)
        def fetch(url):
            parsed=urlsplit(url)
            if parsed.path.endswith('.js'):return 'x'*100001
            statuses=[]
            body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':parsed.path,'QUERY_STRING':parsed.query},lambda s,h:statuses.append(s)))
            self.assertEqual(statuses,['200 OK'])
            return body.decode() if parsed.path=='/' else json.loads(body)
        health=fetch('http://localhost/healthz')
        self.assertEqual(health['status'],'ok');self.assertEqual(health['refresh']['state'],'degraded')
        self.assertTrue(health['refresh']['stale'])
        spec=importlib.util.spec_from_file_location('verify_backfill',Path(__file__).parents[1]/'deploy/verify-health.py')
        verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
        verifier.verify(app.commit,fetch)
        def broken(url):
            data=fetch(url)
            if '/cohort/api/stats' in url:data['samples']+=1
            return data
        with self.assertRaises(ValueError):verifier.verify(app.commit,broken)

    def test_invalid_or_failed_queued_export_cannot_downgrade_prior_release(self):
        self.publish();before=self.release_rows();pointer=(self.store/'current.json').read_bytes()
        clean={'listing_error':None,'retry':0,'accepted':0,'rejected':0}
        for retry in (False,True):
            payload=game('Invalid-'+str(retry),lf=False)
            payload['data']['advancedLog']=[]
            queue=FakeClient({payload['slug']:payload})
            collect(self.archive,'base',client=queue,max_pages=1,max_downloads=0)
            class Client(FakeClient):
                def get(self,url):
                    if '/status/ended?' in url:raise HTTPError(url,400,'listing',{},io.BytesIO(b'bad'))
                    return super().get(url)
            client=Client(queue.games)
            if retry:client.fail_export.add(payload['slug'])
            def call(directory,mode,**kwargs):
                if mode=='base' and not kwargs.get('head_only'):
                    return collect(directory,mode,client=client,max_pages=1,max_downloads=10)
                return clean
            with self.subTest(retry=retry),patch('gaia_stats.refresh.collect',side_effect=call):
                if retry:
                    with self.assertRaises(ValueError):run(self.store,self.seed,self.archive,self.legacy)
                else:
                    result=run(self.store,self.seed,self.archive,self.legacy)
                    self.assertEqual(result['state'],'degraded')
                    self.assertEqual(result['passes']['base']['rejected'],1)
                    self.assertFalse(result['publication_changed'])
                self.assertEqual((self.store/'current.json').read_bytes(),pointer)
                self.assertEqual(self.release_rows(),before)

    def test_deep_listing_failure_drains_queue_and_publishes_with_warning(self):
        class Client(FakeClient):
            def get(self, url):
                if '/status/ended?' in url and 'expansion=' not in url:
                    offset = int(parse_qs(urlsplit(url).query)['skip'][0])
                    if offset >= 10010:
                        raise HTTPError(url, 400, 'Bad Request', {}, io.BytesIO(b'upstream validation evidence'))
                    if offset >= 9990:
                        return [{'slug': 'Queued'}] * 10, b'[]'
                return super().get(url)
        client = Client({'Queued': game('Queued', lf=False)})
        collect(self.archive, 'base', client=client, max_pages=1, max_downloads=0)
        with sqlite3.connect(self.archive/'archive.sqlite3') as db:
            db.execute('UPDATE scans SET cursor=10010,complete=0 WHERE mode="base"')
        before = self.publish()
        prior_rows=self.release_rows()
        atomic_json(self.store/'refresh-status.json', {'last_success':'prior-success'})
        # Newest pass deliberately contains no queued game: the backlog must drain.
        client.slugs = []
        result = run(self.store,self.seed,self.archive,self.legacy,client=client)
        self.assertEqual(result['state'],'degraded')
        self.assertEqual(result['last_success'],'prior-success')
        self.assertTrue(result['last_publication'])
        self.assertTrue(result['publication_changed'])
        self.assertEqual(result['last_publication_release'],result['release'])
        self.assertNotEqual(result['release'],before['release'])
        self.assertEqual(client.exports,['Queued'])
        detail = result['passes']['base']['listing_error_detail']
        self.assertEqual(detail['http_status'],400)
        self.assertEqual(detail['offset'],10010)
        self.assertEqual(detail['body'],'upstream validation evidence')
        self.assertIn('skip=10010',detail['url'])
        self.assertEqual(result['passes']['base']['checkpoint'],(10010,0))
        self.assertEqual(result['passes']['base']['pages'],2)
        self.assertEqual(result['passes']['base']['queued'],0)
        with sqlite3.connect(current(self.store)/'base.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations WHERE game_id="Queued"').fetchone()[0],4)
        saved = json.loads((self.store/'refresh-status.json').read_text())
        self.assertEqual(saved['state'],'degraded')
        self.assertEqual(self.legacy.read_bytes(),self.legacy_bytes)
        after=self.release_rows()
        self.assertTrue(prior_rows.keys()<=after.keys())
        self.assertTrue(all(after[key]==value for key,value in prior_rows.items()))

    def test_head_failure_retry_and_non400_do_not_publish(self):
        self.publish();before=(self.store/'current.json').read_bytes()
        clean={'listing_error':None,'retry':0,'accepted':0,'rejected':0}
        for code,retry,head in ((400,0,True),(429,0,False),(503,0,False),(400,1,False)):
            failed={**clean,'listing_error':'failure','retry':retry,
                    'listing_error_detail':{'http_status':code}}
            responses=[failed] if head else [clean,failed]
            with self.subTest(code=code,retry=retry,head=head), patch('gaia_stats.refresh.collect',side_effect=responses):
                with self.assertRaises(ValueError):run(self.store,self.seed,self.archive,self.legacy)
                self.assertEqual((self.store/'current.json').read_bytes(),before)

    def test_http_error_evidence_is_bounded_without_marking_complete(self):
        class Client(FakeClient):
            def get(self,url):
                raise HTTPError(url,400,'Bad Request',{},io.BytesIO(b'x'*10000))
        result=collect(self.archive,'base',client=Client({}),max_pages=1)
        self.assertEqual(len(result['listing_error_detail']['body']),4096)
        self.assertIsNone(result['checkpoint'])
