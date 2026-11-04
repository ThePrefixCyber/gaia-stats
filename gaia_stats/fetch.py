"""Small, deliberate BGS downloads. Archive discovery/scheduling is a separate job."""
import json
from pathlib import Path
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from .eligibility import excluded_export
from .analysis import normalize
from .__main__ import atomic_json
from .identifiers import valid_slug,url_segment


def fetch_games(slugs, directory):
    failures = 0
    for index, slug in enumerate(dict.fromkeys(slugs)):
        if not valid_slug(slug):
            print(f"Rejected invalid game slug: {slug!r}")
            failures += 1
            continue
        if index:
            time.sleep(1)
        try:
            request = Request("https://www.boardgamers.space/api/gameplay/" + url_segment(slug),
                              headers={"User-Agent": "GaiaStats/0.1 (+https://github.com/ThePrefixCyber/gaia-stats)"})
            with urlopen(request, timeout=30) as response:
                game = json.load(response)
            if not isinstance(game,dict) or game.get('slug')!=slug:
                raise ValueError('Export slug does not match request')
            if excluded_export(game):
                atomic_json(Path(directory) / (slug + ".json"), game)
                print(f"Retained raw {slug}: excluded from statistics by game eligibility policy")
                continue
            rows = normalize(game)
            if any(not r["score_verified"] for r in rows):
                raise ValueError("VP ledger mismatch")
            atomic_json(Path(directory) / (slug + ".json"), game)
            print(f"Saved {slug}: {rows[0]['ruleset']}, {len(rows)} players")
        except (URLError, TimeoutError, ValueError, KeyError, TypeError, IndexError) as exc:
            print(f"Skipped {slug}: {exc}")
            failures += 1
    return failures
