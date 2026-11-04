# Gaia Stats

Gaia Project statistics for the base game and Lost Fleet, extending
[Timothy Gladyshev's original project](https://github.com/TimGladyshev/bgs_data_gaia)
and the chart families shown at [gpstats.dev](https://gpstats.dev).
The current application uses a new shared interface with corrected statistics;
it does not claim pixel-perfect reproduction of Tim's site.

The public deployment is [http://45.76.250.100](http://45.76.250.100).
As of **2026-11-02 09:22 UTC**, the rebuilt application, GitHub-polling code
updates and scheduled cursor-based archive refresh were verified running.
Base collection is stopped. This branch stages the CSV-only source transition.
Use `/healthz` for current release counts, discovery checkpoints and refresh status
rather than treating
this README as a live inventory. HTTPS and off-server backups are not established.

## Current statistics and filters

The root page offers independent base/Lost Fleet modes, 2/3/4-player selection,
observed factions (including the four new LF factions), minimum individual pregame
Elo, layout, auction and faction-variant filters, plus round/final scoring and
available advanced-tech selections. Options depend on the selected dataset;
missing historical metadata remains unknown. Missing Elo is included without a
cutoff and excluded when a numeric minimum is set. Mode selections are remembered
within the browser session. Player counts are 4 (default), 3, 2 and Any. The LF
4-QIC control is shown only for 2/Any, and a Layout control is shown only when
multiple known layouts are available. Hidden controls do not add request filters;
their previous selections are retained for when they apply again.

Games explicitly marked **more-balanced** are excluded site-wide, in both base
and Lost Fleet modes. They are not a selectable cohort. Unknown or missing variant
metadata stays unknown and is not assumed to be more-balanced. Original exports,
source CSVs and prior releases are retained for audit/recovery. See
[GAME_ELIGIBILITY.md](docs/GAME_ELIGIBILITY.md) for metadata and cache migration.

The significant two-player LF **4-QIC → technology** variant has three choices:
**standard only** (default), **both**, and **variant only**. Classification uses
explicit BGS option metadata, not faction names. The default excludes that
variant; it does not remove ordinary three- and four-player LF games.

All nine chart views and the selected player-game CSV honor the faction filter.
The two always-visible faction and advanced-tech comparison tables include all
factions, retaining every other selected filter and scoring setup. Selecting a
faction with no graph observations can still leave valid comparison rows for
other factions. Chart views include:

- Three basic-technology views: acquisition by setup location, acquirers’ mean score by source location, and all setup observations’ mean score. Advanced technology frequency and mean-score plots remain available. See [basic-tech methods](docs/BASIC_TECH_MODES.md).
- Round-one structure treemap.
- Round and final scoring heatmaps, alongside shared-win heatmaps.
- Signed VP-source distributions with exact quartiles and min/max whiskers.

Sample counts and unavailable observations are shown. Empty selections produce
no-data results rather than invented zero scores. All current cohort table columns
can be sorted using their heading buttons (click, Enter or Space). A second
activation reverses direction; missing measurements stay last. Each table keeps
its sort when filters refresh. Percentages, VP and sample counts are formatted
for readability; numeric sorts use the unrounded values. Separate historical wide-CSV
links do not reflect current UI selections, but also exclude more-balanced games.

Every statistical view and export excludes the entire game when any player has
an observed score before auction bids below 100 VP. Exactly 100 is retained; missing scores
are not treated as zero. This mandatory rule is applied before faction and Elo
filters, in both modes, alongside the more-balanced exclusion. Raw source data
remains preserved for audit. See [game eligibility](docs/GAME_ELIGIBILITY.md).

Current views use one player-game observation, pre-bid VP, competition
ranks and shared credit for ties after excluding signed auction contributions.
Original printed results and signed bid deltas remain in audit/export fields. Round/final heatmaps show VP earned from the tile or final tile pair in
**both** modes; conditional final score is separately labelled. Technology
frequency denominators are observed available player-game opportunities.

Raw VP totals reconcile against printed final scores including the initial 10 points.
Analytical VP sources omit auction contributions and reconcile to pre-bid totals.
Only verified complete ledgers imply zeros for missing scoring events; historical
CSV blanks remain unknown. Base raw source categories are phase-aware, LF source
names retain expansion contributions, and original raw totals remain available.
Tile-VP denominators exclude unavailable measurements. See
[PREBID_SCORING.md](docs/PREBID_SCORING.md) for current definitions and migration requirements.
These are descriptive associations, not causal strategy recommendations or
skill-adjusted predictions; repeated players contribute repeated observations.

## Data collection and publication

This branch prepares the base-game statistics solely from the original static
wide CSVs. Pre-bid scores use each player's aligned auction cost; dropped games,
more-balanced games and games with any known pre-bid score below 100 remain
excluded. Base raw exports never add or replace served base observations.
The existing base raw archive, queue and historical release files are preserved.
Switching an older merged-base release requires the separately reviewed bundle
migration, not an ordinary scheduled refresh.

Only Lost Fleet is collected. Each refresh checks two newest pages, then resumes
its historical queue using `endedAt` plus `_id`, with bounded downloads, pacing,
retries and persistent checkpoints. Cursor exhaustion does not prove every export
was accepted. LF still rejects unknown/conflicting rulesets, solo/Automa,
cancelled, incomplete/dropped games and unreconciled VP ledgers. See
[CURSOR_DISCOVERY.md](docs/CURSOR_DISCOVERY.md).

Data lives outside Git under `/var/lib/gaia-stats`. A release uses one immutable
`base.sqlite`, shared by hardlink with later LF-only releases, plus a small
`lost-fleet.json` index. Each processed LF game is stored once by content hash;
new generations reuse unchanged objects. Only new/changed LF exports are
normalized, unless a normalization, score or eligibility version changes.
An unchanged scan or a base-archive-only change creates no release.

One atomic `current.json` pointer selects both modes. Publication validates every
referenced object and preserves LF identities except verified exclusions. Old
inline LF releases remain readable. The static-base transition records which
base observations remain only in the preserved old release, rather than deleting
them. Requests pin a generation and fail closed on corrupt/missing data. See
[STORAGE_V2.md](docs/STORAGE_V2.md) for the storage model, review and rollback plan.

Failures normally retain the last good release. A historical-listing HTTP 400
can still permit independently validated queued exports to publish after clean
head scans and no export retries. That refresh remains explicitly **degraded**,
retains the last fully successful refresh time, and exits unsuccessfully. An
unchanged-data no-op does not advance publication time. No error is treated as
end-of-history. Details: [BACKFILL_FAILURE.md](docs/BACKFILL_FAILURE.md).

## Deployment and operations

The current VPS runs Nginx → Gunicorn under a restricted `gaia-stats` service
account, with one worker/four threads and an external release store. Expensive
cohort work is serialized across generations and base calculations process bounded
complete-game batches. Two separate systemd timers have different jobs:

| Timer | Purpose | Schedule |
|---|---|---|
| `gaia-stats-update.timer` | Test and deploy clean fast-forward changes from GitHub main | Every two minutes |
| `gaia-stats-data-refresh.timer` | Discover/download public games and publish validated data | 15 minutes after completion, plus up to two minutes jitter |

Refresh runs as the app account, with a lock, 720-second process deadline,
13-minute service timeout, 512 MiB memory ceiling, and at most 100 export attempts
per run for Lost Fleet. Code updates run tests as the app account, restart, and verify
the expected code SHA, rebuilt root, Plotly asset and both modes through Gunicorn
and Nginx. Unchanged-code polls also verify health. Degraded archive freshness
alone does not cause healthy app code to roll back.

For a **new VPS**, cloning this repository is not sufficient to reproduce the
current application. Review [REBUILT_RELEASE.md](docs/REBUILT_RELEASE.md): provision
the service, historical CSV seed/database, classic cache including Plotly, raw
archive, external release store and rebuilt service override; validate access as
`gaia-stats`, publish a checked generation, and verify both endpoints before
enabling timers. Do not run VPS bootstrap commands in a development checkout.

`deploy/install-vps.sh` is the older fresh-Ubuntu bootstrap. It configures Nginx,
UFW and the legacy sample-data service; it does **not** perform the rebuilt-data
migration or enable both timers. Review its changes before using it, especially
on a shared server, and do not rerun it over the current deployment.
`deploy/enable-updates.sh` bootstraps the **code** timer after tests/restart/health
verification; it does not install the data-refresh timer. Both are already
configured on the current VPS, not automatically on every new installation.

Inspect the current server without changing it:

```sh
systemctl status gaia-stats --no-pager
systemctl list-timers --all gaia-stats-update.timer gaia-stats-data-refresh.timer --no-pager
journalctl -u gaia-stats-update -u gaia-stats-data-refresh -n 80 --no-pager
curl -fsS http://127.0.0.1/healthz
curl -fsS 'http://127.0.0.1/cohort/api/stats?ruleset=base&plot=point-sources'
curl -fsS 'http://127.0.0.1/cohort/api/stats?ruleset=lost-fleet&lf_2p_4qic_mode=include-both&plot=point-sources'
```

Use sudo for service/log access if required. Rebuilt health exposes the running
code SHA, data release, counts and refresh details. Code-updater results are stored
separately in `/var/lib/gaia-stats/deploy-status.json` and its journal.

Commits to main are deployment actions while polling is enabled. Limit repository
write access accordingly. Pause relevant timers and wait for active jobs before
manual maintenance. Code rollback is best effort: old dependencies are reinstalled
into the shared virtual environment, not restored from an exact environment
snapshot. Restart deployment can cause brief downtime. Repeated broken targets
can be retried by the timer. Data-only rollback selects a validated prior release;
retain newer archives rather than restoring an old backup over them. Follow the
scoped rollback procedure in [REBUILT_RELEASE.md](docs/REBUILT_RELEASE.md).

**Operational gaps:** no verified off-server backup/restore process is established.
The incremental store bounds growth to new/changed LF game objects plus small
release metadata; historical full-copy generations are not removed automatically.
Inspect exact redundancy and preserve the archive and required rollback artifacts
before any separately approved cleanup. The disk guard fails closed. Local
snapshots and persistent storage are not off-server backups. The public app is read-only over
HTTP; provision HTTPS before introducing credentials or private features.

## Development and historical compatibility

Use Python 3.12 and the current web/test dependency set:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-web.txt
.venv/bin/python -m unittest discover -s tests -v
node --test tests/frontend/tables.test.cjs
```

The historical `requirements.txt` belongs to the original notebooks; it is not
the current web deployment environment. Tests use reduced public fixtures, not
the production archive. Local serving of the rebuilt interface needs the seed,
LF dataset/release and Plotly cache described in the release procedure.
`GAIA_RELEASE_ROOT` selects the atomic release store; `GAIA_CLASSIC_CACHE` selects
the separately generated compatibility assets.

`/classic/`, the original notebooks and legacy routes remain for historical and
compatibility work. Cached plots/aggregates can use older, explicitly labelled
methods and do not follow the live cohort filters. Original notebook methodology
is available explicitly through the plotting adapter; current cohort views use
the corrected definitions above. Some older milestone documents describe earlier
local-only stages; they are not current deployment-status reports.

The original notebooks cover name scraping (`fetch_names.ipynb`), JSON fetching
and parsing (`fetch_jsons.ipynb`, `parse_jsons.ipynb`), basic/advanced technology,
round-one structures, round/final scoring and VP sources. `texting_app.ipynb`
contains the original SMS example; SMS is not configured in this deployment.
The legacy opening explorer, fixture-seeding commands, `deploy/pull-games.sh`
and `render.yaml` target the older single-JSON application. They are not the
current release-store update path or a turnkey equivalent of the rebuilt VPS.

## Attribution and rules

Timothy Gladyshev's [bgs_data_gaia](https://github.com/TimGladyshev/bgs_data_gaia)
provides the original notebooks, statistical work and historical base data.
The upstream README identifies that project as MIT-licensed. Preserve upstream
attribution when reusing its code. This does not establish a licence for every
asset on gpstats.dev, game artwork, rulebooks or third-party data.

Rules references: [official base rulebook](https://capstone-games.com/cdn/shop/files/Gaia-Project-Rules-CG.0609sm2_1.pdf?v=15399621975902927537)
and [official Lost Fleet rulebook](https://capstone-games.com/cdn/shop/files/GP_Exp_Rule_EN_V1_Web.pdf?v=6134275372584409409).
Game records come from [boardgamers.space](https://www.boardgamers.space/boardgame/gaia-project).
