"""The cohort UI serves only its known local presentation assets."""
import unittest
from gaia_stats.cohort import response


class TableAssetsTests(unittest.TestCase):
    def test_scripts_and_styles_are_served(self):
        for path, content_type in (
            ('/cohort/tables.js', 'application/javascript'),
            ('/cohort/styles.css', 'text/css; charset=utf-8'),
            ('/cohort/app.js', 'application/javascript'),
        ):
            with self.subTest(path=path):
                content, mime = response({}, path, {})
                self.assertEqual(mime, content_type)
                self.assertTrue(content)

    def test_page_loads_table_helper_before_app(self):
        content, _ = response({}, '/cohort/', {})
        page = content.decode()
        self.assertIn('href="/cohort/styles.css"', page)
        self.assertLess(page.index('src="/cohort/tile-labels.js"'), page.index('src="/cohort/app.js"'))
        self.assertLess(page.index('src="/cohort/tables.js"'), page.index('src="/cohort/app.js"'))

    def test_unknown_asset_is_not_served(self):
        for path in ('/cohort/../README.md', '/cohort/missing.js'):
            with self.subTest(path=path), self.assertRaises(FileNotFoundError):
                response({}, path, {})
