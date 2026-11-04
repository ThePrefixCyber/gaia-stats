import copy
import json
import unittest
from pathlib import Path
from gaia_stats.analysis import normalize
from gaia_stats.cohort import enrich,report
from gaia_stats.basic_tech import KINDS,prepare,statistics
from gaia_stats.streaming_cohort import statistics as streamed

class BasicTechModesTests(unittest.TestCase):
    def setUp(self):
        game=json.loads((Path(__file__).parent/'fixtures/Jubilant-rover-3041.json').read_text())
        self.rows=enrich(game,normalize(game))

    def plot(self,kind,rows=None,**filters):
        return report({'rows':self.rows if rows is None else rows,'scope':'test'}, {'ruleset':'lost-fleet','plot':kind,**filters})['plots'][kind]

    def cell(self,kind,tile,location,**kwargs):
        return next(c for c in self.plot(kind,**kwargs)['cells'] if c['tile_id']==tile and c['location_id']==location)

    def test_real_ship_taken_setup_and_not_taken_have_distinct_denominators(self):
        taken=self.cell('basic-tech-score','ship-tech-resource','tfmars')
        setup=self.cell('basic-tech-setup-score','ship-tech-resource','tfmars')
        not_taken=self.cell('basic-tech-score','ship-tech-resource','not_taken')
        self.assertEqual((taken['samples'],taken['mean_score']),(2,159.5))
        self.assertEqual((setup['samples'],setup['mean_score']),(4,139.75))
        self.assertEqual((not_taken['samples'],not_taken['mean_score']),(2,120))

    def test_zero_remaining_and_covered_tiles_still_count(self):
        c=self.cell('basic-tech-frequency','tech2','nav')
        self.assertEqual((c['samples'],c['available'],c['frequency']),(4,4,1))
        self.assertEqual(self.cell('basic-tech-score','tech2','nav')['samples'],4)

    def test_exhausted_ship_recovered_before_faction_filter_without_mutation(self):
        rows=copy.deepcopy(self.rows)
        for r in rows:r['ship_technologies'].pop('tfmars',None)
        nonowner=next(r['faction'] for r in rows if not any(t['slot']=='tfmars' for t in r['owned_technologies']))
        c=self.cell('basic-tech-setup-score','ship-tech-resource','tfmars',rows=rows,faction=nonowner)
        self.assertEqual(c['samples'],1)
        self.assertTrue(all('tfmars' not in r['ship_technologies'] for r in rows))

    def test_missing_inventory_is_not_not_taken_but_setup_is_retained(self):
        rows=copy.deepcopy(self.rows);rows[0]['owned_technologies']=None
        c=self.cell('basic-tech-setup-score','tech2','nav',rows=rows)
        self.assertEqual(c['samples'],4)
        c=self.cell('basic-tech-frequency','tech2','nav',rows=rows)
        self.assertEqual((c['available'],c['setup_samples'],c['unknown_ownership']),(3,4,1))
        total=sum(c['samples'] for c in self.plot('basic-tech-score',rows)['cells'] if c['tile_id']=='tech2' and c['location_id'] in ('taken','not_taken'))
        self.assertEqual(total,3)

    def test_aliases_merge_without_changing_original_and_free_collapses_only_setup_modes(self):
        row=copy.deepcopy(self.rows[0]);row['technologies']={'free1':'1q_1o','free2':'tech1','free3':'tech4'}
        row['owned_technologies']=[{'tile':'tech1','slot':'free1'}]
        for kind in ('basic-tech-frequency','basic-tech-setup-score'):
            c=self.cell(kind,'tech1','free',rows=[row])
            self.assertEqual(c['samples'],1)
        c=self.cell('basic-tech-score','tech1','free1',rows=[row]);self.assertEqual(c['samples'],1)
        self.assertEqual(row['technologies']['free1'],'1q_1o')
        a=copy.deepcopy(row);a['game_id']='other';a['technologies']={'free1':'tech1'}
        c=self.cell('basic-tech-setup-score','tech1','free',rows=[row,a]);self.assertEqual(c['samples'],2)

    def test_no_twilight_technology_or_fabricated_conflicting_ship(self):
        self.assertFalse(any(c['location_id']=='twilight' for c in self.plot('basic-tech-frequency')['cells']))
        rows=copy.deepcopy(self.rows);rows[0]['ship_technologies']['tfmars']['tile']='ship-tech-range'
        self.assertFalse(any(c['location_id']=='tfmars' for c in self.plot('basic-tech-setup-score',rows)['cells']))
        self.assertEqual(self.plot('basic-tech-setup-score',rows)['unavailable_records'],4)

    def test_streaming_pools_counts_and_means_not_batch_averages(self):
        second=copy.deepcopy(self.rows)
        for row in second:row['game_id']='second';row['score']+=33
        second[0]['owned_technologies']=None
        for kind in KINDS:
            filters={'ruleset':'lost-fleet','plot':kind}
            expected=report({'rows':self.rows+second,'scope':'test'},filters)
            actual=streamed(iter([self.rows,second]),filters,'test')
            self.assertEqual(actual['plots'][kind],expected['plots'][kind])

    def test_elo_and_faction_filters_still_apply_to_all_modes(self):
        for kind in KINDS:
            p=self.plot(kind,faction=self.rows[0]['faction'],min_elo='99999')
            self.assertEqual(p['cells'],[])
