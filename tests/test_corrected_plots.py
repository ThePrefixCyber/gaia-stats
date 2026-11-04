import unittest
import pandas as pd
from gaia_stats.corrected_plots import observations, mean_score, pair_mean
from gaia_stats.legacy_plots import make_plot


def game(score=100, other=100, dropped=False, identifier='g'):
    result = {'id':identifier,'num_players':2,'pos_1_faction':'terrans','pos_2_faction':'xenos',
            'pos_1_score':score,'pos_2_score':other,'pos_1_dropped':False,'pos_2_dropped':dropped,
            'score_source_layout':'player-position-v1','pos_1_bid':20,'pos_2_bid':0,
            'pos_1_tech_score':score-70,'pos_2_tech_score':other-78,
            'pos_1_elo':150,'pos_2_elo':250,'pos_1_score_bid':-20,'pos_2_score_bid':0,
            'tech_terra':'a','tech_adv-terra':'b','pos_1_tech_taken_a':True,'pos_2_tech_taken_a':False,
            'pos_1_adv_tech_taken_b':True,'pos_2_adv_tech_taken_b':False,
            'final_scoring_1':'gaia','final_scoring_2':'sector',
            'pos_1_score_final1':18,'pos_1_score_final2':12,'pos_2_score_final1':12,'pos_2_score_final2':6,
            **{f'round_{i}_scoring':'roundtile' for i in range(1,7)},
            **{f'pos_{p}_score_round{i}':10 for p in (1,2) for i in range(1,7)}}
    return result


class CorrectedPlotTests(unittest.TestCase):
    def test_weighted_mean_unequal_rank_cells(self):
        games=[game(identifier=str(i)) for i in range(9)]+[game(200,210,identifier='last')]
        rows=[r for r in observations(pd.DataFrame(games),2) if r['faction']=='terrans']
        self.assertEqual(mean_score(rows),(130,10))
        for kind in ('basic-tech-score','advanced-tech-score'):
            fig=make_plot(kind,pd.DataFrame(games),players=2,faction='terrans')
            self.assertEqual(fig.data[0].x[0],130)
            self.assertEqual(int(fig.data[0].text[0]),10)

    def test_single_pair_and_reversed_order_pool_once(self):
        row=game(); reverse=game(identifier='reverse');reverse['final_scoring_1']='sector';reverse['final_scoring_2']='gaia'
        rows=[r for r in observations(pd.DataFrame([row,reverse]),2) if r['faction']=='terrans']
        self.assertEqual(pair_mean(rows,'gaia','sector')[0],(30,2))
        fig=make_plot('final-scoring',pd.DataFrame([row]),players=2,faction='terrans')
        self.assertEqual(fig.data[0].z[0][1],30)
        self.assertIsNone(fig.data[0].z[0][0])

    def test_ties_invariant_under_position_reordering(self):
        row=game(100,120); other=dict(row)
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
        self.assertEqual(rows[0]['win_share'],0)
        self.assertEqual(observations(data,2)[0]['rank'],1) # Auction points are excluded
        fig=make_plot('advanced-tech-score',data,players=2,faction='terrans',min_elo=200)
        self.assertEqual(len(fig.data),0)

    def test_free_score_pools_players_once_before_weighted_mean(self):
        games = [game(score=100, identifier=str(i)) for i in range(3)] + [game(score=200, identifier='last')]
        for i, row in enumerate(games):
            row['tech_free1'] = 'a' if i < 3 else 'other'
            row['tech_free2'] = 'a' if i == 0 else 'other'
            row['tech_free3'] = 'a' if i == 3 else 'other'
        fig = make_plot('basic-tech-score', pd.DataFrame(games), players=2, faction='terrans')
        traces = {trace.name:trace for trace in fig.data}
        self.assertFalse({'tech_free1','tech_free2','tech_free3'} & traces.keys())
        self.assertEqual(traces['tech_free'].x[0], 145)
        self.assertEqual(int(traces['tech_free'].text[0]), 4)
        self.assertEqual(int(traces['tech_terra'].text[0]), 4)
        self.assertTrue({'taken','not_taken'} <= traces.keys())

    def test_classic_source_distributions_sum_free_within_player_before_rank_shares(self):
        frame = pd.DataFrame([game()])
        rows = observations(frame, 2)
        row = next(r for r in rows if r['faction']=='terrans')
        for slot, value in [('free1',3),('free2',5),('free3',7)]:
            row['values'][row['prefix']+'score_tech-'+slot] = value
        fig = make_plot('point-sources', frame, players=2, faction='terrans', _observations=rows)
        first = fig.data[0]
        self.assertEqual(list(first.x).count('tech-free'), 1)
        self.assertFalse({'tech-free1','tech-free2','tech-free3'} & set(first.x))
        self.assertEqual(first.y[list(first.x).index('tech-free')], 12.5)


