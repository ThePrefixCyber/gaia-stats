# Gaia Stats development handoff

## Goal

Extend Tim Gladyshev's Gaia Project analysis to The Lost Fleet, with strictly
separate base/expansion tabs, datasets, exports and recommendations. The main
purpose is to compare build orders conditional on faction, setup/scoring,
opponents, player strength and expansion mechanics. Observed outcomes must not
be presented as proof of optimal strategy.

## Source and deployment

- Working repository: https://github.com/ThePrefixCyber/gaia-stats (main).
- Original source/history: https://github.com/TimGladyshev/bgs_data_gaia.
- Existing Tim site: https://gpstats.dev (not modified).
- User deployed to Vultr, Atlanta: http://45.76.250.100/.
- Server: Ubuntu 24.04, 2 shared AMD CPUs, 4 GB RAM, 100 GB NVMe.
- Code: `/opt/gaia-stats`; state/raw data: `/var/lib/gaia-stats`.
- Gunicorn systemd service: `gaia-stats`; Nginx fronts local port 8000 on port 80.
- Service account: `gaia-stats`; user's admin SSH account: root.
- No server password or private SSH key has been shared or committed.

The user verified the site works. The cloud agent fetched `/healthz` successfully
and confirmed 3 expansion games / 10 player records. Base has 1 game / 4 records.
Cloud-agent SSH attempts were refused even though the user's Mac can connect.
User output confirms sshd listening on all interfaces on port 22, with UFW
allowing SSH and Nginx. This is not evidence the server's SSH configuration needs
changing; investigate the agent's network path before asking for firewall edits.

An optional GitHub-polling deploy timer is included in `deploy/enable-updates.sh`.
It is **not confirmed enabled on the server**. Its README instructions are the
one-time bootstrap. It pulls main every two minutes, tests/restarts the app,
attempts verified code rollback on failure and writes a public non-secret deploy status.
Bootstrap validates tests and running commit before enabling polling; unchanged
checks validate health too. Shared-venv rollback remains best effort; see README.
It grants no interactive shell. GitHub Actions settings/secrets APIs returned
403 for this connection, so do not assume Actions administration is available.

## Implementation

- `gaia_stats/analysis.py`: BGS ruleset classification, normalization, VP ledger
  reconciliation, round-one building sequences, conditional filters and summaries.
- `gaia_stats/__main__.py`: ingest, fetch and local server CLI; shared HTTP response
  functions; atomic JSON output. Entirely invalid imports preserve previous data.
- `gaia_stats/wsgi.py`: production app, seeds examples only when dataset missing,
  hot-reloads dataset on next request. Health includes commit/counts/deploy status.
- `web/index.html`: separate Base/Lost Fleet tabs, independent filters, CSV export,
  opening comparisons, original moves and VP sources.
- `deploy/`: fresh VPS install, explicit game imports, optional polling deployer.
- `render.yaml`: alternative paid Render deployment, not used/activated.
- 33 Python tests cover real exports and production request/reload behavior and updater failure paths.
  Run `python -m unittest discover -s tests -v`.

Skill modes: All (including unrated), Top (90th percentile of pregame player-game
ratings separately by ruleset/player count; not a unique-player leaderboard),
Custom minimum player Elo. Additional table-average Elo filter preserves Tim's
notebook approach (cutoff 200, off by default). Thresholds are fixed before
faction/scoring filters; small samples are labelled.

## Next substantive work

1. Expand finished-game discovery beyond explicit slugs. The four fixtures are
   regression examples, not sufficient strategy evidence. No scheduled archive
   collection exists yet. Never imply the existing deploy timer collects games.
2. Improve import compatibility and gather fixtures for all Lost Fleet factions
   (Darkanians not covered) and mechanics. Preserve unknown scoring identifiers.
3. Add exploration/action/technology/booster timing analyses beyond building-only
   sequences; exact map/initial placement conditioning needs more work.
4. Add dataset freshness metadata and scalable storage/aggregation as archive grows.
5. Add domain/HTTPS and external backups. User's instance screenshot showed backups
   not enabled; do not claim otherwise.
6. Browser visual QA was interrupted. Python/API tests and Gunicorn smoke passed;
   do not claim a complete automated browser interaction test.

## Persistence

The live app survives this chat/workspace ending. GitHub preserves pushed code.
This chat and its private tool state do not migrate automatically to a VPS or a
new Codex session. A local/VPS Codex session can read this handoff and README;
use a separate development checkout rather than editing a timer-managed live
checkout. Keep long-running terminal sessions in tmux if appropriate.
