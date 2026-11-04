"""Observed tile identity and Tim's exact opening-strategy grouping."""
import json
import math
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def technology_aliases():
    # This registry's aliases are tested against the original notebook parser.
    # Canonicalization is limited to the tile-level view; raw records are untouched.
    registry = json.loads((Path(__file__).resolve().parents[1] /
                           'web/cohort/tile-labels.json').read_text())
    return {category: {alias: tile for tile, entry in registry[category].items()
                       for alias in (tile, *entry['aliases'])}
            for category in ('basic', 'advanced')}


def technology_id(tile, advanced):
    return technology_aliases()['advanced' if advanced else 'basic'].get(tile, tile)


STRUCTURE_ORDER = ('m', 'ts', 'lab', 'PI', 'ac1', 'ac2')


def opening_configuration(structures):
    """Return exact counts and original class precedence, or unknown.

    Raw reconstruction uses sparse Counters: absent building types are known zero.
    Historical CSV maps are emitted only when all six counts are known. Explicit
    null/non-integer counts are not zero. Tim's successive assignments make ac2
    override ac1, which overrides PI, followed by labs, trading stations, mines.
    """
    if not isinstance(structures, dict):
        return None
    counts = {key: structures.get(key, 0) for key in STRUCTURE_ORDER}
    if any(not isinstance(value, (int, float)) or not math.isfinite(value)
           or value < 0 or int(value) != value for value in counts.values()):
        return None
    counts = {key: int(value) for key, value in counts.items()}
    category = next((key for key in ('ac2', 'ac1', 'PI', 'lab', 'ts') if counts[key]), 'm')
    label = '_'.join(f'{counts[key]}-{key.lower()}' for key in STRUCTURE_ORDER)
    return category, label, counts
