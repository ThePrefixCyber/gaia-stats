import copy
import json
import unittest
from pathlib import Path
from gaia_stats.analysis import normalize
from gaia_stats.cohort import enrich, report
from gaia_stats.streaming_cohort import statistics as streamed
from gaia_stats.scoring_views import ScoringViews


class ScoringViewsTests(unittest.TestCase):
    def setUp(self):
        raw=json.loads((Path(__file__).parent/'fixtures/Jubilant-rover-3041.json').read_text())
        self.template=enrich(raw,normalize(raw))[0]
        self.filters={'ruleset':'lost-fleet','faction':self.template['faction']}

    def row(self, identifier, **changes):
        row=copy.deepcopy(self.template)
        row.update(game_id=identifier, **changes)
        return row

    def test_signed_percentages_by_rank_count_no_score_threshold(self):
        rows=[self.row('a',score=50,rank=1,player_count=4,vp_sources={'fed':10,'charge':-2,'bid':-5},scoring_vp={f'round{i}':i for i in range(1,7)}),
              self.row('b',score=200,rank=1,player_count=4,vp_sources={'fed':20},scoring_vp={'final1':18,'final2':12}),
              self.row('c',score=100,rank=2,player_count=4,vp_sources={'fed':30}),
              self.row('d',score=100,rank=1,player_count=2,vp_sources={'fed':40}),
              self.row('e',score=0,vp_sources={'fed':90})]
        view=ScoringViews(self.filters);view.add_points(rows);result=view.points()
        lookup={(c['label'],c['player_count'],c['rank']):c for c in result['rank_cells']}
        self.assertEqual(lookup['fed',4,1]['values'],[20,10])
        self.assertEqual(lookup['charge',4,1]['values'],[-4,0])
        self.assertEqual(lookup['bid',4,1]['values'],[-10,0])
        self.assertEqual(lookup['round',4,1]['values'],[42,0])
        self.assertEqual(lookup['final',4,1]['values'],[0,15])
        self.assertEqual(lookup['fed',4,2]['values'],[30])
        self.assertEqual(lookup['fed',2,1]['values'],[40])
        self.assertEqual(result['invalid_share_denominators'],1)

    def test_unknown_not_zero_complete_absence_zero_late_sources(self):
        a=self.row('a',score=100,vp_sources={'fed':None},scoring_vp=None)
        b=self.row('b',score=100,vp_sources={'new-source':20})
        c=self.row('c',score=100,vp_sources={},vp_ledger_complete=False,scoring_vp=None)
        v=ScoringViews(self.filters)
        for row in (a,b,c):v.add_points([row])
        cells={c['label']:c for c in v.points()['rank_cells']}
        self.assertEqual(cells['new-source']['values'],[20,0])
        self.assertEqual(cells['fed']['samples'],1) # explicit None is not zero
        self.assertEqual(cells['round']['samples'],1) # unknown aggregate excluded

    def test_round_reference_relaxes_only_rounds_and_never_mixes_counts(self):
        a=self.row('a',win_share=1,round_scorings=['score1']*6,scoring_vp={'round1':8},player_count=4)
        b=self.row('b',win_share=0,round_scorings=['score2']*6,player_count=4)
        two=self.row('two',win_share=.5,round_scorings=['score1']*6,player_count=2)
        wrong=self.row('wrong',win_share=0,round_scorings=['score2']*6,layout='other',player_count=4)
        dataset={'rows':[a,b,two,wrong],'scope':'test'}
        filters={**self.filters,'plot':'round-scoring','round1':'score1','layout':a['layout']}
        result=report(dataset,filters)
        cells=result['plots']['round-scoring']['comparison_cells']
        four=next(c for c in cells if c['round']==1 and c['player_count']==4)
        self.assertEqual((four['mean_score'],four['win_share'],four['win_baseline'],four['win_difference']),(8,1,.5,.5))
        self.assertEqual(four['win_baseline_samples'],2)
        two_cell=next(c for c in cells if c['round']==1 and c['player_count']==2)
        self.assertEqual((two_cell['win_baseline'],two_cell['win_difference']),(.5,0))
        self.assertEqual(result['samples'],2)
        for batches in ([[a],[b,two,wrong]],[[b,wrong],[two],[a]]):
            actual=streamed(iter(batches),filters,'test')
            self.assertEqual(actual['plots']['round-scoring'],result['plots']['round-scoring'])

    def test_missing_round_vp_preserves_wins_and_all_factions_requires_selection(self):
        row=self.row('a',scoring_vp=None,win_share=.5)
        plot=report({'rows':[row]}, {**self.filters,'plot':'round-scoring'})['plots']['round-scoring']
        c=plot['comparison_cells'][0]
        self.assertEqual((c['samples'],c['score_samples'],c['mean_score'],c['win_share']),(1,0,None,.5))
        pooled=report({'rows':[row]}, {'ruleset':'lost-fleet','plot':'round-scoring'})['plots']['round-scoring']
        self.assertEqual(pooled['comparison_cells'],[])
        self.assertEqual(pooled['round_selection_required'],'faction')
        self.assertTrue(pooled['cells']) # existing raw observations retained

    def test_real_export_shares_stream_exact_and_absolute_view_preserved(self):
        raw=json.loads((Path(__file__).parent/'fixtures/Jubilant-rover-3041.json').read_text())
        rows=enrich(raw,normalize(raw));filters={'ruleset':'lost-fleet','plot':'point-sources'}
        expected=report({'rows':rows,'scope':'test'},filters)
        actual=streamed(iter([rows]),filters,'test')
        self.assertEqual(expected,actual)
        self.assertTrue(expected['plots']['point-sources']['cells'])
        cell=next(c for c in expected['plots']['point-sources']['rank_cells'] if c['label']=='final' and c['rank']==rows[0]['rank'])
        expected_values=[100*(r['scoring_vp']['final1']+r['scoring_vp']['final2'])/r['score'] for r in rows if r['rank']==rows[0]['rank']]
        self.assertEqual(cell['values'],expected_values)


    def test_real_lost_fleet_keeps_raw_source_vocabulary_and_reconciles_shares(self):
        raw=json.loads((Path(__file__).parent/'fixtures/Jubilant-rover-3041.json').read_text())
        rows=enrich(raw,normalize(raw))
        view=ScoringViews(self.filters);view.add_points(rows)
        labels={c['label'] for c in view.points()['rank_cells']}
        observed={k for row in rows for k in row['vp_sources']}
        self.assertEqual(labels, (observed-{f'round{i}' for i in range(1,7)}-{'final1','final2'})|{'round','final'})
        self.assertTrue({'federation','spend','initial'}<=labels)
        self.assertFalse({'fed','resource','init','research','adv','booster','tech_basic','qic'}&labels)
        for row in rows:
            single=ScoringViews(self.filters);single.add_points([row])
            cells={c['label']:c for c in single.points()['rank_cells']}
            self.assertAlmostEqual(sum(c['values'][0] for c in cells.values()),100)
            for source in ('federation','spend','initial'):
                if source in row['vp_sources']:
                    self.assertAlmostEqual(cells[source]['values'][0],100*row['vp_sources'][source]/row['score'])
