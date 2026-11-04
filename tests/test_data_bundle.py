import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gaia_stats.data_bundle import paths
from gaia_stats.wsgi import create_app


class DataBundleTests(unittest.TestCase):
    def test_worker_resolves_active_pointer_once_and_requires_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);first=root/'first';second=root/'second'
            for bundle in (first,second):
                bundle.mkdir();(bundle/'preparation.json').write_text(json.dumps({'state':'ready'}))
                (bundle/'releases-store').mkdir();(bundle/'classic-cache').mkdir();(bundle/'seeds').mkdir()
            active=root/'active';active.symlink_to(first,target_is_directory=True)
            with patch.dict(os.environ,{'GAIA_DATA_BUNDLE':str(active)}):
                app=create_app()
                active.unlink();active.symlink_to(second,target_is_directory=True)
                self.assertEqual(app.root,first/'releases-store')
                self.assertEqual(create_app().root,second/'releases-store')
                (second/'preparation.json').write_text('{"state":"failed"}')
                with self.assertRaisesRegex(ValueError,'preflight'):create_app()

    def test_member_symlinks_cannot_escape_the_selected_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);bundle=root/'bundle';bundle.mkdir();outside=root/'outside';outside.mkdir()
            (bundle/'releases-store').symlink_to(outside,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'escapes'):paths(bundle)
