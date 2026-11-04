"""Immutable LF game objects with small per-release indexes; old rows stay readable."""
import hashlib
import json
from pathlib import Path
import re

from .__main__ import atomic_json

STORAGE = 'content-addressed-games-v1'


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def object_path(dataset, sha):
    dataset = Path(dataset)
    if not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{64}', sha):
        raise ValueError('Invalid LF object hash')
    if dataset.parent.parent.name != 'releases':
        raise ValueError('LF object index must belong to a release store')
    directory = dataset.parent.parent.parent / 'objects' / 'lost-fleet'
    path = directory / (sha + '.json')
    if path.resolve().parent != directory.resolve():
        raise ValueError('LF object escapes its store')
    return path


def load_dataset(path):
    """Resolve and verify every referenced object; do not trust a manifest alone."""
    path = Path(path)
    data = json.loads(path.read_text())
    if data.get('storage') is None:
        if data.get('schema_version') != 1 or not isinstance(data.get('rows'), list):
            raise ValueError('Unsupported dataset')
        return data
    if data.get('storage') != STORAGE or data.get('schema_version') != 1:
        raise ValueError('Unsupported LF storage')
    if not isinstance(data.get('games'), dict) or 'rows' in data:
        raise ValueError('Invalid LF object index')
    rows = []
    for slug, sha in sorted(data['games'].items()):
        raw = object_path(path, sha).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError('LF object hash mismatch: ' + slug)
        game = json.loads(raw)
        if not isinstance(game, list) or not game or any(row.get('game_id') != slug for row in game):
            raise ValueError('LF object identity mismatch: ' + slug)
        rows.extend(game)
    return {**data, 'rows': rows}


def write_dataset(path, groups, **metadata):
    """Only new/changed games allocate data; previous releases keep their objects."""
    path = Path(path)
    games = {}
    for slug, rows in sorted(groups.items()):
        raw = encoded(sorted(rows, key=lambda row: row['faction']))
        sha = hashlib.sha256(raw).hexdigest()
        target = object_path(path, sha)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError('Existing LF object is corrupt: ' + slug)
        else:
            # Publication holds the release-store lock. A partial object after a
            # crash cannot be selected: verification fails before pointer swap.
            with target.open('xb') as handle:
                handle.write(raw)
                handle.flush()
                import os
                os.fsync(handle.fileno())
        games[slug] = sha
    data = {'schema_version': 1, 'storage': STORAGE, 'games': games, **metadata}
    atomic_json(path, data)
    return data
