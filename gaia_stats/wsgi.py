"""Production WSGI entry point; read-only HTTP, disk-backed dataset with hot reload."""
import json
import os
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs

from .__main__ import ingest, response_for


class Application:
    def __init__(self, dataset_path):
        self.path = Path(dataset_path)
        self.lock = Lock()
        self.dataset = None
        self.version = None
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
            elif path == "/healthz":
                self.load()
                body, content_type = b'{"status":"ok"}', "application/json"
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
    return Application(os.environ.get("GAIA_DATASET", "data/analysis.json"))
