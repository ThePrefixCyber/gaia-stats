"""Public BGS identifiers safe to use as one URL/path segment."""
import re

# A verified historical game is '-remote-Christmas-party'. Keep the existing
# 121-character cap and require an alphanumeric character after one leading '-'.
SLUG = re.compile(r'(?:[A-Za-z0-9][A-Za-z0-9_-]{0,120}|-[A-Za-z0-9][A-Za-z0-9_-]{0,119})\Z')


def valid_slug(value):
    return isinstance(value,str) and SLUG.fullmatch(value) is not None
