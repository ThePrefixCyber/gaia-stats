import copy
import io
import json
import sqlite3
import unittest
from gaia_stats import base_cohort, streaming_cohort
from gaia_stats.cohort import report, export, PLOTS
import test_base_cohort as fixtures


class StreamingTests(unittest.TestCase):
    setUp = fixtures.BaseCohortTests.setUp
    def assert_equivalent(self, actual, expected):
        if isinstance(expected,dict):
            self.assertEqual(set(actual),set(expected))
            for key in expected:self.assert_equivalent(actual[key],expected[key])
        elif isinstance(expected,list):
            self.assertEqual(len(actual),len(expected))
            for a,b in zip(actual,expected):self.assert_equivalent(a,b)
        elif isinstance(expected,float):self.assertAlmostEqual(actual,expected,places=10)
        else:self.assertEqual(actual,expected)

    def test_complete_game_batches_match_reference_all_metrics_and_csv(self):
        source=base_cohort.dataset(self.db,{})
        rows=[]
        for index in range(1100):
            for original in source['rows'][:2]:
                row=copy.deepcopy(original);row['game_id']='game-'+str(index).zfill(5)
                row['score']+=index%19;row['win_share']=1/3 if index%3 else 0
                row['vp_sources']['round1']=index%13-6
                if index%5==0:row['vp_sources'].pop('final1',None)
                rows.append(row)
        with sqlite3.connect(self.db) as db:
            db.execute('DELETE FROM observations')
            for row in rows:
                db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)',tuple(row[k] for k in ('game_id','faction','player_count','elo','layout','auction','faction_variant'))+(json.dumps(row),))
        for filters in ({'ruleset':'base'},{'ruleset':'base','min_elo':'200'},
                        {'ruleset':'base','faction':'terrans'}, {'ruleset':'base','min_elo':'9999'}):
            data=base_cohort.dataset(self.db,filters)
            for plot in PLOTS:
                selected={**filters,'plot':plot}
                optimized=streaming_cohort.statistics(base_cohort.batches(self.db,selected,size=17),selected,base_cohort.SCOPE)
                self.assert_equivalent(optimized,report(data,selected))
            self.assertEqual(streaming_cohort.csv_export(base_cohort.batches(self.db,filters,size=17),filters),export(data,filters))
        chunks=list(base_cohort.batches(self.db,{},size=17))
        self.assertTrue(all(len(chunk)<=20 for chunk in chunks))
        self.assertTrue(all(a[-1]['game_id']!=b[0]['game_id'] for a,b in zip(chunks,chunks[1:])))

    def test_missing_source_across_batches_counts_only_complete_selected_ledgers(self):
        originals=base_cohort.dataset(self.db,{})['rows'][:2]
        games=[]
        for index in range(3):
            rows=copy.deepcopy(originals)
            for row in rows:
                row['game_id']='game-'+str(index)
                row['vp_ledger_complete']=index<2
                row['vp_sources']={'init':10}
            games.append(rows)
        for source_batch in (0,1):
            with self.subTest(source_batch=source_batch):
                batches=copy.deepcopy(games)
                batches[source_batch][0]['vp_sources']['unmapped:new-source']=10
                rows=[row for batch in batches for row in batch]
                for faction in (None, originals[0]['faction'], originals[1]['faction']):
                    filters={'ruleset':'base','plot':'point-sources'}
                    if faction:filters['faction']=faction
                    actual=streaming_cohort.statistics(iter(batches),filters,'test')
                    expected=report({'rows':rows,'scope':'test'},filters)
                    self.assert_equivalent(actual,expected)
                    if not faction:
                        cell=next(c for c in actual['plots']['point-sources']['cells'] if c['label']=='unmapped:new-source')
                        self.assertEqual(cell['samples'],4) # Historical blanks stay unknown.
                        self.assertEqual(cell['median'],0)
                        self.assertEqual(cell['q3'],2.5)
                reversed_batches=list(reversed(batches))
                filters={'ruleset':'base','plot':'point-sources'}
                self.assert_equivalent(streaming_cohort.statistics(iter(reversed_batches),filters,'test'),
                    report({'rows':[r for b in reversed_batches for r in b],'scope':'test'},filters))
                # Explicit historical observations still count, including real zeros.
                batches[2][0]['vp_sources']['unmapped:new-source']=0
                filters={'ruleset':'base','plot':'point-sources'}
                self.assert_equivalent(streaming_cohort.statistics(iter(batches),filters,'test'),
                    report({'rows':[r for b in batches for r in b],'scope':'test'},filters))
