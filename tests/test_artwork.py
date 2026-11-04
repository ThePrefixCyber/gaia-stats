"""Original artwork is local, attributed and independent of statistical data."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gaia_stats.artwork import ASSETS, response
from gaia_stats.wsgi import Application


ROOT = Path(__file__).resolve().parents[1]


class ArtworkTests(unittest.TestCase):
    def test_cover_preserves_original_bytes_and_every_asset_is_local(self):
        body, mime = response('/art/gaia-project-cover.jpeg')
        self.assertEqual(mime, 'image/jpeg')
        self.assertEqual(hashlib.sha256(body).hexdigest(),
                         '0a3c4fa255efb3324b49d4a314e5a66bd4ff6ae9df4dbd37429a2372cfd67496')
        for path, (_, expected_mime) in ASSETS.items():
            data, content_type = response(path)
            self.assertTrue(data)
            self.assertEqual(content_type, expected_mime)

    def test_art_is_served_without_dataset_or_computation_locks(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data.json'
            data.write_text('{"schema_version":1,"rows":[]}')
            app = Application(data, code_commit='test')
            with patch.object(app, 'load', side_effect=AssertionError('Read data')):
                for path in ASSETS:
                    status = []
                    body = b''.join(app({'REQUEST_METHOD': 'GET', 'PATH_INFO': path},
                                       lambda s, h: status.append((s, dict(h)))))
                    self.assertEqual(status[0][0], '200 OK')
                    self.assertEqual(status[0][1]['X-Content-Type-Options'], 'nosniff')
                    self.assertEqual(body, response(path)[0])

    def test_unknown_and_traversal_paths_are_rejected(self):
        for path in ('/art/../README.md', '/art/vendor/../../README.md',
                     '/art/%2e%2e/README.md', '/art/missing.js'):
            with self.subTest(path=path), self.assertRaises(FileNotFoundError):
                response(path)

    def test_both_pages_use_original_art_and_keep_attribution(self):
        for filename in ('web/cohort/index.html', 'web/classic/index.html'):
            text = (ROOT / filename).read_text()
            self.assertIn('class="gaia-cover"', text)
            self.assertIn('src="/art/gaia-project-cover.jpeg"', text)
            self.assertIn('href="/art/site-art.css"', text)
            self.assertIn('src="/art/site-art.js" defer', text)
            self.assertIn('Timothy Gladyshev', text)
            self.assertIn('Dennis Lohausen', text)
            self.assertIn('Feuerland Spiele', text)
            self.assertNotIn('Original artwork is not included', text)
            self.assertNotIn('This preview recreates', text)
            self.assertNotIn('Separate unfiltered historical downloads:', text)
            self.assertNotIn('These files do not use the selected filters.', text)
            self.assertEqual(text.count('id="gaia-background"'), 1)
            self.assertEqual(text.count('id="art-motion"'), 1)

    def test_software_licenses_are_separate_from_image_credit(self):
        for filename in ('three-LICENSE.txt', 'vanta-LICENSE.txt'):
            self.assertIn('Permission is hereby granted',
                          (ROOT / 'web/art/vendor' / filename).read_text())
        self.assertIn('not a separate license grant', (ROOT / 'docs/ARTWORK_CREDITS.md').read_text())
