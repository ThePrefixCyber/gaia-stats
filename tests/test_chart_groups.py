import copy
import unittest
from collections import defaultdict

from gaia_stats.chart_groups import opening_configuration
from gaia_stats.cohort import statistics, report
from gaia_stats.streaming_cohort import statistics as streamed
from gaia_stats.base_cohort import convert
from test_corrected_plots import game


def row(identifier, rank=1, owned=None, available=None):
    return {'game_id': identifier, 'score': 100 + rank, 'rank': rank,
            'win_share': 1 if rank == 1 else 0, 'elo': 150,
            'technologies': available or {}, 'ship_technologies': {},
            'owned_technologies': owned, 'round_one_structures': {'m': 2, 'PI': 1}}


class ChartGroupTests(unittest.TestCase):
    def test_tiles_are_deduplicated_across_positions_and_verified_aliases(self):
        available = {'terra': 'tech1', 'nav': '1q_1o'}
        rows = [row('one', owned=[{'tile':'tech1','slot':'terra'},
                                  {'tile':'1q_1o','slot':'nav'},
                                  {'tile':'tech1','slot':'terra'}], available=available),
                row('two', rank=2, owned=[], available=available),
                row('unknown', rank=3, available=available)]
        result = statistics(rows, 'basic-tech-frequency')
        self.assertEqual(result['unavailable_records'], 1)
        self.assertEqual(len(result['tile_cells']), 1)
        cell = result['tile_cells'][0]
        self.assertEqual((cell['label'], cell['samples'], cell['available']), ('tech1', 1, 2))
        self.assertEqual(cell['rank_counts'], {1: 1})
        self.assertEqual(cell['frequency'], .5)
        self.assertEqual(len(result['cells']), 2)  # Optional position detail remains.

    def test_advanced_denominator_requires_tile_available_and_known_ownership(self):
        rows = [row('one', owned=[{'tile':'advtech1','slot':'adv-nav'}],
                    available={'adv-nav':'advtech1'}),
                row('two', rank=2, owned=[], available={'adv-terra':'3vp_per_fed_pass'}),
                row('three', rank=3, owned=[], available={'adv-terra':'advtech2'}),
                row('four', rank=4, available={'adv-nav':'advtech1'})]
        cell = next(c for c in statistics(rows,'advanced-tech-frequency')['tile_cells'] if c['label']=='advtech1')
        self.assertEqual(cell['available'], 2)
        self.assertEqual(cell['samples'], 1)
        self.assertEqual(cell['frequency'], .5)

    def test_unknown_setup_is_not_invented_from_acquisition(self):
        rows = [row('one', owned=[{'tile':'mystery-a','slot':'terra'}], available={'nav':'mystery-b'})]
        cells = {c['label']:c for c in statistics(rows,'basic-tech-frequency')['tile_cells']}
        self.assertEqual(set(cells), {'mystery-a','mystery-b'})
        self.assertEqual(cells['mystery-a']['available'], 0)
        self.assertEqual(cells['mystery-a']['unavailable_taken_n'], 1)
        self.assertIsNone(cells['mystery-a']['frequency'])
        self.assertEqual(cells['mystery-b']['frequency'], 0)

    def test_original_structure_precedence_and_exact_count_order(self):
        for structures, expected in [({'m':2},'m'),({'m':2,'ts':1},'ts'),
                                     ({'m':2,'lab':1,'ts':1},'lab'),
                                     ({'PI':1,'lab':1},'PI'),
                                     ({'PI':1,'ac1':1},'ac1'),
                                     ({'PI':1,'ac1':1,'ac2':1},'ac2')]:
            self.assertEqual(opening_configuration(structures)[0], expected)
        self.assertEqual(opening_configuration({'m':2,'PI':1})[1], '2-m_0-ts_0-lab_1-pi_0-ac1_0-ac2')
        for unknown in (None, {'m':None}, {'m':-1}, {'lab':.5}, {'ts':float('nan')}):
            self.assertIsNone(opening_configuration(unknown))

    def test_sparse_raw_and_complete_csv_counts_share_one_leaf(self):
        first=row('first',owned=[])
        second=copy.deepcopy(first);second.update(game_id='second',score=200,elo=None)
        second['round_one_structures']={'m':2.,'ts':0.,'lab':0.,'PI':1.,'ac1':0.,'ac2':0.}
        result=statistics([first,second],'round-one-structures')
        self.assertEqual(len(result['cells']),1)
        cell=result['cells'][0]
        self.assertEqual(cell['samples'],2)
        self.assertEqual(cell['mean_score'],150.5)
        self.assertEqual(cell['mean_elo'],150)
        self.assertEqual(cell['mean_elo_n'],1)

    def test_streaming_merges_tile_aliases_and_elo_using_measured_counts(self):
        # Real normalized rows keep selection and CSV semantics identical.
        def make(identifier, tile, elo):
            source=game(score=150,other=150,identifier=identifier)
            source.update(tech_terra=tile, pos_1_elo=elo)
            source['pos_1_tech_taken_'+tile]=True
            for p in (1,2):
                source[f'pos_{p}_dropped']='False'
                for key in ('m','ts','lab','PI','ac1','ac2'):
                    source[f'pos_{p}_buildings_r_1_{key}']=2 if key=='m' else int(key=='PI')
            return convert({k:str(v) for k,v in source.items()},2)
        batches=[make('first','tech1',150),make('second','1q_1o','')]
        rows=[r for batch in batches for r in batch]
        for kind in ('basic-tech-frequency','advanced-tech-frequency','round-one-structures'):
            filters={'ruleset':'base','plot':kind}
            actual=streamed(iter(batches),filters,'test')
            expected=report({'rows':rows,'scope':'test'},filters)
            self.assertEqual(actual,expected)

    def test_leaf_classes_and_sizes_match_original_notebook_hierarchy(self):
        import pandas as pd
        from gaia_stats.legacy_plots import make_plot
        configurations=[{'m':2,'PI':1},{'m':2,'PI':1},{'m':2,'lab':1},{'m':1,'ts':2},{'m':3}]
        games=[];rows=[]
        for i,structures in enumerate(configurations):
            source=game(score=150,other=150,identifier='parity-'+str(i))
            source['pos_1_score_bid']=source['pos_2_score_bid']=0
            if i % 2:
                source['pos_1_faction'],source['pos_2_faction']='xenos','terrans'
            for p in (1,2):
                for key in ('m','ts','lab','PI','ac1','ac2'):
                    source[f'pos_{p}_buildings_r_1_{key}']=structures.get(key,0)
            games.append(source)
            record=row(str(i),owned=[]);record.update(score=150,round_one_structures=structures);rows.append(record)
        trace=make_plot('round-one-structures',pd.DataFrame(games),players=2,
                        faction='terrans',methodology='historical').data[0]
        original={}
        classes={}
        for label,parent,value in zip(trace.labels,trace.parents,trace.values):
            if parent.count('/')==1:
                original[(parent.rsplit('/',1)[1],label.strip())]=int(value)
            elif parent:
                classes[label]=int(value)
        cells=statistics(rows,'round-one-structures')['cells']
        self.assertEqual({(c['structure_class'],c['label']):c['samples'] for c in cells},original)
        current=defaultdict(int)
        for cell in cells:current[cell['structure_class']]+=cell['samples']
        self.assertEqual(dict(current),classes)
        self.assertEqual(sum(c['samples'] for c in cells),int(next(v for p,v in zip(trace.parents,trace.values) if not p)))
        self.assertEqual(trace.branchvalues,'total')
