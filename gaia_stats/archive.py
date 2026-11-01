"""Resumable finished-game discovery; never writes the live analysis dataset.

python -m gaia_stats.archive --mode lost-fleet --directory /tmp/gaia-archive
Listing envelopes/order must be verified against live BGS before bulk operation.
Conservative incremental passes scan the listing again and download only new IDs.
"""
import argparse
from contextlib import contextmanager
import datetime
from email.utils import parsedate_to_datetime
import fcntl
import gzip
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .__main__ import atomic_json
from .analysis import normalize

ORIGIN = 'https://boardgamers.space'
SLUG = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,120}\Z')
MAX_BODY = 64 * 1024 * 1024


def atomic_bytes(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def retry_after_seconds(error, current_time=None):
    value = error.headers.get('Retry-After') if isinstance(error, HTTPError) and error.headers else None
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, parsedate_to_datetime(value).timestamp() -
                       (time.time() if current_time is None else current_time))
        except (ValueError, TypeError, OverflowError):
            return 0


class ArchiveClient:
    def __init__(self, *, interval=1.0, attempts=3, opener=urlopen, sleep=time.sleep, clock=time.monotonic):
        if interval < 1 or attempts < 1:
            raise ValueError('Use at least one second pacing and one attempt')
        self.interval, self.attempts = interval, attempts
        self.opener, self.sleep, self.clock = opener, sleep, clock
        self.last = None

    def get(self, url):
        for attempt in range(self.attempts):
            if self.last is not None:
                self.sleep(max(0, self.interval - (self.clock() - self.last)))
            self.last = self.clock()
            request = Request(url, headers={'Accept-Encoding': 'gzip',
                'User-Agent': 'GaiaStats-archive/0.1 (+https://github.com/ThePrefixCyber/gaia-stats)'})
            try:
                with self.opener(request, timeout=30) as response:
                    raw = response.read(MAX_BODY + 1)
                    if len(raw) > MAX_BODY:
                        raise ValueError('Response exceeds archive size limit')
                    encoding = response.headers.get('Content-Encoding', '')
                    if encoding.lower() == 'gzip' or raw.startswith(b'\x1f\x8b'):
                        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                            raw = compressed.read(MAX_BODY + 1)
                        if len(raw) > MAX_BODY:
                            raise ValueError('Decompressed response exceeds archive size limit')
                    return json.loads(raw), raw
            except (HTTPError, URLError, TimeoutError) as error:
                if isinstance(error, HTTPError) and error.code not in (408, 429, 500, 502, 503, 504):
                    raise
                if attempt + 1 == self.attempts:
                    raise
                delay = max(min(120, 2 ** (attempt + 1)), retry_after_seconds(error))
                if delay > 60:
                    raise  # Defer long server-requested waits to the persistent retry queue.
                self.sleep(delay)



def listing_entries(payload):
    # Explicit supported shape; do not silently treat an unknown envelope as EOF.
    if not isinstance(payload, list):
        raise ValueError('Unverified listing envelope: expected a JSON array')
    if any(not isinstance(item, dict) for item in payload):
        raise ValueError('Invalid listing entries')
    return payload


def listing_slug(entry):
    """The live public listing uses _id; older saved envelopes used slug."""
    if entry.get('slug') and entry.get('_id') and entry['slug'] != entry['_id']:
        raise ValueError('Conflicting listing identifiers')
    slug = entry.get('_id') or entry.get('slug')
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise ValueError('Invalid listing identifier')
    return slug


@contextmanager
def archive_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'collector.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('An archive collector is already running') from None
        yield


