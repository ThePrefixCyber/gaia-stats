"""Production WSGI entry point; read-only HTTP, disk-backed dataset with hot reload."""
import json
import os
import subprocess
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs

from .__main__ import ingest, response_for
from .legacy_cache import is_classic_path


class Application:
    def __init__(self, dataset_path, classic_cache=None):
        self.path = Path(dataset_path)
        self.classic_cache = classic_cache
        self.lock = Lock()
        self.dataset = None
        self.version = None
        try:
            self.commit = subprocess.check_output(
                ["git", "-c", "safe.directory=" + str(Path(__file__).resolve().parent.parent), "rev-parse", "HEAD"],
                cwd=Path(__file__).parent.parent, text=True, timeout=3,
                stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.SubprocessError):
            self.commit = None
        if not self.path.exists():
            fixtures = Path(__file__).parent.parent / "tests/fixtures"
            ingest(sorted(fixtures.glob("*.json")), self.path)

    def load(self):
        with self.lock:
            info = self.path.stat()
            version = (info.st_mtime_ns, info.st_size)
            if version != self.version:
                candidate = json.loads(self.path.read_text())
                if candidate.get("schema_version") != 1 or not isinstance(candidate.get("rows"), list):
                    raise ValueError("Unsupported dataset")
                self.dataset, self.version = candidate, version
            return self.dataset

    def __call__(self, environ, start_response):
        status, headers = "200 OK", [("Cache-Control", "no-store")]
        path = environ.get("PATH_INFO", "/")
        filters = {key: values[-1] for key, values in parse_qs(environ.get("QUERY_STRING", "")).items()}
        try:
            if environ.get("REQUEST_METHOD") != "GET":
                status, body, content_type = "405 Method Not Allowed", b"GET only", "text/plain"
                headers.append(("Allow", "GET"))
            elif self.classic_cache is not None and is_classic_path(path):
                from .legacy_cache import cache_response
                body, content_type, download = cache_response(self.classic_cache, path, filters)
                if download:
                    headers.append(("Content-Disposition", f'attachment; filename="{download}"'))
            elif path == "/healthz":
                dataset = self.load()
                deployment = None
                try:
                    deployment = json.loads((self.path.parent / "deploy-status.json").read_text())
                except (OSError, ValueError):
                    pass
                body = json.dumps({"status": "ok", "commit": self.commit,
                                   "games": len({row["game_id"] for row in dataset["rows"]}),
                                   "player_records": len(dataset["rows"]),
                                   "deployment": deployment}).encode()
                content_type = "application/json"
            else:
                body, content_type = response_for(self.load(), path, filters)
                if path == "/api/export":
                    headers.append(("Content-Disposition", f'attachment; filename="gaia-{filters["ruleset"]}.csv"'))
        except FileNotFoundError:
            status, body, content_type = "404 Not Found", b"Not found", "text/plain"
        except (ValueError, KeyError) as exc:
            status, body, content_type = "400 Bad Request", json.dumps({"error": str(exc)}).encode(), "application/json"
        headers.extend([("Content-Type", content_type), ("Content-Length", str(len(body))),
                        ("X-Content-Type-Options", "nosniff")])
        start_response(status, headers)
        return [body]


def create_app():
    return Application(os.environ.get("GAIA_DATASET", "data/analysis.json"),
                       classic_cache=os.environ.get("GAIA_CLASSIC_CACHE"))
