import json
from pathlib import Path
import tempfile
import unittest

from gaia_stats.release_data import load_dataset, write_dataset, object_path


class ReleaseDataTests(unittest.TestCase):
    def test_objects_reuse_verify_and_read_old_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root/'releases/release-first/lost-fleet.json'
            first.parent.mkdir(parents=True)
            rows = [{'game_id':'g', 'faction':'terrans'}, {'game_id':'g', 'faction':'xenos'}]
            index = write_dataset(first, {'g':rows}, scope='test')
            target = object_path(first, index['games']['g'])
            self.assertEqual(load_dataset(first)['rows'], rows)
            second = root/'releases/release-second/lost-fleet.json'
            second.parent.mkdir()
            write_dataset(second, {'g':rows})
            self.assertEqual(len(list(target.parent.iterdir())), 1)
            first.write_text(json.dumps({'schema_version':1, 'rows':rows}))
            self.assertEqual(load_dataset(first)['rows'], rows)
            target.write_text('corrupt')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                load_dataset(second)

    def test_index_path_and_object_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'releases/release-first/lost-fleet.json';path.parent.mkdir(parents=True)
            write_dataset(path, {'wrong':[{'game_id':'other', 'faction':'x'}]})
            with self.assertRaisesRegex(ValueError,'identity mismatch'):load_dataset(path)
            data=json.loads(path.read_text());data['games']['wrong']='../escape';path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'object hash'):load_dataset(path)
