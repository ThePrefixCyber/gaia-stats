"""Production WSGI entry point; read-only HTTP, disk-backed dataset with hot reload."""
import json
import datetime
import os
import subprocess
import sqlite3
from pathlib import Path
from threading import Lock
from collections import OrderedDict
from urllib.parse import parse_qs

from .eligibility import eligible_rows, require_safe_policy
from .release_data import load_dataset
from .__main__ import ingest, response_for
from .legacy_cache import is_classic_path


_UNSET = object()

def running_commit():
    try:
        return subprocess.check_output(
            ["git", "-c", "safe.directory=" + str(Path(__file__).resolve().parent.parent), "rev-parse", "HEAD"],
            cwd=Path(__file__).parent.parent, text=True, timeout=3,
            stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.SubprocessError):
        return None


class Application:
    def __init__(self, dataset_path, classic_cache=None, base_cohort=None, seed_missing=True, code_commit=_UNSET, excluded_game_ids=()):
        self.path = Path(dataset_path)
        self.classic_cache = classic_cache
        self.excluded_game_ids = frozenset(excluded_game_ids)
        self.base_cohort = Path(base_cohort) if base_cohort else None
        self.cohort_lock = Lock()
        self.cohort_cache = OrderedDict()
        self.cache_lock = Lock()
        self.cohort_cache_bytes = 0
        self.lock = Lock()
        self.dataset = None
        self.version = None
        self.commit = running_commit() if code_commit is _UNSET else code_commit
        if not self.path.exists():
            if not seed_missing:raise FileNotFoundError('Release dataset missing; refusing example seeding')
            fixtures = Path(__file__).parent.parent / "tests/fixtures"
            ingest(sorted(fixtures.glob("*.json")), self.path)

    def load(self):
        return self.load_snapshot()[0]

    def load_snapshot(self):
        with self.lock:
            info = self.path.stat()
            version = (info.st_mtime_ns, info.st_size)
            if version != self.version:
                candidate = load_dataset(self.path)
                if candidate.get("schema_version") != 1 or not isinstance(candidate.get("rows"), list):
                    raise ValueError("Unsupported dataset")
                require_safe_policy(candidate.get("eligibility_policy"))
                candidate["rows"] = [r for r in eligible_rows(candidate["rows"]) if r["game_id"] not in self.excluded_game_ids]
                self.dataset, self.version = candidate, version
            return self.dataset, self.version

    def cohort_response(self, path, filters):
        from .cohort import response
        if path == '/cohort/tile-labels.js':
            return response(None, path, {})
        allowed={'ruleset','plot','player_count','faction','min_elo','lf_2p_4qic_mode',
                 'layout','auction','faction_variant','final_scoring','final_scoring2'}
        allowed.update(f'round{i}' for i in range(1,7))
        allowed.update('adv-'+slot for slot in ('terra','nav','int','gaia','eco','sci','ext'))
        if set(filters)-allowed or any(len(str(v))>200 for v in filters.values()):
            raise ValueError('Unsupported cohort filter')
        if filters.get('player_count') and filters['player_count'] not in ('2','3','4'):
            raise ValueError('Choose 2, 3 or 4 players')
        # The shell and script do not use cohort data. Never queue them behind
        # an expensive calculation or decode the LF dataset just to serve bytes.
        if path in ('/cohort/', '/cohort/app.js', '/cohort/tables.js', '/cohort/styles.css', '/cohort/basic-tech.js'):
            return response({}, path, filters)
        is_base = filters.get('ruleset') == 'base' and path.startswith('/cohort/api/')
        if is_base:
            if self.base_cohort is None:
                raise ValueError('Base cohort database not configured')
            from . import base_cohort
            if path == '/cohort/api/catalog':
                return json.dumps(base_cohort.catalog(self.base_cohort)).encode(), 'application/json'
            filters = dict(filters)
            if path == '/cohort/api/stats':
                filters.setdefault('plot', 'advanced-tech-frequency')

        def snapshot():
            if is_base:
                stat = self.base_cohort.stat()
                return ('base', stat.st_mtime_ns, stat.st_size), None
            dataset, version = self.load_snapshot()
            return ('lf', version), dataset

        def cached(key):
            with self.cache_lock:
                if key in self.cohort_cache:
                    self.cohort_cache.move_to_end(key)
                    return self.cohort_cache[key]
            return None

        version, dataset = snapshot()
        key = (version, path, tuple(sorted(filters.items())))
        hit = cached(key)
        if hit is not None:
            return hit
        # Only cache misses serialize expensive work. Hits must not wait behind
        # another user's cold query. Recheck after waiting for a concurrent fill
        # or dataset change; retain bounded JSON only, never decoded base rows.
        with self.cohort_lock:
            version, dataset = snapshot()
            key = (version, path, tuple(sorted(filters.items())))
            hit = cached(key)
            if hit is not None:
                return hit
            result = (base_cohort.response(self.base_cohort, path, filters) if is_base
                      else response(dataset, path, filters))
            if path == '/cohort/api/stats' and len(result[0]) <= 2 * 1024 * 1024:
                with self.cache_lock:
                    self.cohort_cache[key] = result
                    self.cohort_cache_bytes += len(result[0])
                    while len(self.cohort_cache) > 8 or self.cohort_cache_bytes > 16 * 1024 * 1024:
                        _, old = self.cohort_cache.popitem(last=False)
                        self.cohort_cache_bytes -= len(old[0])
            return result

    def __call__(self, environ, start_response):
        status, headers = "200 OK", [("Cache-Control", "no-store")]
        path = environ.get("PATH_INFO", "/")
        if path == "/" and self.base_cohort is not None:
            path = "/cohort/"
        filters = {key: values[-1] for key, values in parse_qs(environ.get("QUERY_STRING", "")).items()}
        try:
            if environ.get("REQUEST_METHOD") != "GET":
                status, body, content_type = "405 Method Not Allowed", b"GET only", "text/plain"
                headers.append(("Allow", "GET"))
            elif path.startswith('/art/'):
                from .artwork import response as artwork_response
                body, content_type = artwork_response(path)
            elif path.startswith('/cohort/'):
                body, content_type = self.cohort_response(path, filters)
                if path == '/cohort/api/export':
                    headers.append(('Content-Disposition', 'attachment; filename="gaia-cohort.csv"'))
            elif self.classic_cache is not None and is_classic_path(path):
                from .legacy_cache import cache_response
                body, content_type, download = cache_response(self.classic_cache, path, filters, excluded_game_ids=self.excluded_game_ids)
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
        except sqlite3.Error as exc:
            status, body, content_type = '503 Service Unavailable', json.dumps({'error':'Cohort database unavailable: '+str(exc)}).encode(), 'application/json'
        except (ValueError, KeyError) as exc:
            status, body, content_type = "400 Bad Request", json.dumps({"error": str(exc)}).encode(), "application/json"
        headers.extend([("Content-Type", content_type), ("Content-Length", str(len(body))),
                        ("X-Content-Type-Options", "nosniff")])
        start_response(status, headers)
        return [body]


