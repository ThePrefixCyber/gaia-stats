import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from gaia_stats.analysis import normalize
from gaia_stats.archive import listing_entries, listing_slug
from gaia_stats.cohort import enrich, build, report, export, statistics, PLOTS
from gaia_stats.wsgi import Application

FIXTURES = Path(__file__).parent / 'fixtures'


def load(path):
    return json.loads(path.read_text())


class CohortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.games = [load(FIXTURES / 'Jubilant-rover-3041.json')]
        cls.games += [load(FIXTURES / 'cohort' / name) for name in
                      ('Admirable-falcon-401.json', 'Eclipsed-council-7948.json')]
        cls.rows = [r for g in cls.games for r in enrich(g, normalize(g))]
        cls.dataset = {'schema_version': 1, 'rows': cls.rows}

    def test_real_factions_and_ship_vp(self):
        self.assertTrue({'moweyds','tinkeroids','darkanians','space-giants'} <= {r['faction'] for r in self.rows})
        for row in self.rows:
            self.assertEqual(sum(row['vp_sources'].values()), row['score'])
        for row in self.rows:
            if row['faction'] in ('moweyds','darkanians','space-giants'):
                self.assertEqual(row['initial_structures'], {'m':1})
            elif row['faction']=='tinkeroids':
                self.assertEqual(row['initial_structures'], {'PI':1})
        self.assertTrue(any(r['vp_sources'].get('tfmars', 0) for r in self.rows))
        self.assertTrue(any(t['tile'].startswith('ship-tech-') for r in self.rows for t in r['owned_technologies']))

    def test_tinkeroids_setup_pi_and_covered_tech(self):
        row = next(r for r in self.rows if r['game_id']=='Jubilant-rover-3041' and r['faction']=='tinkeroids')
        self.assertEqual(row['round_one_structures']['PI'], 1)
        self.assertIn({'tile':'tech2','slot':'nav'}, row['owned_technologies'])

    def test_default_variant_and_mode_isolation(self):
        base = normalize(load(FIXTURES / 'Modern-riddle-1723.json'))
        data = {'rows': self.rows + base}
        standard = report(data, {'ruleset':'lost-fleet'})
        both = report(data, {'ruleset':'lost-fleet','lf_2p_4qic_mode':'include-both'})
        variant = report(data, {'ruleset':'lost-fleet','lf_2p_4qic_mode':'variant-only'})
        self.assertEqual(variant['samples'],2)
        self.assertEqual(standard['samples']+variant['samples'],both['samples'])
        self.assertEqual(report(data, {'ruleset':'base'})['samples'],len(base))
        self.assertFalse(set(standard['record_ids']) & set(variant['record_ids']))

    def test_elo_missing_and_consistent_exports(self):
        rows = copy.deepcopy(self.rows)
        rows[0]['elo'] = None
        data = {'rows':rows}
        for mode in ('standard-only','include-both','variant-only'):
            filters = {'ruleset':'lost-fleet','lf_2p_4qic_mode':mode,'min_elo':'0'}
            result = report(data, filters)
            exported = list(csv.DictReader(io.StringIO(export(data,filters).decode())))
            self.assertEqual(result['missing_elo'],0)
            self.assertEqual(result['samples'],len(exported))
            self.assertEqual(set(result['record_ids']), {r['game_id']+':'+r['faction'] for r in exported})
            self.assertEqual(sum(r['samples'] for r in result['comparisons']),result['samples'])
            for cell in result['plots']['point-sources']['cells']:
                self.assertEqual(len(cell['values']),result['samples'])

    def test_all_plot_families_and_empty_cells(self):
        for kind in PLOTS:
            result=statistics(self.rows,kind)
            self.assertTrue(result['cells'])
            self.assertEqual(statistics([],kind)['cells'],[])
        result=statistics(self.rows,'basic-tech-frequency')
        for cell in result['cells']:
            self.assertLessEqual(cell['samples'],cell['available'])
        rows=copy.deepcopy(self.rows)
        for r in rows:r['round_one_structures']=None
        result=statistics(rows,'round-one-structures')
        self.assertEqual(result['unavailable_records'],len(rows))
        self.assertEqual(result['cells'],[])

    def test_setup_and_options_filters_share_one_cohort(self):
        row=self.rows[0]
        filters={'ruleset':'lost-fleet','layout':row['layout'],'auction':row['auction'],
                 'faction_variant':row['faction_variant'],'round1':row['round_scorings'][0],
                 'adv-terra':row['technologies']['adv-terra'],'final_scoring2':row['final_scorings'][1]}
        self.assertGreater(report(self.dataset,filters)['samples'],0)
        filters['adv-terra']='nonexistent'
        self.assertEqual(report(self.dataset,filters)['samples'],0)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(export(self.dataset,filters).decode())))),0)

    def test_real_listing_ids_and_lookahead(self):
        first=listing_entries(load(FIXTURES/'cohort/listing-000.json'))
        second=listing_entries(load(FIXTURES/'cohort/listing-010.json'))
        self.assertEqual(len(first),11)
        self.assertEqual(listing_slug(first[-1]),listing_slug(second[0]))
        self.assertEqual(len({listing_slug(x) for x in first[:10]+second[:10]}),20)
        with self.assertRaises(ValueError):listing_slug({'_id':'one','slug':'two'})
        with self.assertRaises(ValueError):listing_entries({'games':first})

    def test_wsgi_api_and_csv_use_same_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'analysis.json';path.write_text(json.dumps(self.dataset))
            app=Application(path)
            def get(route):
                status=[]
                body=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':route,'QUERY_STRING':'ruleset=lost-fleet&player_count=2&lf_2p_4qic_mode=variant-only'},lambda s,h:status.append(s)))
                self.assertEqual(status,['200 OK'])
                return body
            result=json.loads(get('/cohort/api/stats'))
            records=list(csv.DictReader(io.StringIO(get('/cohort/api/export').decode())))
            self.assertEqual(result['samples'],len(records))
            self.assertEqual(result['samples'],2)

    def test_lf_comparisons_include_observed_zero_scoring(self):
        rows=copy.deepcopy(self.rows)
        for r in rows:r['vp_sources'].pop('round1',None)
        result=report({'rows':rows},{'ruleset':'lost-fleet','lf_2p_4qic_mode':'include-both'})
        for r in result['setup_comparisons']['rounds']:
            self.assertEqual(r['round1'],0)
            self.assertEqual(r['round1_n'],r['samples'])
