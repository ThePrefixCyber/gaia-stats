import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gaia_stats.__main__ import atomic_json, ingest
from gaia_stats.fetch import fetch_games
from gaia_stats.wsgi import Application


class DeploymentTests(unittest.TestCase):
    def request(self, app, path="/", query="", method="GET"):
        captured = {}
        def start(status, headers):
            captured.update(status=status, headers=dict(headers))
        body = b"".join(app({"PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": method}, start))
        return captured, body

    def test_production_app_bootstraps_once_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "analysis.json"
            app = Application(path)
            response, body = self.request(app, "/api/analysis", "ruleset=lost-fleet&skill=top")
            self.assertEqual(response["status"], "200 OK")
            self.assertEqual(json.loads(body)["games"], 2)  # one top record per player count
            dataset = json.loads(path.read_text())
            dataset["rows"] = [r for r in dataset["rows"] if r["ruleset"] == "base"]
            atomic_json(path, dataset)
            for instance in (app, Application(path)):
                response, body = self.request(instance, "/api/analysis", "ruleset=lost-fleet")
                self.assertEqual(json.loads(body)["games"], 0)
                self.assertEqual(response["status"], "200 OK")

    def test_health_export_errors_and_read_only_routes(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Application(Path(folder) / "analysis.json")
            for path, query, method, status in [
                ("/healthz", "", "GET", "200 OK"),
                ("/api/export", "ruleset=base&skill=all", "GET", "200 OK"),
                ("/api/export", "", "GET", "400 Bad Request"),
                ("/not-found", "", "GET", "404 Not Found"),
                ("/", "", "POST", "405 Method Not Allowed"),
            ]:
                response, body = self.request(app, path, query, method)
                self.assertEqual(response["status"], status)
                if path == "/api/export" and query:
                    self.assertIn("gaia-base.csv", response["headers"]["Content-Disposition"])

    def test_empty_bad_import_does_not_replace_existing_dataset(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "analysis.json"
            app = Application(path)
            before = path.read_bytes()
            invalid = Path(folder) / "invalid.json"
            invalid.write_text('{"slug":"bad","status":"running"}')
            with self.assertRaises(ValueError):
                ingest([invalid], path)
            self.assertEqual(path.read_bytes(), before)

    def test_fetch_validates_and_saves_without_network_in_test(self):
        game = json.loads((Path(__file__).parent / "fixtures/Jubilant-rover-3041.json").read_text())
        from io import BytesIO
        with tempfile.TemporaryDirectory() as folder:
            with patch("gaia_stats.fetch.urlopen", return_value=BytesIO(json.dumps(game).encode())):
                self.assertEqual(fetch_games([game["slug"]], folder), 0)
            self.assertTrue((Path(folder) / (game["slug"] + ".json")).exists())
            with patch("gaia_stats.fetch.urlopen") as network:
                self.assertEqual(fetch_games(["../../secret"], folder), 1)
                network.assert_not_called()