class ReleaseApplication:
    """Pin each request to one immutable release; discard old response caches on swap."""
    def __init__(self,root,classic_cache=None):
        self.root=Path(root);self.classic_cache=classic_cache;self.lock=Lock()
        self.active=None;self.exclusion_version=None;self.app=None;self.manifest=None
        self.work_lock=Lock();self.commit=running_commit()

    def __call__(self,environ,start_response):
        from .releases import current,validate,known_exclusions
        try:
            with self.lock:
                path=current(self.root)
                if path is None:raise ValueError('No validated data release has been published')
                try:
                    info=(self.root/'exclusions.json').stat()
                    exclusion_version=(info.st_mtime_ns, info.st_size)
                except FileNotFoundError:exclusion_version=None
                if path!=self.active or exclusion_version!=self.exclusion_version:
                    with self.work_lock:
                        excluded=known_exclusions(self.root)
                        manifest=validate(path,known_exclusions=excluded)
                        if manifest.get('schema_version')!=1:raise ValueError('Unsupported data release')
                        app=Application(path/'lost-fleet.json',classic_cache=self.classic_cache,
                                        base_cohort=path/'base.sqlite',seed_missing=False,code_commit=self.commit,excluded_game_ids=excluded)
                        app.cohort_lock=self.work_lock
                        self.active,self.app,self.manifest=path,app,manifest
                        self.exclusion_version=exclusion_version
                app,manifest=self.app,self.manifest
            # References above keep an in-flight request pinned while another swaps releases.
            if environ.get('PATH_INFO')=='/healthz' and environ.get('REQUEST_METHOD','GET')=='GET':
                try:freshness=json.loads((self.root/'refresh-status.json').read_text())
                except FileNotFoundError:freshness={'state':'never-run','last_success':None}
                now=datetime.datetime.now(datetime.timezone.utc)
                def age(value):
                    try:return max(0,(now-datetime.datetime.fromisoformat(value)).total_seconds())
                    except (TypeError,ValueError):return None
                success_age=age(freshness.get('last_success'))
                freshness['last_success_age_seconds']=success_age
                freshness['stale']=success_age is None or success_age>3600
                running_age=age(freshness.get('started_at'))
                if freshness.get('state')=='running' and running_age is not None and running_age>900:
                    freshness.update(state='interrupted-or-timed-out',error='Refresh has no completion within its runtime bound')
                body=json.dumps({'status':'ok','commit':app.commit,'release':manifest['release'],
                    'datasets':manifest['datasets'],'raw_accepted_games':manifest['raw_accepted_games'],
                    'coverage':manifest['coverage'],'data_created_at':manifest['created_at'],'refresh':freshness,
                    'games':sum(v['games'] for v in manifest['datasets'].values()),
                    'player_records':sum(v['records'] for v in manifest['datasets'].values())}).encode()
                start_response('200 OK',[('Content-Type','application/json'),('Cache-Control','no-store'),('Content-Length',str(len(body)))])
                return [body]
            return app(environ,start_response)
        except (OSError,ValueError,KeyError,sqlite3.Error) as error:
            body=json.dumps({'status':'unavailable','error':str(error)}).encode()
            start_response('503 Service Unavailable',[('Content-Type','application/json'),('Cache-Control','no-store')])
            return [body]


def create_app():
    if os.environ.get('GAIA_DATA_BUNDLE'):
        from .data_bundle import paths
        bundle = paths(os.environ['GAIA_DATA_BUNDLE'], require_ready=True)
        return ReleaseApplication(bundle['root'], bundle['classic_cache'])
    if os.environ.get('GAIA_RELEASE_ROOT'):
        return ReleaseApplication(os.environ['GAIA_RELEASE_ROOT'],os.environ.get('GAIA_CLASSIC_CACHE'))
    return Application(os.environ.get("GAIA_DATASET", "data/analysis.json"),
                       classic_cache=os.environ.get("GAIA_CLASSIC_CACHE"),
                       base_cohort=os.environ.get("GAIA_BASE_COHORT"))
