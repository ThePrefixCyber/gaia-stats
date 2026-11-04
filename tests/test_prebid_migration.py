import csv
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from gaia_stats.migrate_prebid import prepare
from gaia_stats.releases import current,digest
from gaia_stats.archive import archive_lock
from gaia_stats.legacy_cache import build_cache as real_build_cache
import test_releases as shared
from test_corrected_plots import game as wide_game


class PrebidMigrationTests(unittest.TestCase):
    setUp=shared.ReleaseTests.setUp
    publish=shared.ReleaseTests.publish

    def source(self):
        self.publish();self.archive.mkdir(exist_ok=True)
        source=self.root/'original.csv';game=wide_game();game.update(balance_variant='standard',map_layout='standard')
        with source.open('w') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(game));writer.writeheader();writer.writerow(game)
        return source

    def test_separate_bundle_preserves_live_pointer_bytes_and_source_files(self):
        source=self.source();old=current(self.store)
        before={path:path.read_bytes() for path in (self.store/'current.json',self.seed,source,old/'base.sqlite',old/'lost-fleet.json')}
        destination=self.root/'prepared'
        result=prepare(destination,self.store,{2:source},self.archive,self.legacy)
        self.assertEqual(result['state'],'ready')
        self.assertEqual(result['score_basis_version'],'prebid-v1')
        self.assertTrue((destination/'seeds/base.sqlite').is_file())
        self.assertNotEqual(current(destination/'releases-store'),old)
        for path,contents in before.items():self.assertEqual(path.read_bytes(),contents)
        self.assertEqual(current(self.store),old)
        with self.assertRaisesRegex(ValueError,'already exists'):
            prepare(destination,self.store,{2:source},self.archive,self.legacy)

    def test_low_disk_fails_before_creating_destination(self):
        source=self.source();destination=self.root/'no-room'
        with patch('gaia_stats.migrate_prebid.shutil.disk_usage',return_value=shutil._ntuple_diskusage(100,99,1)):
            with self.assertRaisesRegex(ValueError,'disk space'):
                prepare(destination,self.store,{2:source},self.archive,self.legacy)
        self.assertFalse(destination.exists())

    def test_failure_retains_diagnostics_without_activating_or_touching_source(self):
        source=self.source();pointer=(self.store/'current.json').read_bytes();destination=self.root/'failed'
        with patch('gaia_stats.migrate_prebid.build_cache',side_effect=ValueError('simulated cache failure')):
            with self.assertRaisesRegex(ValueError,'cache failure'):
                prepare(destination,self.store,{2:source},self.archive,self.legacy)
        self.assertEqual(json.loads((destination/'preparation.json').read_text())['state'],'failed')
        self.assertEqual((self.store/'current.json').read_bytes(),pointer)

    def test_unrecoverable_retained_history_blocks_activation_without_record_loss(self):
        source=self.source();original=current(self.store)
        with sqlite3.connect(original/'base.sqlite') as db:
            old=[json.loads(x[0]) for x in db.execute('SELECT payload FROM observations')]
            for row in old:
                row['game_id']='missing-original-source'
                for key in ('score_basis_version','bid_cost','bid_delta','reported_score','reported_rank','reported_win_share','vp_sources_audit'):
                    row.pop(key,None)
                db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)',
                           tuple(row[k] for k in ('game_id','faction','player_count','elo','layout','auction','faction_variant'))+(json.dumps(row),))
        manifest=json.loads((original/'manifest.json').read_text())
        manifest['datasets']['base']={'games':2,'records':4}
        manifest['sha256']['base.sqlite']=digest(original/'base.sqlite')
        (original/'manifest.json').write_text(json.dumps(manifest))
        before=(original/'base.sqlite').read_bytes();destination=self.root/'unrecoverable'
        with self.assertRaisesRegex(ValueError,'unknown/non-finite|unmigrated observation'):
            prepare(destination,self.store,{2:source},self.archive,self.legacy)
        self.assertEqual((original/'base.sqlite').read_bytes(),before)
        with sqlite3.connect(current(destination/'releases-store')/'base.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],4)
        self.assertEqual(json.loads((destination/'preparation.json').read_text())['state'],'failed')

    def test_changed_csv_or_active_collector_never_marks_candidate_ready(self):
        source=self.source();destination=self.root/'raced'
        with archive_lock(self.archive):
            with self.assertRaisesRegex(RuntimeError,'collector'):
                prepare(destination,self.store,{2:source},self.archive,self.legacy)
        self.assertFalse(destination.exists())
        pointer=(self.store/'current.json').read_bytes()
        def changed(*args,**kwargs):
            result=real_build_cache(*args,**kwargs)
            source.write_text(source.read_text()+'\n')
            return result
        with patch('gaia_stats.migrate_prebid.build_cache',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'CSV changed'):
                prepare(destination,self.store,{2:source},self.archive,self.legacy)
        self.assertEqual(json.loads((destination/'preparation.json').read_text())['state'],'failed')
        self.assertEqual((self.store/'current.json').read_bytes(),pointer)
