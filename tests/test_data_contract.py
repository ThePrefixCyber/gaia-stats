"""Standalone deployment verification, independent of all application modules."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_data_contract', ROOT/'deploy/check-data-contract.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class DataContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name)
        self.root = self.bundle/'releases-store'; self.cache = self.bundle/'classic-cache'
        self.seed = self.bundle/'seeds/base.sqlite'
        self.release = self.root/'releases/release-test'; self.build = self.cache/'build-test'
        for folder in (self.seed.parent, self.release, self.build/'plots', self.build/'data'):
            folder.mkdir(parents=True, exist_ok=True)
        self.contract = dict(schema_version=1, eligibility_policy=3, score_basis_version='prebid-v1', normalization_version=3)
        self.contract_path = self.bundle/'contract.json'; self.write(self.contract_path, self.contract)
        self.write(self.bundle/'preparation.json', {'state':'ready'})
        self.rows = [dict(game_id='base', faction=faction, ruleset='base', player_count=2,
                         reported_score=reported, score=score, bid_delta=delta,
                         rank=rank, win_share=win, score_basis_version='prebid-v1',
                         normalization_version=2, faction_variant='standard', vp_sources={'initial':10})
                     for faction, reported, score, delta, rank, win in
                     [('terrans', 75, 125, -50, 2, 0), ('xenos', 150, 150, 0, 1, 1)]]
        self.database(self.seed, self.rows); self.database(self.release/'base.sqlite', self.rows)
        lf = [dict(row, game_id='lf', ruleset='lost-fleet') for row in self.rows]
        self.write(self.release/'lost-fleet.json', {'rows':lf})
        self.manifest = dict(self.contract, release='release-test',
                             inputs=dict(normalization_version=3, score_basis_version='prebid-v1', seed=guard.digest(self.seed)),
                             datasets={'base':{'games':1,'records':2},'lost-fleet':{'games':1,'records':2}},
                             excluded_game_ids=[], sha256={})
        self.rehash()
        self.write(self.root/'current.json', {'release':'release-test'})
        self.write(self.root/'exclusions.json', {'eligibility_policy':3, 'game_ids':[]})
        self.write(self.cache/'current.json', {'build':'build-test'})
        self.catalogue = dict(self.contract, datasets={'2':{'games':1,'sha256':'a'*64,'available':{'terrans':['point-sources']}}})
        self.write(self.build/'manifest.json', self.catalogue)
        self.write(self.build/'eligible-games.json', {'complete':True,'game_ids':['base']})
        (self.build/'plotly.min.js').write_text('x'*100001)
        (self.build/'plots/2-terrans-point-sources.html').write_text('<html>ready</html>')
        with (self.build/'data/2.csv').open('w') as handle:
            writer = csv.writer(handle)
            writer.writerow(['id','num_players','balance_variant','pos_1_score','pos_1_bid','pos_2_score','pos_2_bid','pos_1_dropped','pos_2_dropped'])
            writer.writerow(['base',2,'standard',75,50,150,0,False,False])

    def write(self, path, data):
        Path(path).write_text(json.dumps(data))

    def database(self, path, rows):
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE metadata(key TEXT,value TEXT)')
            db.executemany('INSERT INTO metadata VALUES (?,?)', [('eligibility_policy','3'), ('score_basis_version','prebid-v1'), ('imports',json.dumps({'2':{'sha256':'a'*64}}))])
            db.execute('CREATE TABLE observations(game_id TEXT,faction TEXT,payload TEXT)')
            db.executemany('INSERT INTO observations VALUES (?,?,?)', [(r['game_id'],r['faction'],json.dumps(r)) for r in rows])

    def rehash(self):
        self.manifest['sha256'] = {name:guard.digest(self.release/name) for name in ('base.sqlite','lost-fleet.json')}
        self.write(self.release/'manifest.json', self.manifest)

    def check(self):
        return guard.check(self.contract_path, self.root, self.seed, self.cache)

    def edit_row(self, change, target='base.sqlite'):
        if target == 'base.sqlite':
            with sqlite3.connect(self.release/target) as db:
                row = json.loads(db.execute('SELECT payload FROM observations WHERE faction="terrans"').fetchone()[0])
                change(row)
                db.execute('UPDATE observations SET payload=? WHERE faction="terrans"', (json.dumps(row),))
        else:
            data = guard.read_json(self.release/target); change(data['rows'][0]); self.write(self.release/target,data)
        self.rehash()

    def index_lost_fleet(self, rows=None):
        if rows is None:
            rows = guard.read_json(self.release/'lost-fleet.json')['rows']
        directory = self.root/'objects/lost-fleet'
        directory.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
        sha = guard.hashlib.sha256(raw).hexdigest()
        target = directory/(sha+'.json'); target.write_bytes(raw)
        self.write(self.release/'lost-fleet.json',
                   {'schema_version':1, 'storage':'content-addressed-games-v1', 'games':{'lf':sha}})
        self.rehash()
        return target

    def test_indexed_lost_fleet_passes_read_only_and_standalone_cli(self):
        self.index_lost_fleet()
        before = {p:p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()}
        self.assertEqual(self.check()['datasets'], self.manifest['datasets'])
        result = subprocess.run([sys.executable, '-I', str(ROOT/'deploy/check-data-contract.py'),
                                 '--contract', str(self.contract_path), '--bundle', str(self.bundle)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({p:p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()}, before)

    def test_indexed_lost_fleet_corrupt_and_missing_objects_fail(self):
        target = self.index_lost_fleet(); original = target.read_bytes()
        target.write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError, 'object hash mismatch'):self.check()
        target.write_bytes(original)
        target.rename(target.with_suffix('.retained'))
        with self.assertRaises(FileNotFoundError):self.check()

    def test_indexed_lost_fleet_rejects_traversal_and_symlink_escape(self):
        target = self.index_lost_fleet()
        index = guard.read_json(self.release/'lost-fleet.json')
        index['games']['lf'] = '../../outside'
        self.write(self.release/'lost-fleet.json', index); self.rehash()
        with self.assertRaisesRegex(ValueError, 'Invalid LF object hash'):self.check()
        index['games']['lf'] = target.stem
        self.write(self.release/'lost-fleet.json', index); self.rehash()
        outside = self.bundle/'outside.json'; target.rename(outside); target.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'escapes'):self.check()

    def test_indexed_lost_fleet_rejects_object_directory_escape(self):
        target = self.index_lost_fleet()
        outside = self.bundle/'outside-objects'; target.parent.rename(outside)
        target.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'directory escapes'):self.check()

    def test_indexed_lost_fleet_checks_identity_and_existing_row_contract(self):
        rows = guard.read_json(self.release/'lost-fleet.json')['rows']
        wrong = copy.deepcopy(rows); wrong[0]['game_id'] = 'other'
        self.index_lost_fleet(wrong)
        with self.assertRaisesRegex(ValueError, 'object identity mismatch'):self.check()
        wrong = copy.deepcopy(rows); wrong[0]['rank'] = 1
        self.index_lost_fleet(wrong)
        with self.assertRaisesRegex(ValueError, 'rank'):self.check()
        self.index_lost_fleet([None])
        with self.assertRaisesRegex(ValueError, 'object identity mismatch'):self.check()

    def test_indexed_lost_fleet_rejects_unsupported_or_ambiguous_storage(self):
        self.index_lost_fleet()
        path = self.release/'lost-fleet.json'; index = guard.read_json(path)
        index['storage'] = 'unknown'; self.write(path, index); self.rehash()
        with self.assertRaisesRegex(ValueError, 'Unsupported Lost Fleet storage'):self.check()
        index['storage'] = 'content-addressed-games-v1'; index['rows'] = []
        self.write(path, index); self.rehash()
        with self.assertRaisesRegex(ValueError, 'Invalid LF object index'):self.check()

    def test_contract_schema_requires_exact_supported_integer(self):
        for invalid in (True, False, 1.0, 2.0, '1', None, 3):
            with self.subTest(schema_version=invalid):
                value=dict(self.contract,schema_version=invalid)
                self.write(self.contract_path,value)
                with self.assertRaisesRegex(ValueError,'Unsupported deployment contract'):
                    guard.contract_value(self.contract_path)

    def test_storage_contract_requires_static_seed_and_indexed_lf(self):
        self.contract.update(schema_version=2,base_source_policy='original-csv-only-v1',lf_storage='content-addressed-games-v1')
        self.write(self.contract_path,self.contract)
        with self.assertRaisesRegex(ValueError,'Base source policy'):self.check()
        self.manifest['base_source_policy']='original-csv-only-v1';self.rehash()
        with self.assertRaisesRegex(ValueError,'LF storage'):self.check()
        self.index_lost_fleet()
        with sqlite3.connect(self.release/'base.sqlite') as db:
            db.execute("INSERT INTO metadata VALUES ('base_source_policy','original-csv-only-v1')")
        self.rehash();self.check()
        self.edit_row(lambda row:row.update(raw_overlay=True))
        with self.assertRaisesRegex(ValueError,'exactly match'):self.check()

    def test_ready_contract_is_read_only_and_accepts_older_source_normalization(self):
        before = {p:p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()}
        result = self.check()
        self.assertEqual(result['datasets'], self.manifest['datasets'])
        self.assertEqual({p:p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()}, before)
        # Printed75 is not wrongly rejected when the actual pre-bid score is125.
        self.assertEqual(result['seed']['records'], 2)

    def test_unknown_score_arithmetic_rank_and_ties_fail_closed(self):
        cases = [('unknown',lambda r:r.update(score=None)),
                 ('reconcile',lambda r:r.update(score=126)),
                 ('rank',lambda r:r.update(rank=1)),
                 ('win credit',lambda r:r.update(win_share=.5)),
                 ('auction contribution',lambda r:r['vp_sources'].update(bid=-50)),
                 ('floor',lambda r:r.update(score=99,reported_score=49))]
        for message, change in cases:
            original=(self.release/'base.sqlite').read_bytes()
            with self.subTest(message=message):
                self.edit_row(change)
                with self.assertRaisesRegex(ValueError,message):self.check()
            (self.release/'base.sqlite').write_bytes(original);self.rehash()
        self.edit_row(lambda r:r.update(score_basis_version='old'), 'lost-fleet.json')
        with self.assertRaisesRegex(ValueError,'unmigrated'):self.check()

    def test_all_games_and_shared_wins_are_checked(self):
        self.edit_row(lambda r:r.update(rank=1,score=150,reported_score=100,win_share=.5))
        with sqlite3.connect(self.release/'base.sqlite') as db:
            row=json.loads(db.execute('SELECT payload FROM observations WHERE faction="xenos"').fetchone()[0]);row['win_share']=.5
            db.execute('UPDATE observations SET payload=? WHERE faction="xenos"',(json.dumps(row),))
        self.rehash();self.check()
        with sqlite3.connect(self.release/'base.sqlite') as db:db.execute('DELETE FROM observations WHERE faction="xenos"')
        self.rehash()
        with self.assertRaisesRegex(ValueError,'incomplete game'):self.check()

    def test_marker_hash_count_registry_and_cache_rejections(self):
        self.manifest['eligibility_policy']=2;self.rehash()
        with self.assertRaisesRegex(ValueError,'policy'):self.check()
        self.manifest['eligibility_policy']=3;self.manifest['inputs']['normalization_version']=2;self.rehash()
        with self.assertRaisesRegex(ValueError,'normalization'):self.check()
        self.manifest['inputs']['normalization_version']=3;self.rehash()
        with (self.release/'lost-fleet.json').open('a') as handle:handle.write(' ')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.check()
        self.rehash();self.manifest['datasets']['base']['records']=999;self.rehash()
        with self.assertRaisesRegex(ValueError,'counts'):self.check()
        self.manifest['datasets']['base']['records']=2;self.rehash()
        self.write(self.root/'exclusions.json', {'eligibility_policy':3,'game_ids':['late']})
        with self.assertRaisesRegex(ValueError,'exclusion evidence'):self.check()
        self.manifest['excluded_game_ids']=['late'];self.rehash()
        self.write(self.build/'eligible-games.json', {'complete':True,'game_ids':['base','late']})
        with self.assertRaisesRegex(ValueError,'newly excluded'):self.check()
        self.write(self.build/'eligible-games.json', {'complete':True,'game_ids':['base']})
        self.catalogue.pop('score_basis_version');self.write(self.build/'manifest.json',self.catalogue)
        with self.assertRaisesRegex(ValueError,'score basis'):self.check()

    def test_seed_marker_is_required_before_code_can_activate(self):
        with sqlite3.connect(self.seed) as db:db.execute("DELETE FROM metadata WHERE key='score_basis_version'")
        self.manifest['inputs']['seed']=guard.digest(self.seed);self.rehash()
        with self.assertRaisesRegex(ValueError,'Seed: score basis'):self.check()

    def test_seed_hash_and_classic_source_coverage_must_match(self):
        self.manifest['inputs']['seed']='not-the-seed';self.rehash()
        with self.assertRaisesRegex(ValueError,'seed hash'):self.check()
        self.manifest['inputs']['seed']=guard.digest(self.seed);self.rehash()
        self.catalogue['datasets']['2']['sha256']='b'*64;self.write(self.build/'manifest.json',self.catalogue)
        with self.assertRaisesRegex(ValueError,'source hash'):self.check()
        self.catalogue['datasets']['2']['sha256']='a'*64;self.write(self.build/'manifest.json',self.catalogue)
        with sqlite3.connect(self.seed) as db:
            db.execute("UPDATE metadata SET value=? WHERE key='imports'", (json.dumps({'2':{'sha256':'a'*64},'3':{'sha256':'c'*64}}),))
        self.manifest['inputs']['seed']=guard.digest(self.seed);self.rehash()
        with self.assertRaisesRegex(ValueError,'source player counts'):self.check()

    def test_classic_csv_and_plot_integrity(self):
        chart=self.build/'plots/2-terrans-point-sources.html';chart.unlink()
        with self.assertRaisesRegex(ValueError,'Missing classic chart'):self.check()
        chart.write_text('<html>ready</html>')
        csv_path=self.build/'data/2.csv';csv_path.write_text(csv_path.read_text().replace('75,50','75,0'))
        with self.assertRaisesRegex(ValueError,'ineligible'):self.check()

    def test_classic_download_rejects_dropped_and_unknown_status(self):
        path = self.build/'data/2.csv'
        original = path.read_text()
        for status in ('True', '', 'unknown'):
            with self.subTest(status=status):
                path.write_text(original.replace('False,False', 'False,'+status))
                with self.assertRaisesRegex(ValueError, 'dropped or unknown-status'):
                    self.check()
        path.write_text(original)
        self.check()

    def test_classic_download_requires_exact_seed_game_ids_not_only_counts(self):
        path = self.build/'data/2.csv'
        original = path.read_text()
        path.write_text(original.replace('base,2,', 'extra,2,'))
        self.write(self.build/'eligible-games.json', {'complete':True, 'game_ids':['extra']})
        with self.assertRaisesRegex(ValueError, 'exactly match'):
            self.check()
        path.write_text(original.splitlines()[0]+'\n')
        self.write(self.build/'eligible-games.json', {'complete':True, 'game_ids':[]})
        self.catalogue['datasets']['2']['games'] = 0
        self.write(self.build/'manifest.json', self.catalogue)
        with self.assertRaisesRegex(ValueError, 'exactly match'):
            self.check()

    def test_classic_download_rejects_additional_self_consistent_game(self):
        path = self.build/'data/2.csv'
        path.write_text(path.read_text()+path.read_text().splitlines()[1].replace('base,2,','extra,2,')+'\n')
        self.catalogue['datasets']['2']['games'] = 2
        self.write(self.build/'manifest.json', self.catalogue)
        self.write(self.build/'eligible-games.json', {'complete':True, 'game_ids':['base','extra']})
        with self.assertRaisesRegex(ValueError, 'exactly match'):
            self.check()

    def test_classic_download_rejects_duplicate_games_even_with_matching_counts(self):
        path = self.build/'data/2.csv'
        path.write_text(path.read_text()+path.read_text().splitlines()[1]+'\n')
        self.catalogue['datasets']['2']['games'] = 2
        self.write(self.build/'manifest.json', self.catalogue)
        with self.assertRaisesRegex(ValueError, 'repeats a game'):
            self.check()

    def test_cli_bundle_resolution_and_unsafe_pointer(self):
        active=self.bundle/'active';active.symlink_to(self.bundle,target_is_directory=True)
        result=subprocess.run([sys.executable,str(ROOT/'deploy/check-data-contract.py'),
                               '--contract',str(self.contract_path),'--bundle',str(active)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['release'],'release-test')
        self.write(self.root/'current.json',{'release':'../outside'})
        with self.assertRaisesRegex(ValueError,'Unsafe'):self.check()

    def test_bundle_preparation_and_member_containment_fail_before_activation(self):
        for state in ('preparing', 'failed'):
            with self.subTest(state=state):
                self.write(self.bundle/'preparation.json', {'state':state})
                result=subprocess.run([sys.executable,str(ROOT/'deploy/check-data-contract.py'),
                                       '--contract',str(self.contract_path),'--bundle',str(self.bundle)],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('has not passed migration preflight',result.stderr)
        self.write(self.bundle/'preparation.json', {'state':'ready'})
        with tempfile.TemporaryDirectory() as outside:
            self.seed.unlink();self.seed.symlink_to(Path(outside)/'base.sqlite')
            with self.assertRaisesRegex(ValueError,'escapes'):guard.bundle_paths(self.bundle)
