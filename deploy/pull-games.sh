#!/usr/bin/env bash
# Run as root: bash deploy/pull-games.sh GAME-SLUG [GAME-SLUG ...]
set -euo pipefail
if [[ $# -eq 0 ]]; then
    echo 'Usage: sudo bash deploy/pull-games.sh GAME-SLUG [GAME-SLUG ...]' >&2
    exit 1
fi
cd /opt/gaia-stats
runuser -u gaia-stats -- .venv/bin/python -m gaia_stats fetch "$@" --directory /var/lib/gaia-stats/raw
# Include the seed fixtures so incremental imports do not drop the initial games.
runuser -u gaia-stats -- .venv/bin/python -m gaia_stats ingest tests/fixtures/*.json /var/lib/gaia-stats/raw/*.json --output /var/lib/gaia-stats/analysis.json
