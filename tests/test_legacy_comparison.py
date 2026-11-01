import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gaia_stats.legacy_comparison import (ADVANCED_TILES, ROUND_TILES, TRACKS,
    compare, validate_aggregates)
from gaia_stats.legacy_cache import build_cache, cache_response


def aggregates():
    faction = {'round_scoring': {}, 'final_scoring': {'planetType': {'structure': {
        'points': 24, 'vict_prob': 51, 'delta_vict_prob': 2}}}, 'advanced_tech': {}}
    for i, tile in enumerate(ROUND_TILES[:6], 1):
        faction['round_scoring'][tile] = {str(i): {'points': i, 'vict_prob': 40+i, 'delta_vict_prob': i-3}}
    for tile, track in zip(ADVANCED_TILES, TRACKS):
        faction['advanced_tech'][tile] = {'tech_adv-'+track: {'score': 180, 'count': 2, 'missed': 6}}
    return {str(p): {'terrans': copy.deepcopy(faction)} for p in (2, 3, 4)}


class ComparisonTests(unittest.TestCase):
    def test_all_counts_preserve_original_round_and_final_contract(self):
        for p in ('2', '3', '4'):
            result = compare(aggregates(), {'num_players': p})
            row = result['rows'][0]
            self.assertEqual(result['players'], int(p))
            self.assertEqual(row['round'], {'points': 21, 'vict_prob': 43.5, 'delta_vict_prob': .5})
            self.assertEqual(row['final'], {'points': 24, 'vict_prob': 51, 'delta_vict_prob': 2})

    def test_gaia_denominator_and_observation_weighting(self):
        data = aggregates()
        data['2']['terrans']['advanced_tech'][ADVANCED_TILES[3]]['tech_adv-gaia'] = {
            'score': 200, 'count': 4, 'missed': 0}
        advanced = compare(data, {'num_players': '2'})['rows'][0]['advanced']
        self.assertEqual(advanced['weighted_sum'], 5*45+200)
        self.assertEqual(advanced['max_weighted_score'], {'value': 200, 'tile': ADVANCED_TILES[3]})
        self.assertEqual(advanced['observed_tracks'], 6)

    def test_missing_nonfinite_and_zero_count_cells_are_not_zero(self):
        data = aggregates(); source = data['4']['terrans']
        del source['round_scoring'][ROUND_TILES[0]]
        source['final_scoring']['planetType']['structure']['points'] = float('nan')
        source['advanced_tech'][ADVANCED_TILES[0]]['tech_adv-terra']['count'] = 0
        row = compare(data, {})['rows'][0]
        self.assertIsNone(row['round']['points'])
        self.assertIsNone(row['final']['points'])
        self.assertIsNone(row['advanced']['weighted_sum'])
        self.assertEqual(row['advanced']['observed_tracks'], 5)
        absent = compare(data, {})['rows'][1]
        self.assertIsNone(absent['advanced']['max_score'])
        json.dumps(compare(data, {}), allow_nan=False)

    def test_invalid_selections_and_legal_duplicate_round_tile(self):
        for query in ({'num_players':'5'}, {'round_1':'unknown'}, {'round_2':ROUND_TILES[0]},
                      {'adv_2':ADVANCED_TILES[0]}, {'final_2':'planetType'}):
            with self.subTest(query=query), self.assertRaises(ValueError): compare(aggregates(), query)
        result=compare(aggregates(), {'round_1':'5vp_per_3pip_place','round_2':'5vp_per_3pip_place'})
        self.assertEqual(result['rounds'].count('5vp_per_3pip_place'), 2)
        with self.assertRaises(ValueError): compare({'2': {}}, {'num_players':'3'})

    def test_aggregate_schema_rejects_unrelated_data(self):
        validate_aggregates(aggregates())
        for data in ({}, {'5':{}}, {'2':{'terrans':{}}}, {'2':{'unknown':{}}}):
            with self.assertRaises(ValueError):validate_aggregates(data)

    def test_cache_imports_exact_bytes_and_serves_comparisons_without_plotting(self):
        import plotly.graph_objects as go
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'dat.json';source.write_text(json.dumps(aggregates()))
            csvs={}
            for p in (2,3,4):
                csvs[p]=root/f'{p}.csv'
                csvs[p].write_text('Unnamed: 0,num_players,'+','.join(f'pos_{i}_faction' for i in range(1,p+1))+'\n0,'+str(p)+','+','.join(['terrans']*p)+'\n')
            with patch('gaia_stats.corrected_plots.observations',return_value=[]), patch('gaia_stats.legacy_plots.make_plot',return_value=go.Figure()), patch('gaia_stats.legacy_cache.FACTIONS',('terrans',)):
                manifest=build_cache(root/'cache',csvs,source)
            self.assertEqual(manifest['comparisons']['player_counts'],['2','3','4'])
            for p in (2,3,4):
                self.assertEqual(cache_response(root/'cache',f'/classic/data/{p}.csv',{})[0],csvs[p].read_bytes())
                body=cache_response(root/'cache','/classic/api/comparison',{'num_players':str(p)})[0]
                self.assertEqual(json.loads(body)['rows'][0]['round']['points'],21)
            for path in ('/classic/compare','/view_tables/index.html'):
                self.assertIn(b'Historical faction results',cache_response(root/'cache',path,{})[0])
            self.assertIn(b'openComparisonWizard',cache_response(root/'cache','/classic/assets/comparison.js',{})[0])
            pointer=(root/'cache/current.json').read_bytes();source.write_text('{"unrelated":true}')
            with patch('gaia_stats.corrected_plots.observations',return_value=[]), patch('gaia_stats.legacy_plots.make_plot',return_value=go.Figure()),patch('gaia_stats.legacy_cache.FACTIONS',('terrans',)),self.assertRaises(ValueError):
                build_cache(root/'cache',csvs,source)
            self.assertEqual((root/'cache/current.json').read_bytes(),pointer)
