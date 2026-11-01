import unittest
import pandas as pd
from gaia_stats.corrected_plots import observations, mean_score, pair_mean
from gaia_stats.legacy_plots import make_plot


def game(score=100, other=90, dropped=False, identifier='g'):
    return {'id':identifier,'num_players':2,'pos_1_faction':'terrans','pos_2_faction':'xenos',
            'pos_1_score':score,'pos_2_score':other,'pos_1_dropped':False,'pos_2_dropped':dropped,
            'pos_1_elo':150,'pos_2_elo':250,'pos_1_score_bid':-20,'pos_2_score_bid':0,
            'tech_terra':'a','tech_adv-terra':'b','pos_1_tech_taken_a':True,'pos_2_tech_taken_a':False,
            'pos_1_adv_tech_taken_b':True,'pos_2_adv_tech_taken_b':False,
            'final_scoring_1':'gaia','final_scoring_2':'sector',
            'pos_1_score_final1':18,'pos_1_score_final2':12,'pos_2_score_final1':12,'pos_2_score_final2':6,
            **{f'round_{i}_scoring':'roundtile' for i in range(1,7)},
            **{f'pos_{p}_score_round{i}':10 for p in (1,2) for i in range(1,7)}}


class CorrectedPlotTests(unittest.TestCase):
    def test_weighted_mean_unequal_rank_cells(self):
        games=[game(identifier=str(i)) for i in range(9)]+[game(200,210,identifier='last')]
        rows=[r for r in observations(pd.DataFrame(games),2) if r['faction']=='terrans']
        self.assertEqual(mean_score(rows),(110,10))
        for kind in ('basic-tech-score','advanced-tech-score'):
            fig=make_plot(kind,pd.DataFrame(games),players=2,faction='terrans')
            self.assertEqual(fig.data[0].x[0],110)
            self.assertEqual(int(fig.data[0].text[0]),10)

    def test_single_pair_and_reversed_order_pool_once(self):
        row=game(); reverse=game(identifier='reverse');reverse['final_scoring_1']='sector';reverse['final_scoring_2']='gaia'
        rows=[r for r in observations(pd.DataFrame([row,reverse]),2) if r['faction']=='terrans']
        self.assertEqual(pair_mean(rows,'gaia','sector')[0],(30,2))
        fig=make_plot('final-scoring',pd.DataFrame([row]),players=2,faction='terrans')
        self.assertEqual(fig.data[0].z[0][1],30)
        self.assertIsNone(fig.data[0].z[0][0])

    def test_ties_invariant_under_position_reordering(self):
        row=game(100,100); other=dict(row)
        for key in list(row):
            if key.startswith('pos_1_'):other[key]=row[key.replace('pos_1_','pos_2_')]
            elif key.startswith('pos_2_'):other[key]=row[key.replace('pos_2_','pos_1_')]
        def results(g):return {r['faction']:(r['rank'],r['win_share']) for r in observations(pd.DataFrame([g]),2)}
        self.assertEqual(results(row),results(other));self.assertEqual(results(row)['terrans'],(1,.5))

    def test_dropped_game_excluded_once(self):
        data=pd.DataFrame([game(),game(dropped=True,identifier='drop')])
        rows=observations(data,2)
        self.assertEqual(len(rows),2);self.assertEqual({r['game'] for r in rows},{'g'})
        fig=make_plot('round-scoring',data,players=2,faction='terrans')
        self.assertEqual(fig.data[0].customdata[0][0],1)
        self.assertEqual(fig.data[0].z[0][0],10)

    def test_unseen_faction_and_unavailable_tech(self):
        data=pd.DataFrame([game()]);fig=make_plot('basic-tech-frequency',data,players=2,faction='absent')
        self.assertEqual(len(fig.data),0)
        data['tech_terra']='other'
        fig=make_plot('basic-tech-frequency',data,players=2,faction='terrans')
        self.assertIsNone(fig.data[0].y[0])
        fig=make_plot('advanced-tech-score',data,players=2,faction='xenos')
        self.assertIsNone(fig.data[0].x[0])

    def test_actual_score_and_elo_from_csv(self):
        row=game(100,110)
        data=pd.DataFrame([row]);rows=observations(data,2,min_elo=200)
        self.assertEqual([r['faction'] for r in rows],['xenos'])
        self.assertEqual(rows[0]['win_share'],1)
        self.assertEqual(observations(data,2)[0]['rank'],2) # bid restored would incorrectly win
        fig=make_plot('advanced-tech-score',data,players=2,faction='terrans',min_elo=200)
        self.assertEqual(len(fig.data),0)