class CorrectedOpeningHierarchyTests(unittest.TestCase):
    @staticmethod
    def frame(specifications):
        games=[]
        for i,(score,counts) in enumerate(specifications):
            source=game(score=score,other=150,identifier='opening-'+str(i))
            for p in (1,2):
                for key in ('m','ts','lab','PI','ac1','ac2'):
                    source[f'pos_{p}_buildings_r_1_{key}']=counts.get(key,0)
            games.append(source)
        return pd.DataFrame(games)

    def test_hierarchy_counts_and_parent_colors_are_observation_weighted_prebid(self):
        frame=self.frame([(100,{'m':2,'PI':1})]*3+[(200,{'m':3,'PI':1}),(150,{'m':2,'lab':1})])
        original=frame.copy(deep=True)
        figure=make_plot('round-one-structures',frame,players=2,faction='terrans')
        trace=figure.data[0]
        nodes={identity:(parent,value,score) for identity,parent,value,score in
               zip(trace.ids,trace.parents,trace.values,trace.customdata)}
        self.assertEqual(trace.branchvalues,'total')
        self.assertEqual(nodes['terrans'],('',5,150))
        self.assertEqual(nodes['terrans/PI'],('terrans',4,145))
        self.assertEqual(nodes['terrans/lab'],('terrans',1,170))
        self.assertEqual(nodes['terrans/PI/2-m_0-ts_0-lab_1-pi_0-ac1_0-ac2'],('terrans/PI',3,120))
        self.assertEqual(nodes['terrans/PI/3-m_0-ts_0-lab_1-pi_0-ac1_0-ac2'],('terrans/PI',1,220))
        self.assertEqual(list(trace.marker.colors),list(trace.customdata))
        self.assertEqual(figure.layout.meta['structure_observations'],5)
        self.assertEqual(figure.layout.meta['unavailable_structure_observations'],0)
        pd.testing.assert_frame_equal(frame,original)

    def test_representative_hierarchy_matches_historical_without_old_score_math(self):
        frame=self.frame([(150,{'m':2,'PI':1}),(150,{'m':2,'PI':1}),
                          (150,{'m':2,'lab':1}),(150,{'m':1,'ts':2}),(150,{'m':3})])
        original=make_plot('round-one-structures',frame,players=2,faction='terrans',methodology='historical').data[0]
        corrected=make_plot('round-one-structures',frame,players=2,faction='terrans').data[0]
        def hierarchy(trace):
            return {(str(label).strip(),str(parent).strip()):int(value)
                    for label,parent,value in zip(trace.labels,trace.parents,trace.values)}
        self.assertEqual(hierarchy(corrected),hierarchy(original))
        self.assertTrue(all(score==170 for score in corrected.customdata))

    def test_unknown_structures_are_unavailable_not_zero_openings(self):
        frame=self.frame([(150,{'m':2,'PI':1}),(150,{'m':None})])
        figure=make_plot('round-one-structures',frame,players=2,faction='terrans')
        self.assertEqual(figure.data[0].values[0],1)
        self.assertEqual(figure.layout.meta['unavailable_structure_observations'],1)
        unknown=make_plot('round-one-structures',frame.iloc[1:],players=2,faction='terrans')
        self.assertEqual(len(unknown.data),0)
        self.assertEqual(unknown.layout.meta['structure_observations'],0)
