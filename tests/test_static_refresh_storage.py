import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from gaia_stats.analysis import normalize
from gaia_stats.archive import collect
from gaia_stats.release_data import load_dataset
from gaia_stats.releases import current, digest, insert_game, validate
from test_archive import FakeClient, game
import test_releases as shared


class StaticStorageTests(unittest.TestCase):
    setUp = shared.ReleaseTests.setUp
    publish = shared.ReleaseTests.publish
    add_legacy_game = shared.ReleaseTests.add_legacy_game

    def accepted(self, slug, mode='lost-fleet'):
        client=FakeClient({slug:game(slug,lf=mode=='lost-fleet')})
        collect(self.archive,mode,client=client,max_pages=1,max_downloads=1,head_only=True)
        return client

    def test_base_archive_never_changes_static_rows_or_release(self):
        self.accepted('Ignored-base','base')
        first=self.publish();prior=current(self.store)
        with sqlite3.connect(self.seed) as db:seed=db.execute('SELECT payload FROM observations ORDER BY game_id,faction').fetchall()
        with sqlite3.connect(prior/'base.sqlite') as db:self.assertEqual(db.execute('SELECT payload FROM observations ORDER BY game_id,faction').fetchall(),seed)
        before={p:p.read_bytes() for p in self.archive.rglob('*') if p.is_file() and p.suffix=='.json'}
        self.accepted('Another-base','base')
        with patch('gaia_stats.releases.normalize',side_effect=AssertionError('should not normalize')):
            self.assertEqual(self.publish()['release'],first['release'])
        self.assertEqual(current(self.store),prior)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
        self.assertEqual(len(list((self.store/'releases').iterdir())),1)

    def test_one_lf_game_stores_one_new_object_and_shared_base(self):
        self.accepted('First-game');first=self.publish();prior=current(self.store)
        base_sha=digest(prior/'base.sqlite')
        old_objects={p.name:p.read_bytes() for p in (self.store/'objects/lost-fleet').iterdir()}
        self.accepted('Next-game')
        with patch('gaia_stats.releases.normalize',wraps=normalize) as normalizer:
            second=self.publish()
        normalizer.assert_called_once()
        self.assertEqual(normalizer.call_args.args[0]['slug'],'Next-game')
        active=current(self.store)
        self.assertEqual((prior/'base.sqlite').stat().st_ino,(active/'base.sqlite').stat().st_ino)
        self.assertNotEqual(self.seed.stat().st_ino,(active/'base.sqlite').stat().st_ino)
        self.assertEqual(digest(prior/'base.sqlite'),base_sha)
        self.assertEqual(len(list((self.store/'objects/lost-fleet').iterdir())),len(old_objects)+1)
        self.assertTrue(all((self.store/'objects/lost-fleet'/name).read_bytes()==raw for name,raw in old_objects.items()))
        self.assertEqual(second['datasets']['lost-fleet']['games'],first['datasets']['lost-fleet']['games']+1)
        with patch('gaia_stats.releases.normalize',side_effect=AssertionError('no-op normalized')):
            self.assertEqual(self.publish()['release'],second['release'])
        self.assertEqual(len(list((self.store/'releases').iterdir())),2)

    def test_seed_replacement_does_not_modify_linked_releases(self):
        self.publish();prior=current(self.store);before=(prior/'base.sqlite').read_bytes()
        with sqlite3.connect(self.seed) as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('review_note','changed seed')")
        self.publish();active=current(self.store)
        self.assertNotEqual((active/'base.sqlite').stat().st_ino,(prior/'base.sqlite').stat().st_ino)
        self.assertEqual((prior/'base.sqlite').read_bytes(),before)

    def test_legacy_whitespace_and_irrelevant_base_change_are_noops(self):
        first=self.publish()
        self.legacy.write_text(self.legacy.read_text()+' ')
        self.assertEqual(self.publish()['release'],first['release'])
        data=json.loads(self.legacy.read_text())
        with sqlite3.connect(self.seed) as db:row=json.loads(db.execute('SELECT payload FROM observations LIMIT 1').fetchone()[0])
        data['rows'].append(row);self.legacy.write_text(json.dumps(data))
        self.assertEqual(self.publish()['release'],first['release'])
        # Accepted LF arriving for a record already in the legacy data changes
        # provenance but identical processed observations need no extra objects.
        self.assertEqual(len(list((self.store/'releases').iterdir())),1)

    def test_static_migration_requires_explicit_optin_and_keeps_old_bytes(self):
        self.publish();old=current(self.store)
        with sqlite3.connect(old/'base.sqlite') as db:
            rows=[dict(json.loads(p),game_id='raw-only') for p, in db.execute('SELECT payload FROM observations')]
            insert_game(db,'raw-only',rows)
        manifest=json.loads((old/'manifest.json').read_text())
        manifest.pop('base_source_policy');manifest['inputs'].pop('base_source_policy')
        manifest['datasets']['base']={'games':2,'records':4};manifest['sha256']['base.sqlite']=digest(old/'base.sqlite')
        (old/'manifest.json').write_text(json.dumps(manifest))
        old_bytes={p.name:p.read_bytes() for p in old.iterdir()}
        with self.assertRaisesRegex(ValueError,'explicit static CSV migration'):self.publish()
        new=self.publish(allow_static_base_migration=True)
        self.assertEqual(new['datasets']['base'],{'games':1,'records':2})
        self.assertEqual(new['base_migration']['archived_only_records'],2)
        self.assertEqual(new['datasets']['lost-fleet'],manifest['datasets']['lost-fleet'])
        self.assertTrue(all((old/name).read_bytes()==raw for name,raw in old_bytes.items()))
        validate(old)

    def test_corrupt_lf_object_or_new_raw_does_not_change_pointer(self):
        self.publish();prior=current(self.store);pointer=(self.store/'current.json').read_bytes()
        self.accepted('New-game')
        raw=self.archive/'lost-fleet/raw/New-game.json';raw.write_text('{}')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.publish()
        self.assertEqual((self.store/'current.json').read_bytes(),pointer)
        validate(prior)
        obj=next((self.store/'objects/lost-fleet').iterdir());obj.write_text('corrupt')
        with self.assertRaisesRegex(ValueError,'object hash'):self.publish()

    def test_link_failure_preserves_pointer_without_copy_fallback(self):
        self.publish();pointer=(self.store/'current.json').read_bytes();self.add_legacy_game()
        with patch('gaia_stats.releases.os.link',side_effect=OSError('cross-device')):
            with self.assertRaisesRegex(OSError,'cross-device'):self.publish()
        self.assertEqual((self.store/'current.json').read_bytes(),pointer)
        validate(current(self.store))
