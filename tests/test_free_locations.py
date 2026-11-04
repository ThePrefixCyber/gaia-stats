"""Free is one analytical category, never an average of three slot averages."""
import copy
import csv
import io
import json
import unittest
from pathlib import Path

from gaia_stats.analysis import normalize
from gaia_stats.basic_tech import KINDS
from gaia_stats.cohort import enrich, export, report
from gaia_stats.score_basis import analysis_rows
from gaia_stats.scoring_views import ScoringViews
from gaia_stats.streaming_cohort import statistics as streamed
from gaia_stats.technology_locations import location, sources


class FreeLocationTests(unittest.TestCase):
    def setUp(self):
        raw = json.loads((Path(__file__).parent/'fixtures/Jubilant-rover-3041.json').read_text())
        self.rows = enrich(raw, normalize(raw))

    def test_only_exact_free_locations_merge(self):
        for slot in ('free1', 'free2', 'free3'):
            self.assertEqual(location(slot), 'free')
        for slot in ('free', 'free4', 'free10', 'adv-free1', 'terra', 'tfmars'):
            self.assertEqual(location(slot), slot)

    def test_basic_views_deduplicate_per_tile_player_game_not_nonfree_locations(self):
        rows = copy.deepcopy(self.rows)
        for i, row in enumerate(rows):
            row.update(score=[120, 130, 140, 210][i], technologies={
                'free1':'1q_1o', 'free2':'tech1', 'free3':'tech4', 'terra':'tech1'},
                ship_technologies={}, owned_technologies=[
                    {'tile':'tech1','slot':'free1'}, {'tile':'tech1','slot':'free2'},
                    {'tile':'tech1','slot':'free2'}, {'tile':'tech1','slot':'terra'},
                    {'tile':'tech4','slot':'free3'}])
        before = copy.deepcopy(rows)
        for kind in KINDS:
            plot = report({'rows':rows}, {'ruleset':'lost-fleet','plot':kind})['plots'][kind]
            cells = {(c['tile_id'], c['location_id']):c for c in plot['cells']}
            for key in (('tech1','free'), ('tech1','terra'), ('tech4','free')):
                self.assertEqual((cells[key]['samples'],cells[key]['games'],cells[key]['mean_score']), (4,1,150))
            self.assertFalse(any(c['location_id'] in ('free1','free2','free3') for c in plot['cells']))
            if kind == 'basic-tech-frequency':
                self.assertEqual((cells['tech1','free']['available'], cells['tech1','free']['frequency']), (4,1))
        self.assertEqual(rows, before)

    def test_unequal_slot_counts_and_streaming_use_observation_weights(self):
        batches = []
        for game, slot, score, taken in [('a','free1',120,3), ('b','free3',200,1)]:
            rows = copy.deepcopy(self.rows)
            for i, row in enumerate(rows):
                row.update(game_id=game, score=score, technologies={slot:'tech1'}, ship_technologies={},
                           owned_technologies=[{'tile':'tech1','slot':slot}] if i<taken else [])
            batches.append(rows)
        filters = {'ruleset':'lost-fleet','plot':'basic-tech-score'}
        expected = report({'rows':sum(batches,[]),'scope':'test'}, filters)
        actual = streamed(iter(batches), filters, 'test')
        self.assertEqual(expected, actual)
        free = next(c for c in expected['plots']['basic-tech-score']['cells'] if c['location_id']=='free')
        self.assertEqual((free['samples'],free['games'],free['mean_score']), (4,2,140))

    def test_vp_sources_sum_before_statistics_and_keep_originals(self):
        rows = copy.deepcopy(self.rows)
        originals = [
            {'tech-free1':3,'tech-free2':9,'tech-free3':-2,'tech-terra':5,'tech-free10':8},
            {'tech-free2':20,'tech-terra':7},
            {},
            {'tech-free3':5},
        ]
        for row, values in zip(rows, originals):
            row.update(score=100, vp_sources=values, vp_sources_audit=copy.deepcopy(values),
                       vp_sources_raw=copy.deepcopy(values), vp_ledger_complete=True)
        normalized = analysis_rows(rows)
        self.assertEqual(normalized[0]['vp_sources']['tech-free'], 10)
        self.assertEqual(normalized[0]['vp_sources']['tech-free10'], 8)
        self.assertEqual(normalized[0]['vp_sources']['tech-terra'], 5)
        self.assertEqual(analysis_rows(normalized), normalized)
        for row, original in zip(normalized, originals):
            self.assertEqual(row['vp_sources_audit'], original)
            self.assertEqual(row['vp_sources_raw'], original)
            self.assertEqual(sum(row['vp_sources'].values()), sum(original.values()))
        filters = {'ruleset':'lost-fleet','plot':'point-sources'}
        expected = report({'rows':rows,'scope':'test'}, filters)
        self.assertEqual(streamed(iter([rows]), filters, 'test'), expected)
        cells = {c['label']:c for c in expected['plots']['point-sources']['cells']}
        self.assertFalse({'tech-free1','tech-free2','tech-free3'} & cells.keys())
        self.assertEqual(cells['tech-free']['values'], [10,20,0,5])
        self.assertEqual(cells['tech-free']['samples'], 4)
        self.assertEqual(cells['tech-free']['median'], 7.5)
        exported = list(csv.DictReader(io.StringIO(export({'rows':rows},filters).decode())))
        for row, original in zip(exported, originals):
            self.assertFalse({'tech-free1','tech-free2','tech-free3'} & json.loads(row['vp_sources']).keys())
            self.assertEqual(json.loads(row['vp_sources_raw']), original)
            self.assertEqual(json.loads(row['vp_sources_audit']), original)

    def test_unknown_components_stay_unknown_and_late_batches_receive_one_zero(self):
        self.assertEqual(sources({'tech-free1':5}), {'tech-free':None})
        self.assertEqual(sources({'tech-free1':5,'tech-free2':None,'tech-free3':3}, complete=True), {'tech-free':None})
        self.assertEqual(sources({'tech-free1':5,'tech-free2':0,'tech-free3':3}), {'tech-free':8})
        self.assertEqual(sources({'tech-free':8}), {'tech-free':8})
        rows = copy.deepcopy(self.rows)
        for row, values in zip(rows, [{},{'tech-free1':5,'tech-free3':8},{'tech-free2':None},{'tech-free1':7}]):
            row.update(score=100,rank=1, vp_sources=values, vp_ledger_complete=True)
        rows[-1]['vp_ledger_complete'] = False
        view = ScoringViews({})
        for row in rows:
            view.add_points([row])
        cells = {c['label']:c for c in view.points()['rank_cells']}
        self.assertFalse({'tech-free1','tech-free2','tech-free3'} & cells.keys())
        self.assertEqual(cells['tech-free']['values'], [13,0])
        self.assertEqual(cells['tech-free']['samples'], 2)

    def test_absolute_vp_distributions_omit_unknown_free_totals(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            row.update(vp_sources={'tech-free1':5}, vp_ledger_complete=False)
        filters = {'ruleset':'lost-fleet','plot':'point-sources'}
        expected = report({'rows':rows,'scope':'test'}, filters)
        self.assertEqual(streamed(iter([rows]), filters, 'test'), expected)
        cell = next(c for c in expected['plots']['point-sources']['cells'] if c['label']=='tech-free')
        self.assertEqual(cell, {'label':'tech-free','samples':0,'values':[]})
