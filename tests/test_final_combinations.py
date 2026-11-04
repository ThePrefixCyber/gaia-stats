import copy
import json
import unittest
from pathlib import Path
from gaia_stats.analysis import normalize
from gaia_stats.cohort import enrich, report, export
from gaia_stats.streaming_cohort import statistics as streamed

class FinalCombinationTests(unittest.TestCase):
    def setUp(self):
        raw=json.loads((Path(__file__).parent/'fixtures/Jubilant-rover-3041.json').read_text())
        self.template=enrich(raw,normalize(raw))[0]
        self.games=[self.game('a',['gaia','sector'],[36,24,12,0],[1,0,0,0]),
                    self.game('b',['planetType','satellite'],[0,12,24,36],[0,0,0,1]),
                    self.game('c',['sector','gaia'],[18,18,18,18],[.5,.5,0,0])]
        self.filters={'ruleset':'lost-fleet','plot':'final-scoring','faction':'terrans'}

    def game(self,identifier,pair,vps,wins):
        rows=[]
        for i,(vp,win) in enumerate(zip(vps,wins)):
            r=copy.deepcopy(self.template)
            r.update(game_id=identifier,faction=['terrans','xenos','ivits','geodens'][i],
                     player_count=len(vps),final_scorings=pair,win_share=win,elo=100+i*100,
                     scoring_vp={'final1':vp/2,'final2':vp/2},rank=1 if win else 2,
                     lf_2p_4qic_effective=False)
            rows.append(r)
        return rows

    def result(self,filters=None,games=None):
        return report({'rows':[r for g in (games or self.games) for r in g],'scope':'test'},filters or self.filters)

    def test_constants_replaced_by_faction_differences_with_exact_baselines(self):
        cells=self.result()['plots']['final-scoring']['cells']
        a=next(c for c in cells if c['tiles']==['gaia','sector'])
        self.assertEqual((a['mean_score'],a['score_baseline'],a['score_difference']),(27,18,9))
        self.assertEqual((a['win_share'],a['win_baseline'],a['win_difference']),(.75,.5,.25))
        self.assertEqual((a['samples'],a['score_samples'],a['games']),(2,2,2))
        self.assertEqual((a['score_baseline_samples'],a['win_baseline_samples']),(8,3))
        b=next(c for c in cells if c['tiles']!=a['tiles'])
        self.assertEqual((b['score_difference'],b['win_difference']),(-18,-.5))

    def test_final_filter_does_not_collapse_win_baseline(self):
        f={**self.filters,'final_scoring':'gaia','final_scoring2':'sector'}
        result=self.result(f);cell=result['plots']['final-scoring']['cells'][0]
        self.assertEqual(result['samples'],2)
        self.assertEqual(cell['win_baseline_samples'],3)
        self.assertEqual(cell['win_difference'],.25)
        self.assertEqual(len(result['plots']['final-scoring']['cells']),1)

    def test_all_factions_require_choice_and_empty_selection_stays_empty(self):
        result=self.result({**self.filters,'faction':''})['plots']['final-scoring']
        self.assertEqual(result['cells'],[]);self.assertEqual(result['selection_required'],'faction')
        self.assertEqual(self.result({**self.filters,'faction':'nevlas'})['plots']['final-scoring']['cells'],[])

    def test_missing_vp_not_zero_and_win_denominator_independent(self):
        self.games[0][0]['scoring_vp']['final1']=None
        self.games[0][0]['vp_ledger_complete']=False
        self.games[0][0]['vp_sources'].pop('final1',None)
        cell=self.result()['plots']['final-scoring']['cells'][0]
        self.assertEqual(cell['samples'],2);self.assertEqual(cell['score_samples'],1)
        self.assertEqual(cell['mean_score'],18)
        self.assertEqual(cell['score_baseline_samples'],7)
        self.assertAlmostEqual(cell['score_baseline'],108/7)
        self.assertEqual(cell['win_share'],.75)

    def test_player_counts_never_mix_and_other_filters_stay_active(self):
        self.games.append(self.game('two',['gaia','sector'],[30,6],[0,1]))
        cells=self.result()['plots']['final-scoring']['cells']
        two=next(c for c in cells if c['player_count']==2)
        self.assertEqual((two['score_difference'],two['win_baseline'],two['win_difference']),(12,0,0))
        f={**self.filters,'min_elo':'200'}
        self.assertEqual(self.result(f)['plots']['final-scoring']['cells'],[])
        self.games[0][1]['layout']='other'
        f={**self.filters,'layout':self.template['layout']}
        c=next(c for c in self.result(f)['plots']['final-scoring']['cells'] if c['player_count']==4 and c['tiles']==['gaia','sector'])
        self.assertEqual(c['score_baseline_samples'],7)

    def test_streamed_baselines_use_all_batches_even_without_selected_faction(self):
        self.games.append(self.game('only-opponents',['gaia','sector'],[10,20,30,12],[0,1,0,0])[1:])
        for filters in (self.filters,{**self.filters,'final_scoring':'gaia'},{**self.filters,'faction':''}):
            expected=self.result(filters)
            for batches in (self.games,list(reversed(self.games))):
                actual=streamed(iter(batches),filters,'test')
                a=actual['plots']['final-scoring'];b=expected['plots']['final-scoring']
                self.assertEqual(a.keys(),b.keys())
                for ac,bc in zip(a['cells'],b['cells']):
                    self.assertEqual(ac.keys(),bc.keys())
                    for key in ac:
                        if isinstance(ac[key],float):self.assertAlmostEqual(ac[key],bc[key],places=10)
                        else:self.assertEqual(ac[key],bc[key])
                self.assertEqual(actual['samples'],expected['samples'])

    def test_csv_and_other_chart_filters_still_select_faction_and_pair(self):
        rows=[r for g in self.games for r in g]
        f={**self.filters,'final_scoring':'gaia'}
        self.assertEqual(len(export({'rows':rows},f).splitlines()),3)
        r=self.result({**f,'plot':'round-scoring'})
        self.assertTrue(all(c['samples']==2 for c in r['plots']['round-scoring']['cells']))
