import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from gaia_stats.analysis import normalize
from gaia_stats.cohort import statistics, report
from gaia_stats.archive import collect
from gaia_stats.releases import source_identity
from gaia_stats.scoring import NORMALIZATION_VERSION
from test_archive import FakeClient, game

FIXTURES=Path(__file__).parent/'fixtures'


def load(slug):
    path=FIXTURES/'cohort'/(slug+'.json')
    if not path.exists():path=FIXTURES/(slug+'.json')
    return json.loads(path.read_text())


class ScoringTests(unittest.TestCase):
    def test_base_categories_and_phase_specific_research(self):
        rows=normalize(load('Silly-rocket-2154'));terrans=rows[0]
        expected={'init':10,'bid':0,'charge':-8,'booster':26,'fed':22,'adv':12,
                  'tech_basic':0,'qic':9,'gaia':0,'gleens':0,'resource':2,'research':20,
                  'round1':4,'round2':4,'round3':3,'round4':5,'round5':0,'round6':2,'final1':18,'final2':12}
        self.assertEqual(terrans['vp_sources'],expected)
        self.assertEqual(terrans['vp_sources_raw']['initial'],10)
        raw=normalize(load('Vibrant-flagship-1713'))[1]
        self.assertEqual(raw['vp_sources_raw']['gaia'],25)
        self.assertEqual(raw['vp_sources']['gaia'],13)
        self.assertEqual(raw['vp_sources']['research'],24)
        for row in rows+[raw]:
            self.assertTrue(row['vp_ledger_complete'])
            self.assertEqual(sum(row['vp_sources'].values()),row['score'])
            self.assertEqual(sum(row['vp_sources_raw'].values()),row['score'])

    def test_complete_base_zero_rounds_and_finals_but_historical_unknown(self):
        rows=normalize(load('Shiny-cypress-1384'));ivits=rows[0]
        self.assertNotIn('final1',ivits['vp_sources_raw'])
        self.assertEqual(ivits['scoring_vp']['final1'],0)
        self.assertEqual(ivits['scoring_vp']['final2'],0)
        self.assertEqual(ivits['scoring_vp']['round2'],0)
        cells=statistics(rows,'final-scoring')['cells']
        self.assertEqual([c['score_samples'] for c in cells],[1]*4)
        self.assertEqual(sorted(c['mean_score'] for c in cells),[0,12,24,36])
        historical=copy.deepcopy(ivits)
        historical.pop('scoring_vp');historical['vp_ledger_complete']=False
        historical['vp_sources'].pop('final1')
        result=statistics([historical],'final-scoring')
        self.assertIsNone(result['cells'][0]['mean_score'])
        self.assertEqual(result['cells'][0]['score_samples'],0)
        self.assertEqual(result['unavailable_records'],1)

    def test_lf_tile_earned_vp_is_not_conditional_final_score(self):
        rows=normalize(load('Jubilant-rover-3041'))
        finals=statistics(rows,'final-scoring')
        self.assertEqual(finals['value_label'],'Mean VP earned from scoring tile(s)')
        self.assertEqual(len(finals['cells']),4)
        for cell in finals['cells']:
            row=next(r for r in rows if r['faction']==cell['faction'])
            self.assertEqual(cell['mean_score'],row['scoring_vp']['final1']+row['scoring_vp']['final2'])
            self.assertEqual(cell['score_samples'],1)
            self.assertEqual(cell['mean_final_score'],row['score'])
        rounds=statistics(rows,'round-scoring')['cells']
        self.assertEqual([c['mean_score']for c in rounds],[4.5,3.75,3.75,5,4,5])
        self.assertTrue(all(c['score_samples']==4 for c in rounds))
        result=report({'rows':rows},{'ruleset':'lost-fleet'})
        hh=next(r for r in result['setup_comparisons']['rounds']if r['faction']=='hadsch-hallas')
        self.assertEqual((hh['round1'],hh['round1_n']),(0,1))
        for slug,expected in [('Admirable-falcon-401',24),('Eclipsed-council-7948',30)]:
            rows=normalize(load(slug))
            cells=statistics(rows,'final-scoring')['cells']
            self.assertEqual(sum(c['mean_score'] for c in cells)/len(cells),expected)

    def test_ambiguous_phase_and_unmapped_sources_never_invent_scoring(self):
        payload=load('Silly-rocket-2154')
        payload['data']['advancedLog'].append({'player':0,'changes':{'round1':{'vp':3},'new-mechanism':{'vp':2}}})
        payload['players'][0]['score']+=5
        row=normalize(payload)[0]
        self.assertTrue(row['score_verified'])
        self.assertIsNone(row['scoring_vp'])
        self.assertEqual(row['vp_sources']['unmapped:round1'],3)
        self.assertEqual(row['vp_sources']['unmapped:new-mechanism'],2)
        self.assertEqual(sum(row['vp_sources'].values()),row['score'])
        self.assertIsNone(statistics([row],'final-scoring')['cells'][0]['mean_score'])

    def test_normalization_version_forces_release_recompute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed=root/'seed';seed.write_bytes(b'fixed input')
            identity=source_identity(seed,root/'archive',None)
            self.assertEqual(identity['normalization_version'],NORMALIZATION_VERSION)
            old={k:v for k,v in identity.items()if k!='normalization_version'}
            self.assertNotEqual(identity,old)


class ListingExclusionTests(unittest.TestCase):
    def test_explicit_lf_skipped_unknown_and_conflicting_downloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            games={'lf':game('lf'),'base':game('base',False),'conflict':game('conflict',False)}
            class Client(FakeClient):
                def get(self,url):
                    payload,raw=super().get(url)
                    if '/status/ended?'in url:
                        for entry in payload:
                            if entry['slug']=='lf':entry['game']={'expansions':['lost-fleet']}
                            if entry['slug']=='base':entry['players']=[{'faction':'space-giants'}] # Never classify by faction.
                            if entry['slug']=='conflict':entry['game']={'expansions':['lost-fleet'],'options':{'lostFleet':False}}
                    return payload,raw
            client=Client(games)
            result=collect(Path(tmp),'base',client=client,max_pages=1,max_downloads=3)
            self.assertEqual(result['skipped'],1)
            self.assertEqual(result['accepted'],2)
            self.assertEqual(client.exports,['base','conflict'])
            evidence=json.loads((Path(tmp)/'base/listing-skipped/lf.json').read_text())
            self.assertEqual(evidence['entry']['game']['expansions'],['lost-fleet'])
            again=collect(Path(tmp),'base',client=client,max_pages=1,max_downloads=3)
            self.assertEqual(again['skipped'],0)
            self.assertEqual(client.exports,['base','conflict'])

    def test_old_pending_queue_uses_validated_lf_archive_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=FakeClient({'known':game('known')})
            collect(root,'base',client=client,max_pages=1,max_downloads=0)
            collect(root,'lost-fleet',client=client,max_pages=1,max_downloads=1)
            result=collect(root,'base',client=client,max_pages=1,max_downloads=1)
            self.assertEqual(result['skipped'],1);self.assertEqual(client.exports,['known'])
            with sqlite3.connect(root/'archive.sqlite3') as db:
                self.assertEqual(db.execute("SELECT status,attempts FROM exports WHERE mode='base'").fetchone(),('skipped',0))
