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
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .__main__ import atomic_json
from .analysis import normalize, ruleset
from .identifiers import valid_slug

ORIGIN = 'https://boardgamers.space'
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


class ListingIdentifierError(ValueError):
    def __init__(self,message,entry):
        super().__init__(message)
        self.evidence={}
        for key in ('_id','slug'):
            if key in entry:
                value=entry[key]
                self.evidence[key]={'type':type(value).__name__}
                if isinstance(value,str):
                    self.evidence[key].update(value=value[:160],length=len(value))


def listing_slug(entry):
    """The live public listing uses _id; older saved envelopes used slug."""
    if entry.get('slug') and entry.get('_id') and entry['slug'] != entry['_id']:
        raise ListingIdentifierError('Conflicting listing identifiers',entry)
    slug = entry.get('_id') or entry.get('slug')
    if not valid_slug(slug):
        raise ListingIdentifierError('Invalid listing identifier',entry)
    return slug


def listing_cursor(entry):
    """Deployed BGS ended-list contract: endedAt + _id, never lastMove."""
    if not isinstance(entry, dict) or not entry.get('_id') or 'endedAt' not in entry:
        raise ValueError('Cursor listing requires _id and endedAt (explicit null allowed)')
    slug = listing_slug(entry)
    at = entry['endedAt']
    if at is not None:
        if not isinstance(at, str) or len(at) > 40:
            raise ValueError('Invalid endedAt cursor timestamp')
        try:
            stamp = datetime.datetime.fromisoformat(at.replace('Z', '+00:00'))
            if stamp.tzinfo is None:raise ValueError('Timestamp must include timezone')
        except ValueError as error:
            raise ValueError('Invalid endedAt cursor timestamp') from error
    return json.dumps({'status':'ended','at':at,'id':slug},separators=(',',':'))


def validate_cursor(token):
    try:
        value=json.loads(token)
        if set(value)!= {'status','at','id'} or value['status']!='ended':raise ValueError()
        return listing_cursor({'_id':value['id'],'endedAt':value['at']})
    except (ValueError,TypeError,KeyError,AttributeError) as error:
        raise ValueError('Invalid saved listing cursor; checkpoint retained') from error


def explicitly_lost_fleet(entry):
    """Only explicit, consistent export/listing metadata may skip a base download."""
    try:
        return ruleset(entry) == 'lost-fleet'
    except (ValueError, TypeError, AttributeError):
        return False  # Ambiguous metadata must be resolved by the full export.


