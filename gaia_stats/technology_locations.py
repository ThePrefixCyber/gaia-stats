"""Analytical Free groups; numbered source positions remain in audit records."""
import math

FREE_SLOTS = ('free1', 'free2', 'free3')
FREE_SOURCES = tuple('tech-' + slot for slot in FREE_SLOTS)
FREE_GROUPING_VERSION = 'free-v1'


def location(slot):
    """Merge only the three basic-tech free positions, never other locations."""
    return 'free' if slot in FREE_SLOTS else slot


def sources(values, *, complete=False):
    """Sum Free VP within each player-game before distributions or averages.

    Complete ledgers imply zero for absent positions. In incomplete ledgers a
    missing component is unknown, not zero. Already combined input is idempotent.
    Original dictionaries are never modified; callers retain them for audit.
    """
    if not any(key in values for key in FREE_SOURCES):
        return dict(values)
    result = {key: value for key, value in values.items() if key not in FREE_SOURCES}
    parts = [values.get(key, 0 if complete else None) for key in FREE_SOURCES]
    if 'tech-free' in values:
        parts.append(values['tech-free'])
    result['tech-free'] = (math.fsum(parts) if all(type(value) in (int, float)
                          and math.isfinite(value) for value in parts) else None)
    return result
