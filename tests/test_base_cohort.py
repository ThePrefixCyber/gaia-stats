import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from gaia_stats.base_cohort import build, dataset, catalog
from gaia_stats.wsgi import Application
from gaia_stats.cohort import report, export
from test_corrected_plots import game


class BaseCohortTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'base.sqlite'
        games=[]
        for i,variant in enumerate(('standard','more-balanced','')):
            g=game(identifier='g'+str(i));g.update(balance_variant=variant,map_layout='standard')
            for p in (1,2):
                for kind in ('m','ts','lab','PI','ac1','ac2'):g[f'pos_{p}_buildings_r_1_{kind}']=1
            games.append(g)
        games.append({**games[0],'id':'dropped','pos_2_dropped':True})
        path=self.root/'2.csv'
        with path.open('w') as f:
            writer=csv.DictWriter(f,fieldnames=list(games[0]));writer.writeheader();writer.writerows(games)
        self.imports=build({2:path},self.db)
        lf=json.loads((Path(__file__).parent/'fixtures/cohort/Eclipsed-council-7948.json').read_text())
        from gaia_stats.cohort import enrich
        from gaia_stats.analysis import normalize
        data=self.root/'lf.json';data.write_text(json.dumps({'schema_version':1,'rows':enrich(lf,normalize(lf))}))
        self.app=Application(data,base_cohort=self.db)

    def request(self,path,filters):
        from urllib.parse import urlencode
        response=[]
        body=b''.join(self.app({'REQUEST_METHOD':'GET','PATH_INFO':path,'QUERY_STRING':urlencode(filters)},lambda s,h:response.append(s)))
        return response[0],body

    def test_import_counts_variants_and_structures(self):
        self.assertEqual(self.imports[2]['accepted_games'],3)
        self.assertEqual(self.imports[2]['rejected_games'],1)
        self.assertEqual(catalog(self.db)['faction_variant'],['more-balanced','standard','unknown'])
        data=dataset(self.db,{})
        self.assertEqual(len(data['rows']),6)
        self.assertEqual(data['rows'][0]['round_one_structures']['PI'],1)

    def test_base_all_charts_comparison_and_csv_share_filters(self):
        filters={'ruleset':'base','min_elo':'200','faction_variant':'more-balanced','player_count':'2'}
        for plot in ('advanced-tech-frequency','advanced-tech-score','basic-tech-frequency','basic-tech-score','round-one-structures','round-scoring','final-scoring','point-sources'):
            filters['plot']=plot
            status,raw=self.request('/cohort/api/stats',filters);self.assertEqual(status,'200 OK');r=json.loads(raw)
            _,rawcsv=self.request('/cohort/api/export',filters);records=list(csv.DictReader(io.StringIO(rawcsv.decode())))
            self.assertEqual(r['samples'],1);self.assertEqual(len(records),1)
            self.assertEqual(records[0]['faction'],'xenos');self.assertEqual(r['comparisons'][0]['samples'],1)
            self.assertEqual(r['setup_comparisons']['rounds'][0]['samples'],1)
            self.assertEqual(set(r['record_ids']),{x['game_id']+':'+x['faction'] for x in records})
            self.assertIn(plot,r['plots'])

    def test_no_filter_default_and_high_elo_empty(self):
        status,body=self.request('/cohort/api/stats',{'ruleset':'base'});self.assertEqual(status,'200 OK');self.assertEqual(json.loads(body)['samples'],6)
        status,body=self.request('/cohort/api/stats',{'ruleset':'base','min_elo':'9999'})
        r=json.loads(body);self.assertEqual(r['samples'],0);self.assertEqual(r['comparisons'],[])
        self.assertEqual(next(iter(r['plots'].values()))['cells'],[])

    def test_mode_isolation_and_variant_default(self):
        for mode,expected in [('standard-only',0),('include-both',2),('variant-only',2)]:
            _,body=self.request('/cohort/api/stats',{'ruleset':'lost-fleet','lf_2p_4qic_mode':mode})
            r=json.loads(body);self.assertEqual(r['samples'],expected)
            self.assertTrue(all(not x.startswith('g0:') for x in r['record_ids']))
        _,body=self.request('/cohort/api/stats',{'ruleset':'base'})
        self.assertEqual(json.loads(body)['samples'],6)

    def test_cache_bound_and_injection_rejection(self):
        for cutoff in range(20):self.request('/cohort/api/stats',{'ruleset':'base','min_elo':str(cutoff)})
        self.assertLessEqual(len(self.app.cohort_cache),8)
        self.assertLessEqual(self.app.cohort_cache_bytes,16*1024*1024)
        status,_=self.request('/cohort/api/stats',{'ruleset':'base','filename':'/etc/passwd'});self.assertEqual(status,'400 Bad Request')
        status,_=self.request('/cohort/api/stats',{'ruleset':'base','final_scoring':'gaia','final_scoring2':'gaia'});self.assertEqual(status,'400 Bad Request')
        status,raw=self.request('/cohort/api/stats',{'ruleset':'base','faction':"' OR 1=1 --"});self.assertEqual(status,'200 OK');self.assertEqual(json.loads(raw)['samples'],0)

    def test_scoring_tables_use_actual_selected_contributions(self):
        _,raw=self.request('/cohort/api/stats',{'ruleset':'base','faction':'terrans','faction_variant':'standard','plot':'final-scoring'})
        r=json.loads(raw)
        self.assertEqual(r['setup_comparisons']['finals'][0]['final1'],18)
        self.assertEqual(r['setup_comparisons']['finals'][0]['final2'],12)
        self.assertEqual(r['plots']['final-scoring']['cells'][0]['mean_score'],30)

    def test_archive_accepts_real_id_only_listing_envelope(self):
        from gaia_stats.archive import collect
        import sqlite3
        page=json.loads((Path(__file__).parent/'fixtures/cohort/listing-000.json').read_text())
        class SavedClient:
            def get(self,url):
                if '/status/ended?' not in url:raise AssertionError('No download permitted')
                return page,json.dumps(page).encode()
        result=collect(self.root/'archive','lost-fleet',client=SavedClient(),page_size=11,max_pages=1,max_downloads=0)
        self.assertEqual(result['queued'],11)
        self.assertIsNone(result['listing_error'])
        with sqlite3.connect(self.root/'archive/archive.sqlite3') as db:
            queued={r[0] for r in db.execute('SELECT slug FROM exports')}
        self.assertEqual(queued,{r['_id'] for r in page})