def record_listing_skip(root, db, slug, entry, url, now):
    existing=db.execute('SELECT status FROM exports WHERE mode="base" AND slug=?',(slug,)).fetchone()
    if existing and existing[0] not in ('pending','retry'):
        return 0
    # Save the exact public listing evidence before marking the queue entry skipped.
    atomic_json(root/'base'/'listing-skipped'/(slug+'.json'),
                {'source_url':url,'observed_at':datetime.datetime.fromtimestamp(now,datetime.timezone.utc).isoformat(),
                 'entry':entry,'reason':'Explicit Lost Fleet listing metadata'})
    db.execute('INSERT OR IGNORE INTO exports(mode,slug,status) VALUES (?,?,?)',('base',slug,'pending'))
    db.execute('UPDATE exports SET status="skipped",reason=?,source_url=? WHERE mode="base" AND slug=?',
               ('Explicit Lost Fleet listing metadata',url,slug))
    return 1


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
            max_downloads=100, overlap_pages=2, now=None, head_only=False, pagination='offset'):
    """Checkpoint bounded discovery and downloads, retaining raw/quarantined data.

    Offset mode is retained for compatibility; refresh and the CLI use cursor mode.
    Cursor checkpoints start independently at the head, never from old offsets.
    Only one export is normalized at a time. HTTP failures are retried on a later
    run. Previously accepted exports and live datasets are never replaced.
    """
    if mode not in ('base', 'lost-fleet'):
        raise ValueError('Choose explicit base or lost-fleet mode')
    if page_size < 1 or max_pages < 1 or max_downloads < 0 or overlap_pages < 0:
        raise ValueError('Invalid archive limits')
    if pagination not in ('offset','cursor') or (pagination=='cursor' and page_size>99):
        raise ValueError('Cursor pages must reserve one lookahead within the API count cap of 100')
    root = Path(directory)
    now = time.time if now is None else now
    client = client or ArchiveClient()
    with archive_lock(root):
        with sqlite3.connect(root / 'archive.sqlite3') as db:
            db.execute('CREATE TABLE IF NOT EXISTS scans (mode TEXT PRIMARY KEY, cursor INTEGER, complete INTEGER)')
            db.execute('''CREATE TABLE IF NOT EXISTS cursor_scans (
                mode TEXT PRIMARY KEY, after_token TEXT, complete INTEGER, pages INTEGER)''')
            db.execute('CREATE TABLE IF NOT EXISTS cursor_seen (mode TEXT, token TEXT, PRIMARY KEY(mode,token))')
            db.execute('''CREATE TABLE IF NOT EXISTS exports (
                mode TEXT, slug TEXT, status TEXT, attempts INTEGER DEFAULT 0,
                retry_at REAL DEFAULT 0, reason TEXT, source_url TEXT, fetched_at TEXT,
                sha256 TEXT, PRIMARY KEY(mode,slug))''')
            db.execute('CREATE TABLE IF NOT EXISTS events (mode TEXT, recorded_at REAL, reason TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS cooldowns (host TEXT PRIMARY KEY, retry_at REAL)')
            summary = dict(mode=mode, pages=0, queued=0, accepted=0, rejected=0, retry=0, skipped=0, listing_error=None)
            summary['pagination']=pagination
            if pagination=='cursor':
                summary['cursor_checkpoint']=db.execute('SELECT after_token,complete,pages FROM cursor_scans WHERE mode=?',(mode,)).fetchone()
            cooldown = db.execute('SELECT retry_at FROM cooldowns WHERE host=?', (ORIGIN,)).fetchone()
            if cooldown and cooldown[0] > now():
                summary['listing_error'] = 'Server cooldown is active'
                summary['retry_at'] = cooldown[0]
                summary['totals'] = dict(db.execute('SELECT status,COUNT(*) FROM exports WHERE mode=? GROUP BY status', (mode,)))
                summary['checkpoint'] = db.execute('SELECT cursor,complete FROM scans WHERE mode=?', (mode,)).fetchone()
                return summary
            blocked = False
            row = db.execute('SELECT cursor,complete FROM scans WHERE mode=?', (mode,)).fetchone()
            cursor = row[0] if row and not row[1] and not head_only else 0
            # Ensure small run budgets still advance beyond their overlap.
            offset = max(0, cursor - min(overlap_pages, max_pages - 1) * page_size)
            cursor_state=db.execute('SELECT after_token,complete,pages FROM cursor_scans WHERE mode=?',(mode,)).fetchone()
            restart=not cursor_state or bool(cursor_state[1])
            after=None if pagination=='offset' or head_only or restart else validate_cursor(cursor_state[0])
            cursor_pages=0 if restart else cursor_state[2]
            head_seen=set()
            seen_in_scan = []
            for _ in range(max_pages):
                query = {'count': page_size+(pagination=='cursor'), 'skip': 0 if pagination=='cursor' else offset, 'boardgame': 'gaia-project'}
                if pagination=='cursor' and after is not None:query['after']=after
                if mode == 'lost-fleet':
                    query['expansion'] = 'lost-fleet'
                url = ORIGIN + '/api/game/status/ended?' + urlencode(query)
                try:
                    entries = listing_entries(client.get(url)[0])
                    if len(entries) > query['count']:
                        raise ValueError('Listing page exceeds requested size')
                    if pagination=='cursor':
                        tokens=[]
                        for index,entry in enumerate(entries):
                            try:tokens.append(listing_cursor(entry))
                            except ListingIdentifierError as error:
                                error.evidence['page_index']=index
                                raise
                        ids=[listing_slug(entry) for entry in entries]
                        if len(set(ids))!=len(ids) or (after and json.loads(after)['id'] in ids):
                            raise ValueError('Cursor page duplicates an identity or repeats its boundary')
                        complete=int(len(entries)<=page_size)
                        entries=entries[:page_size]
                        next_after=tokens[len(entries)-1] if entries else after
                        if entries and (next_after in head_seen or (not head_only and not restart and db.execute(
                                'SELECT 1 FROM cursor_seen WHERE mode=? AND token=?',(mode,next_after)).fetchone())):
                            raise ValueError('Cursor did not advance; checkpoint retained')
                except (OSError, ValueError, TypeError) as error:
                    summary['listing_error'] = str(error)
                    summary['listing_error_detail'] = {'url': url, 'offset': offset,
                        'http_status': error.code if isinstance(error, HTTPError) else None}
                    if pagination=='cursor':summary['listing_error_detail'].update(offset=0,after=after)
                    if isinstance(error,ListingIdentifierError):
                        summary['listing_error_detail'].update(kind='invalid-listing-identifier',entry=error.evidence)
                    if isinstance(error, HTTPError):
                        # Public response evidence, bounded independently of export bodies.
                        try:
                            summary['listing_error_detail']['body'] = error.read(4096).decode('utf-8', errors='replace')
                        except OSError:
                            pass
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
                    seen_in_scan.append(slug)
                    if mode=='base' and explicitly_lost_fleet(entry):
                        summary['skipped']+=record_listing_skip(root,db,slug,entry,url,now())
                        continue
                    result = db.execute('INSERT OR IGNORE INTO exports(mode,slug,status) VALUES (?,?,?)',
                                        (mode, slug, 'pending'))
                    summary['queued'] += result.rowcount
                offset += len(entries)
                if pagination=='offset':complete = int(len(entries) < page_size)
                if not head_only and pagination=='offset':
                    db.execute('INSERT OR REPLACE INTO scans VALUES (?,?,?)', (mode, offset, complete))
                elif not head_only:
                    if restart:db.execute('DELETE FROM cursor_seen WHERE mode=?',(mode,))
                    if entries:db.execute('INSERT INTO cursor_seen VALUES (?,?)',(mode,next_after))
                    cursor_pages+=1
                    db.execute('INSERT OR REPLACE INTO cursor_scans VALUES (?,?,?,?)',(mode,next_after,complete,cursor_pages))
                db.commit()  # Queue and checkpoint commit together, before network downloads.
                if pagination=='cursor':
                    after=next_after
                    head_seen.add(after)
                    restart=False
                summary['pages'] += 1
                if complete:
                    break
            if mode=='base':
                summary['skipped']+=db.execute("""UPDATE exports AS b SET status='skipped',
                    reason='Already validated as Lost Fleet in the local archive'
                    WHERE b.mode='base' AND b.status IN ('pending','retry') AND EXISTS
                    (SELECT 1 FROM exports AS lf WHERE lf.mode='lost-fleet' AND lf.slug=b.slug AND lf.status='accepted')""").rowcount
                db.commit()
            scope = ''
            parameters = [mode, now()]
            if head_only:
                scope = ' AND slug IN (' + ','.join('?' for _ in seen_in_scan) + ')' if seen_in_scan else ' AND 0'
                parameters.extend(seen_in_scan)
            queue = db.execute("SELECT slug,attempts FROM exports WHERE mode=? "
                "AND status IN ('pending','retry') AND retry_at<=?" + scope + ' ORDER BY rowid LIMIT ?',
                parameters + [0 if blocked else max_downloads]).fetchall()
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
            if pagination=='cursor':
                summary['cursor_checkpoint']=db.execute('SELECT after_token,complete,pages FROM cursor_scans WHERE mode=?',(mode,)).fetchone()
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
    parser.add_argument('--pagination',choices=('cursor','offset'),default='cursor')
    args = parser.parse_args()
    result = collect(args.directory, args.mode, client=ArchiveClient(interval=args.interval),
                     page_size=args.page_size, max_pages=args.max_pages,
                     max_downloads=args.max_downloads, overlap_pages=args.overlap_pages,pagination=args.pagination)
    print(json.dumps(result, indent=2))
    if result['listing_error'] or result['retry']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
