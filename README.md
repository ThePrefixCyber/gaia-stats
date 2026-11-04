# Gaia Stats

Gaia Project statistics for the base game and Lost Fleet, extending
[Timothy Gladyshev's original project](https://github.com/TimGladyshev/bgs_data_gaia)
and the chart families shown at [gpstats.dev](https://gpstats.dev).
The current application uses a new shared interface with corrected statistics;
it does not claim pixel-perfect reproduction of Tim's site.

The public deployment is [http://45.76.250.100](http://45.76.250.100).
As of **2026-11-02 09:22 UTC**, the rebuilt application, GitHub-polling code
updates and scheduled cursor-based archive refresh were verified running.
Historical base-game backfill is still incomplete. Use `/healthz` for current
release counts, discovery checkpoints and refresh status rather than treating
this README as a live inventory. HTTPS and off-server backups are not established.

## Current statistics and filters

The root page offers independent base/Lost Fleet modes, 2/3/4-player selection,
observed factions (including the four new LF factions), minimum individual pregame
Elo, layout, auction and faction-variant filters, plus round/final scoring and
available advanced-tech selections. Options depend on the selected dataset;
missing historical metadata remains unknown. Missing Elo is included without a
cutoff and excluded when a numeric minimum is set. Mode selections are remembered
within the browser session.

The significant two-player LF **4-QIC → technology** variant has three choices:
**standard only** (default), **both**, and **variant only**. Classification uses
explicit BGS option metadata, not faction names. The default excludes that
variant; it does not remove ordinary three- and four-player LF games.

All eight chart views use the same selected cohort as the faction comparisons,
round/final/advanced-tech tables and selected player-game CSV:

- Basic and advanced technology acquisition frequencies and mean-score plots.
- Round-one structure treemap.
- Round and final scoring heatmaps, alongside shared-win heatmaps.
- Signed VP-source distributions with exact quartiles and min/max whiskers.

Sample counts and unavailable observations are shown. Empty selections produce
no-data results rather than invented zero scores. All current cohort table columns
can be sorted using their heading buttons (click, Enter or Space). A second
activation reverses direction; missing measurements stay last. Each table keeps
its sort when filters refresh. Percentages, VP and sample counts are formatted
for readability; numeric sorts use the unrounded values. Separate historical wide-CSV
links are explicitly **unfiltered** and do not reflect current selections.

Current views use one player-game observation, actual final net VP, competition
ranks and shared credit for tied wins. Auction bids are not added back to rank
players. Round/final heatmaps show VP earned from the tile or final tile pair in
**both** modes; conditional final score is separately labelled. Technology
frequency denominators are observed available player-game opportunities.

Raw VP totals reconcile against final scores including the initial 10 points.
Only verified complete ledgers imply zeros for missing scoring events; historical
CSV blanks remain unknown. Base raw source categories are phase-aware, LF source
names retain expansion contributions, and original raw totals remain available.
Tile-VP denominators exclude unavailable measurements. See
[SCORING_V2.md](docs/SCORING_V2.md) for these definitions and evidence.
These are descriptive associations, not causal strategy recommendations or
skill-adjusted predictions; repeated players contribute repeated observations.

## Data collection and publication

Production combines an eligible historical base CSV seed with accepted public
BGS raw exports. Matching raw game IDs replace seed observations rather than
being appended twice. LF is maintained separately. The raw importer rejects
unknown/conflicting rulesets, solo/Automa, cancelled, incomplete or dropped games,
and unreconciled VP ledgers. Historical CSV eligibility and provenance are distinct
from raw-ledger verification: CSV scores are source results, not freshly verified
raw logs.

The collector uses the deployed ended-game cursor contract, `endedAt` plus `_id`,
with one-row lookahead. Cursor migration starts at the head and deduplicates the
existing queue; it preserves old offset checkpoints and raw provenance. Queue
entries and cursor advancement commit together. Each refresh checks two newest
pages first, then resumes historical discovery, with paced requests, bounded
retries, persistent cooldowns and a resumable download queue. Head downloads
receive priority over the historical backlog. See
[CURSOR_DISCOVERY.md](docs/CURSOR_DISCOVERY.md) for protocol evidence and limits.

Cursor exhaustion means that listing traversal reached its end, **not** that all
queued exports were accepted or that universal historical coverage is proven.
API changes, rejected games, missing metadata and concurrent listing changes
remain relevant. Neither a successful refresh nor a historical CSV seed means
base backfill is complete.

Data lives outside Git under `/var/lib/gaia-stats`. Immutable release directories
hold `base.sqlite`, `lost-fleet.json` and hash/count manifests. One atomic
`current.json` pointer selects both modes together. Publication validates the
candidate and preserves prior player-game identities; requests pin one generation
and cached results are replaced on a generation change. Missing/corrupt serving
data fails closed rather than seeding examples.

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
per mode per run. Code updates run tests as the app account, restart, and verify
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

**Operational gaps:** no automatic release retention policy or verified off-server
backup/restore process is established. Changed generations consume additional disk;
the publication disk guard fails closed, but is not a retention policy or a limit
on raw-archive growth. Monitor disk use and refresh freshness. Local snapshots and
persistent storage are not off-server backups. The public app is read-only over
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
