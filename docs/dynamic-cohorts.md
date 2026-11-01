# Complete local cohort interface

The application now serves the shared base/Lost Fleet interface at `/` when
`GAIA_BASE_COHORT` is configured, and always at `/cohort/`. `/classic/` remains an
explicit historical/offline view. No production configuration has been changed.

## Run locally

```sh
python -m gaia_stats.base_cohort \
  --csv 2=/path/to/two_players_data.csv \
  --csv 3=/path/to/three_players_data.csv \
  --csv 4=/path/to/four_players_data.csv \
  --output /path/to/base-cohort.sqlite
GAIA_BASE_COHORT=/path/to/base-cohort.sqlite \
GAIA_DATASET=/path/to/lf-cohort.json \
GAIA_CLASSIC_CACHE=/path/to/classic-cache \
  gunicorn 'gaia_stats.wsgi:create_app()' --bind 127.0.0.1:8767 --workers 1 --threads 4
```

Use the previous `gaia_stats.cohort` offline command to build LF normalized data.
The current task-local server is at http://127.0.0.1:8767/ . Database, raw exports,
and generated cache stay outside Git. The SQLite import publishes by atomic replace.

## One selected cohort

Both modes support player count, faction, pregame player Elo, layout, faction variant,
six round tiles, two final tiles, and available advanced-tech positions. LF additionally
supports observed auction modes and standard-only (default), include-both, variant-only
for the two-player 4-QIC tech variant. Base auction metadata is unavailable and is not
invented. Missing historical balance variants remain `unknown`, not `standard`.

Mode-specific selections are stored in sessionStorage, restored on switching, and the
active mode is reflected in the URL. The same filter query feeds chart data, faction
summaries, regenerated round/final/advanced-tech comparison tables, and selected CSV.
Tables never read `dat.json` in this interface. Exact per-cell sample counts accompany
scoring means and advanced-tech acquisition means. Empty cohorts clear every output.

Separate links explicitly download **unfiltered historical wide CSVs** for 2/3/4 players.
The selected export is a normalized player-game CSV with the selected rows, setup,
variant, Elo, technologies, round-one structures and source VP contributions.

Base import:

| Players | Eligible games | Excluded games | Player records |
|---|---:|---:|---:|
| 2 | 15,992 | 305 | 31,984 |
| 3 | 3,622 | 223 | 10,866 |
| 4 | 8,990 | 1,036 | 35,960 |
| Total | 28,604 | 1,564 | 78,810 |

Eligibility requires every player explicitly not dropped and finite final scores.
Input hashes are recorded in SQLite metadata. Historical CSV scores are source results;
the raw gameplay ledger is not independently reverified during this import. All observed
technology acquisition flags in eligible rows were checked: no missing/nonboolean flags
across the three current CSVs. Unknown field values are not manufactured as known variants.

## Methods and judgments

All dynamic views use actual net final scores, symmetric ties, and one player-game
observation per record. Round-one treemaps use stored `buildings_r_1_*` counts. Point
source boxes use the signed stored VP fields plus research-track scoring. No historical
score or quantile cutoff is imposed on these two dynamic families: retaining their old
cutoffs would silently change the selected cohort. The separate cached historical views
retain their disclosed bid-restored behavior, as documented in statistical-corrections.md.

Technology frequency uses available player-game opportunities, which becomes games where
available when selecting a single faction. Acquisition score scatter plots show means by
tile/position. Base round/final heatmaps use VP earned from those scoring tiles; LF retains
its labelled mean-final-net-VP conditional heatmap. No causal or optimal-play claim is made.
The comparison tables describe actual matching records, not additive predictions.

Point-source distributions are summarized by exact inclusive quartiles and min/max
whiskers. Large raw sample arrays are omitted from the browser payload, keeping charts
small; selected CSV remains the route to individual observations. Every point-source
cell reports its observation count. Missing base source fields are unknown, whereas an
absent source in a reconciled LF ledger is an observed zero.

## Resource bounds and measurements

SQLite is opened read-only at request time; SQL column identifiers are fixed and filter
values are bound parameters. Filter names, player counts and value lengths are validated.
No request can choose a filesystem path. Base selection first applies indexed/simple
filters in SQL; setup matching then uses the shared cohort filter. No pandas/dataframe or
server-side Plotly generation occurs on a filtered HTTP request.

One worker serializes expensive cohort requests with a lock. It caches only JSON response
bytes, at most 8 entries, at most 16 MiB total, and at most 2 MiB per entry. It never caches
full selected rows or CSV exports. Cache keys include the data file version; imports
invalidate old results. Base requests default to one selected plot rather than all eight.

Measured on this Intel Mac using the full base snapshot (not a VPS guarantee):

| Request | Elapsed | Response | Process peak RSS |
|---|---:|---:|---:|
| All-base point sources, cold | 6.373 s | 17,603 bytes | 931.0 MiB |
| Same request, cached | <0.001 s | 17,603 bytes | 931.0 MiB cumulative |
| 2-player Terrans Elo >=200, structures | 0.052 s | 40,045 bytes | 931.0 MiB cumulative |
| All-base selected CSV | 6.050 s | 74,173,338 bytes | 1,132.6 MiB |

Recommend **one worker**, four threads, for the proposed 4 GB VPS initially. The lock is
per process, so multiplying workers multiplies the potential peak. Re-measure on staging
before rollout. SQLite file is about 159 MiB. Exports currently materialize the CSV body;
streaming export is a future optimization, not a prerequisite for this measured snapshot.

## Archive verification and remaining scope

Archive CLI supports the actual JSON-array envelope and `_id` identifiers, with legacy
`slug` compatibility and conflict rejection. Read-only validation of all 18 saved pages
found 179 unique valid IDs and 17 adjacent lookahead overlaps. A regression invokes the
actual collector with a saved 11-entry `_id`-only page, max_downloads=0, and confirms 11
correct queued identifiers. No network scan or bulk download was run. UI lookahead uses
count=11/skip+=10; collector uses its requested page size without a lookahead row and
persistent deduplication. Full LF archive collection remains the next stage.

Remaining gaps: base CSV does not contain complete modern option metadata; LF remains a
29-game sample; some LF special-action structures remain unavailable; friendly LF tile
labels/artwork and larger-data performance remain future work. Old `/classic/` comparison
pages are explicitly historical and separate; filtered cohort mode never falls back to
them. No main push, production import or deployment occurred.

## Completion evidence

98 tests pass, including actual `_id`-only collector queueing, API/CSV identity, bounded
cache eviction, injection-shaped inputs, invalid duplicate final tiles, LF observed-zero
scoring, default exclusion, and missing/empty cohorts. Browser QA exercised all eight
families in each mode, preserved independent filters across mode switches and reload,
and verified empty-to-nonempty chart recovery. No app console errors were observed.

Live HTTP checks matched sorted record-identity hashes between stats and CSV:
- Base 2p Terrans, Elo >=200, xshape, more-balanced: 16 records,
  `97e683a4084c607c1610c5e0c34e26ee28fda65f6ed7460fbb2760b70712412f`.
- LF 2p variant-only: 2 records,
  `b4ce14b4f6e5975684eab074fc5262a1bf1f32d3d8c0d26304bb459aeb310a3b`.
