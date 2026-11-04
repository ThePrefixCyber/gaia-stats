import copy
import csv
import json
from pathlib import Path
import sqlite3
import unittest

from gaia_stats.analysis import normalize, select
from gaia_stats.cohort import report, export
from gaia_stats.score_basis import (analysis_rows, csv_score, csv_sources, row_score,
                                    raw_scores, BASE_SCORE_SQL, SCORE_BASIS_VERSION)

ROOT = Path(__file__).resolve().parents[1]


class PrebidScoreTests(unittest.TestCase):
    def test_nordic_actual_results_are_236_and_128_everywhere(self):
        game = json.loads((ROOT/'tests/fixtures/auction/Nordic-cage-6717.json').read_text())
        rows = normalize(game)
        by_faction = {row['faction']:row for row in rows}
        self.assertEqual((by_faction['geodens']['reported_score'],by_faction['geodens']['score']),(221,236))
        self.assertEqual((by_faction['darkanians']['reported_score'],by_faction['darkanians']['score']),(113,128))
        self.assertEqual(by_faction['darkanians']['vp_sources']['explore'],-15)
        result = report({'rows':rows},{'ruleset':'lost-fleet','faction':'geodens'})
        self.assertEqual(result['mean_score'],236)
        self.assertEqual(next(row for row in result['comparisons'] if row['faction']=='geodens')['mean_score'],236)
        for row in rows:
            self.assertEqual(sum(row['vp_sources'].values()),row['score'])
            self.assertEqual(sum(row['vp_sources_raw'].values()),row['reported_score'])

    def test_fixed_classic_colors_and_typed_sql_parity(self):
        from gaia_stats.score_colors import color, marker
        self.assertEqual([color(value) for value in (0,100,200)],['#ff3b30','#d1d5db','#081d58'])
        for values in ([128,236],[128,236,500]):
            colors = marker(values)
            for score in values:
                stop=(score-colors['cmin'])/(colors['cmax']-colors['cmin'])
                self.assertEqual(next(c for v,c in colors['colorscale'] if v==stop),color(score))
        for invalid in ('120',True,None,float('nan')):
            self.assertIsNone(row_score({'score_basis_version':SCORE_BASIS_VERSION,'score':invalid}))
        self.assertEqual(raw_scores(None),[])
        self.assertEqual(raw_scores({'players':None}),[])

    def test_raw_signed_bid_changes_rank_and_preserves_audit(self):
        game = json.loads((ROOT/'tests/fixtures/Modern-riddle-1723.json').read_text())
        rows = normalize(game)
        for row in rows: row['faction_variant']='standard'; row['faction_variant_sources']={}
        self.assertEqual([r['reported_score'] for r in rows], [172,156,144,139])
        self.assertEqual([r['score'] for r in rows], [172,173,162,139])
        self.assertEqual([r['rank'] for r in rows], [2,1,3,4])
        self.assertEqual([r['reported_rank'] for r in rows], [1,2,3,4])
        self.assertEqual(raw_scores(game), [172,173,162,139])
        for row in rows:
            self.assertNotIn('bid', row['vp_sources'])
            self.assertEqual(sum(row['vp_sources'].values()), row['score'])
            self.assertEqual(sum(row['vp_sources_raw'].values()), row['reported_score'])
        self.assertEqual(analysis_rows(rows), rows)
        self.assertEqual(select(rows, {'ruleset':'base','faction':rows[1]['faction']})[0]['rank'],1)

    def test_csv_own_cost_and_net_rank_source_mapping(self):
        with (ROOT/'data/remote_four_players_data.csv').open() as handle:
            game = next(g for g in csv.DictReader(handle) if g['id']=='Obsolete-mushroom-5157')
        self.assertEqual(csv_score(game,1),179)
        self.assertEqual(float(game['pos_1_score_bid']),0)
        sources, rank = csv_sources(game,1)
        self.assertEqual(rank,2)
        self.assertEqual(sources['bid'],-24)
        self.assertEqual(sum(sources.values())+float(game['pos_1_tech_score']),155)
        game['pos_1_bid']=''
        self.assertIsNone(csv_score(game,1))

    def test_tied_csv_sources_unavailable_but_totals_known(self):
        with (ROOT/'data/remote_four_players_data.csv').open() as handle:
            game = next(g for g in csv.DictReader(handle) if g['id']=='Princely-story-9148')
        for p in range(1,5):
            self.assertIsNotNone(csv_score(game,p))
            if float(game[f'pos_{p}_score'])==166:
                self.assertEqual(csv_sources(game,p),({},None))

    def test_old_csv_unknown_and_sql_matches_old_raw_and_new_rows(self):
        old = {'game_id':'g','ruleset':'base','score':155,'bid':0,'vp_sources':{'bid':0},'vp_ledger_complete':False}
        raw = {**old,'vp_sources_raw':{'bid':-24},'vp_ledger_complete':True}
        new = {**old,'score':179,'reported_score':155,'bid_cost':24,'bid_delta':-24,'score_basis_version':SCORE_BASIS_VERSION}
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE observations (payload TEXT)')
            for row, expected in [(old,None),(raw,179),(new,179)]:
                self.assertEqual(row_score(row),expected)
                db.execute('DELETE FROM observations')
                db.execute('INSERT INTO observations VALUES (?)',(json.dumps(row),))
                self.assertEqual(db.execute('SELECT '+BASE_SCORE_SQL+' FROM observations').fetchone()[0],expected)

    def test_every_live_stat_and_export_uses_prebid_and_omits_bid_source(self):
        rows = normalize(json.loads((ROOT/'tests/fixtures/Modern-riddle-1723.json').read_text()))
        for row in rows: row['faction_variant']='standard'; row['faction_variant_sources']={}
        result = report({'rows':rows},{'ruleset':'base'})
        self.assertEqual(result['mean_score'],161.5)
        for plot in result['plots'].values():
            self.assertNotIn('bid',[c['label'] for c in plot['cells']])
        points=result['plots']['point-sources']
        self.assertNotIn('bid',[c['label'] for c in points['rank_cells']])
        header=export({'rows':rows},{'ruleset':'base'}).decode().splitlines()[0]
        for name in ('score','reported_score','bid_delta','score_basis_version'):
            self.assertIn(name,header)


if __name__=='__main__':unittest.main()
