"""Resolve a paired data bundle once, so an active worker cannot follow a swap."""
from pathlib import Path
import json


def paths(bundle, *, require_ready=False):
    root = Path(bundle).resolve(strict=True)
    if require_ready:
        state = json.loads((root/'preparation.json').read_text())
        if state.get('state') != 'ready':
            raise ValueError('Data bundle has not passed migration preflight')
    result = {'bundle':root, 'root':root/'releases-store',
              'seed_base':root/'seeds/base.sqlite', 'classic_cache':root/'classic-cache'}
    for key, value in result.items():
        if key != 'bundle' and not value.resolve().is_relative_to(root):
            raise ValueError('Data bundle member escapes its selected bundle')
    return result
