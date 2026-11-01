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
