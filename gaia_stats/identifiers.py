"""Public BGS identifiers safe to use as one URL/path segment."""
import re
from urllib.parse import quote

# Historical game_names.txt contains bracketed, backtick and all-hyphen IDs.
# Keep one bounded ASCII filename component; do not normalize the identity.
SLUG = re.compile(r'[A-Za-z0-9-][A-Za-z0-9_\[\]`-]{0,120}\Z')


def valid_slug(value):
    return isinstance(value,str) and SLUG.fullmatch(value) is not None


def url_segment(value):
    if not valid_slug(value):raise ValueError('Invalid game identifier')
    return quote(value,safe='')
