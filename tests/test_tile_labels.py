"""Presentation registry invariants; no new runtime or test dependency."""
import json
import unittest
from pathlib import Path
from gaia_stats.cohort import response
from gaia_stats.wsgi import Application

ROOT = Path(__file__).resolve().parents[1]

class TileLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.labels = json.loads((ROOT/'web/cohort/tile-labels.json').read_text())

    def test_complete_tile_families(self):
        for category, ids in {
            'advanced': {f'advtech{i}' for i in range(1,16)} | {'advtech-'+s for s in ('asteroidpass','big','deep','deeppass','qaction','terra')},
            'basic': {f'tech{i}' for i in range(1,10)} | {'ship-tech-'+s for s in ('range','terraform','resource')},
            'round': {f'score{i}' for i in range(1,11)} | {'lflab4','lfsector3','lfplanet3'},
            'final': {'structure','structureFed','planetType','gaia','sector','satellite','asteroid','deepSpaceSector','piAcademyDistance'},
            'booster': {f'booster{i}' for i in range(1,11)} | {'booster-lostfleet-'+s for s in ('former','planet','deep','instant')},
        }.items():
            self.assertEqual(set(self.labels[category]),ids)
        for category in self.labels.values():
            for entry in category.values():
                self.assertTrue(entry['description'])
                self.assertIsInstance(entry['aliases'],list)

    def test_timing_and_misleading_historical_aliases(self):
        advanced=self.labels['advanced']
        self.assertTrue(advanced['advtech4']['description'].startswith('Immediate:'))
        self.assertTrue(advanced['advtech14']['description'].startswith('Each mine'))
        self.assertIn('current trading station',advanced['advtech9']['description'])
        self.assertIn('Each trading station',advanced['advtech15']['description'])
        self.assertIn('planet type',advanced['advtech7']['description'])
        self.assertIn('1vp_per_terra_pass',advanced['advtech7']['aliases'])
        self.assertIn('planet type',self.labels['basic']['tech2']['description'])
        self.assertIn('power tokens',self.labels['booster']['booster2']['description'])
        self.assertIn('charge 1 power',self.labels['basic']['tech5']['description'])
        self.assertEqual(self.labels['round']['score7']['description'],self.labels['round']['score10']['description'])
        self.assertNotIn('adv-terra',advanced)

    def test_aliases_match_committed_tim_parser(self):
        notebook=json.loads((ROOT/'parse_jsons.ipynb').read_text())
        code='\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type']=='code')
        for category in ('advanced','basic','round','booster'):
            for entry in self.labels[category].values():
                for alias in entry['aliases']:
                    self.assertIn(alias,code)

    def test_asset_embeds_valid_registry_without_dataset(self):
        body,mime=response(None,'/cohort/tile-labels.js',{})
        self.assertEqual(mime,'application/javascript')
        self.assertNotIn(b'__TILE_REGISTRY__',body)
        self.assertIn(b'advtech-deeppass',body)
        # The presentation resource must remain available even if data loading fails.
        app=Application.__new__(Application)
        app.load=lambda: self.fail('Static labels must not read production data')
        self.assertEqual(app.cohort_response('/cohort/tile-labels.js',{}),(body,mime))

    def test_pages_load_shared_labels_before_usage(self):
        for name in ('cohort/index','classic/index','classic/compare','classic/plot'):
            page=(ROOT/'web'/f'{name}.html').read_text()
            self.assertEqual(page.count('src="/cohort/tile-labels.js"'),1)
            self.assertIn('id="tile-key"',page)
            self.assertIn('GaiaTiles.glossary',page)