def collect(directory, mode, *, client=None, page_size=10, max_pages=100,
            max_downloads=100, overlap_pages=2, now=None):
    """Checkpoint bounded discovery and downloads, retaining raw/quarantined data.

    Offset resumes overlap prior pages to tolerate new entries. No early-stop
    assumption about listing sort order is made. SQLite holds the queue/statuses;
    only one export is normalized at a time. HTTP failures are retried on a later
    run. Previously accepted exports and live datasets are never replaced.
    """
    if mode not in ('base', 'lost-fleet'):
        raise ValueError('Choose explicit base or lost-fleet mode')
    if page_size < 1 or max_pages < 1 or max_downloads < 0 or overlap_pages < 0:
        raise ValueError('Invalid archive limits')
    root = Path(directory)
    now = time.time if now is None else now
    client = client or ArchiveClient()
    with archive_lock(root):
        with sqlite3.connect(root / 'archive.sqlite3') as db:
            db.execute('CREATE TABLE IF NOT EXISTS scans (mode TEXT PRIMARY KEY, cursor INTEGER, complete INTEGER)')
            db.execute('''CREATE TABLE IF NOT EXISTS exports (
                mode TEXT, slug TEXT, status TEXT, attempts INTEGER DEFAULT 0,
                retry_at REAL DEFAULT 0, reason TEXT, source_url TEXT, fetched_at TEXT,
                sha256 TEXT, PRIMARY KEY(mode,slug))''')
            db.execute('CREATE TABLE IF NOT EXISTS events (mode TEXT, recorded_at REAL, reason TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS cooldowns (host TEXT PRIMARY KEY, retry_at REAL)')
            summary = dict(mode=mode, pages=0, queued=0, accepted=0, rejected=0, retry=0, listing_error=None)
            cooldown = db.execute('SELECT retry_at FROM cooldowns WHERE host=?', (ORIGIN,)).fetchone()
            if cooldown and cooldown[0] > now():
                summary['listing_error'] = 'Server cooldown is active'
                summary['retry_at'] = cooldown[0]
                summary['totals'] = dict(db.execute('SELECT status,COUNT(*) FROM exports WHERE mode=? GROUP BY status', (mode,)))
                summary['checkpoint'] = db.execute('SELECT cursor,complete FROM scans WHERE mode=?', (mode,)).fetchone()
                return summary
            blocked = False
            row = db.execute('SELECT cursor,complete FROM scans WHERE mode=?', (mode,)).fetchone()
            cursor = row[0] if row and not row[1] else 0
            # Ensure small run budgets still advance beyond their overlap.
            offset = max(0, cursor - min(overlap_pages, max_pages - 1) * page_size)
            for _ in range(max_pages):
                query = {'count': page_size, 'skip': offset, 'boardgame': 'gaia-project'}
                if mode == 'lost-fleet':
                    query['expansion'] = 'lost-fleet'
                url = ORIGIN + '/api/game/status/ended?' + urlencode(query)
                try:
                    entries = listing_entries(client.get(url)[0])
                    if len(entries) > page_size:
                        raise ValueError('Listing page exceeds requested size')
                except (OSError, ValueError, TypeError) as error:
                    summary['listing_error'] = str(error)
                    if isinstance(error, HTTPError) and (error.code == 429 or retry_after_seconds(error, now()) > 0):
                        db.execute('INSERT OR REPLACE INTO cooldowns VALUES (?,?)',
                                   (ORIGIN, now() + max(60, retry_after_seconds(error, now()))))
                        blocked = True
                    db.execute('INSERT INTO events VALUES (?,?,?)', (mode, now(), str(error)))
                    db.commit()
                    break
                for entry in entries:
                    try:
                        slug = listing_slug(entry)
                    except ValueError as error:
                        db.execute('INSERT INTO events VALUES (?,?,?)', (mode, now(), str(error)))
                        continue
                    result = db.execute('INSERT OR IGNORE INTO exports(mode,slug,status) VALUES (?,?,?)',
                                        (mode, slug, 'pending'))
                    summary['queued'] += result.rowcount
                offset += len(entries)
                complete = int(len(entries) < page_size)
                db.execute('INSERT OR REPLACE INTO scans VALUES (?,?,?)', (mode, offset, complete))
                db.commit()  # Queue and checkpoint commit together, before network downloads.
                summary['pages'] += 1
                if complete:
                    break
            queue = db.execute('''SELECT slug,attempts FROM exports WHERE mode=?
                AND status IN ('pending','retry') AND retry_at<=? ORDER BY rowid LIMIT ?''',
                (mode, now(), 0 if blocked else max_downloads)).fetchall()
            for slug, attempts in queue:
                url = ORIGIN + '/api/gameplay/' + slug
                fetched_at = datetime.datetime.fromtimestamp(now(), datetime.timezone.utc).isoformat()
                digest = None
                rate_until = 0
                try:
                    payload, raw = client.get(url)
                    digest = hashlib.sha256(raw).hexdigest()
                    # Retain every fetched JSON, including rejected games, with provenance.
                    atomic_bytes(root / mode / 'raw' / (slug + '.json'), raw)
                    atomic_json(root / mode / 'provenance' / (slug + '.json'),
                                {'url': url, 'fetched_at': fetched_at, 'response_sha256': digest,
                                 'requested_mode': mode, 'slug': slug})
                    if not isinstance(payload, dict) or payload.get('slug') != slug:
                        raise ValueError('Export slug does not match listing')
                    rows = normalize(payload)
                    if len(rows) not in (2, 3, 4):
                        raise ValueError('Unsupported player count')
                    if rows[0]['ruleset'] != mode:
                        raise ValueError('Export ruleset differs from requested mode')
                    if not all(row['score_verified'] for row in rows):
                        raise ValueError('VP ledger mismatch')
                    atomic_json(root / mode / 'rows' / (slug + '.json'),
                                {'schema_version': 1, 'source_sha256': digest, 'rows': rows})
                    status, reason, retry_at = 'accepted', None, 0
                except (URLError, TimeoutError, ConnectionError) as error:
                    status, reason = 'retry', str(error)
                    retry_at = now() + max(min(86400, 60 * 2 ** min(attempts, 10)),
                                           retry_after_seconds(error, now()))
                    if isinstance(error, HTTPError) and (error.code == 429 or retry_after_seconds(error, now()) > 0):
                        rate_until = retry_at
                except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
                    status, reason, retry_at = 'rejected', str(error), 0
                # Disk/permission errors deliberately propagate: never mark unpersisted data accepted.
                db.execute('''UPDATE exports SET status=?, attempts=?, retry_at=?, reason=?,
                    source_url=?, fetched_at=?, sha256=? WHERE mode=? AND slug=?''',
                    (status, attempts + 1, retry_at, reason, url, fetched_at, digest, mode, slug))
                if rate_until:
                    db.execute('INSERT OR REPLACE INTO cooldowns VALUES (?,?)', (ORIGIN, rate_until))
                db.commit()
                summary[status] += 1
                if rate_until:
                    break
            summary['totals'] = dict(db.execute('SELECT status,COUNT(*) FROM exports WHERE mode=? GROUP BY status', (mode,)))
            summary['checkpoint'] = db.execute('SELECT cursor,complete FROM scans WHERE mode=?', (mode,)).fetchone()
            return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('base', 'lost-fleet'), required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--page-size', type=int, default=10)
    parser.add_argument('--max-pages', type=int, default=100)
    parser.add_argument('--max-downloads', type=int, default=100)
    parser.add_argument('--overlap-pages', type=int, default=2)
    parser.add_argument('--interval', type=float, default=1)
    args = parser.parse_args()
    result = collect(args.directory, args.mode, client=ArchiveClient(interval=args.interval),
                     page_size=args.page_size, max_pages=args.max_pages,
                     max_downloads=args.max_downloads, overlap_pages=args.overlap_pages)
    print(json.dumps(result, indent=2))
    if result['listing_error'] or result['retry']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
