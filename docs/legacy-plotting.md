# Original notebook plotting adapter (local milestone)

Current default methodology is corrected for six plot families; see [statistical-corrections.md](statistical-corrections.md). The original-formula descriptions below document explicit `methodology="historical"` compatibility mode, not the default corrected cache.

`gaia_stats.legacy_plots` exposes the six original base-game plot families as eight
Plotly views. The plotting implementation is only used during offline generation, never in
HTTP requests. An opt-in cache-serving preview is described below; production
data and the existing root page remain unchanged. It uses the six unchanged notebooks from
[Tim's upstream commit 1c4cf35](https://github.com/TimGladyshev/bgs_data_gaia/tree/1c4cf35fa3599ed3d29ac9f7f36cfb5d0484261e).

```bash
python -m venv .venv-plots
.venv-plots/bin/pip install -r requirements-plotting.txt
.venv-plots/bin/python -m unittest discover -s tests/plotting -v
```

```python
from gaia_stats.legacy_plots import load_historical_csv, make_plot, PLOTS

data = load_historical_csv()
figure = make_plot('basic-tech-frequency', data, players=4, faction='terrans')
# Caller-controlled export, never automatic:
figure.write_html('/tmp/terrans-basic-tech.html', include_plotlyjs=True)
```

The adapter reads notebook JSON and loads literal constants and function
definitions only. It never executes notebook-level imports, pickle reads, file
writes, figure calls, global warning filters or pandas display configuration.
The only function-body transformation replaces `fig.show()` with figure capture.
One explicit faction is selected per call and the input dataframe is copied.
The notebook definitions are trusted repository code, not a sandbox for uploaded
notebooks. Missing columns, mismatched player counts and unsupported factions
fail explicitly. Some sparse subsets remain unsupported by the original
calculations; division/index errors are reported rather than filling in zeros.

## Historical data and parity

The default CSV has 5,687 rows and 489 columns and supports all eight views.
It is `data/remote_four_players_data.csv`, not the absent filename
`data/four_players_data.csv` used by the separate exploratory workbook. No pickle
was deserialized for this milestone. The two-/three-player pickles remain untouched. Public CSV exports for all
three counts have now been imported and all 336 faction/count/view combinations
built locally; see the integration milestone below. The
explorer's normalized JSON is a different schema and is not silently converted.

`tests/plotting/legacy_baseline.json` fixes the source notebook/CSV SHA-256 values
and full Terrans Plotly output digests produced by executing the original,
unmodified function bodies on that CSV. Tests also compare all eight adapted
Xenos figures against unmodified functions at runtime, independently check basic
technology denominators and bid-adjusted point-source arithmetic, assert input
preservation, and prohibit implicit pickle/CSV loading or browser display.
Plotting packages are pinned separately and included by requirements-web.txt so
the normal deployment gate runs these regressions rather than silently skipping
them. The suite is collected by `python -m unittest discover -s tests`.

Original conventions deliberately retained:

- Existing `pos_1`…`pos_N` rank columns are used as supplied. Tim's parser ranks
  score plus absolute bid and resolves ties by player order; the adapter does
  not rerank games using the new explorer's net-score/shared-win convention.
- Basic/advanced technology frequency plots exclude games with any dropped
  player. Score plots add absolute bids; advanced technology score cohorts use
  a score threshold of **at least 130**, even though the original title says
  `score > 130`. Several averages weight rank/track means equally, not by sample
  count. These formulas and titles are unchanged.
- Round-one structures exclude dropped players and require every player's
  bid-adjusted score to be at least 100. Groups below the 15th percentile of
  grouped average score are removed. These are structure-count treemaps, not
  the replacement explorer's ordered build sequences.
- Round scoring concatenates separately filtered per-position frames. This
  duplicates games and can retain a game with another dropped player. The
  original matrix calculation and scoring-combination search are preserved.
- Final scoring keeps the original pairwise heatmaps, per-rank averaging and
  baseline victory calculation; empty matrix cells retain their original values.
- Point-source plots use bid-adjusted scores strictly above 100, combine round
  and final sources, invert charging VP cost, and retain the original source list.
- Original pandas copy warnings and Plotly `append_trace` deprecations can appear.
  The adapter does not globally suppress warnings or rewrite these calculations.

This milestone makes no Lost Fleet rules or payload-ID assumptions. Extending
these functions and reconciling the live frontend are separate work. Base-rule
and Lost Fleet rulebook review must not silently change historical base parity.


## Local cached frontend integration

Build a complete snapshot sequentially, outside request handling:

```bash
python -m gaia_stats.legacy_cache --cache /tmp/gaia-classic \
  --csv 4=data/remote_four_players_data.csv
# Add --csv 2=/path/two_players_data.csv --csv 3=/path/three_players_data.csv
# when those CSVs have been retrieved and verified.
GAIA_CLASSIC_CACHE=/tmp/gaia-classic GAIA_DATASET=/tmp/gaia-analysis.json \
  gunicorn 'gaia_stats.wsgi:create_app()' --bind 127.0.0.1:8765
# Preview at http://127.0.0.1:8765/classic/
```

Generation holds one dataframe and one figure at a time. It writes a new build
folder and publishes an atomic current.json pointer only after all plots succeed.
Failure removes the incomplete build and preserves the prior snapshot. Old
snapshots remain for manual recovery/removal. Requests only read cached files;
they never load pandas datasets or generate figures. Snapshot CSVs are copied
unchanged and their SHA-256 values are recorded in the catalog. Plot downloads
embed Plotly for standalone use; browser views share one local Plotly asset.

The preview recreates the centered selectors, eight original chart choices,
New Tab/Here/Download actions, CSV dialog, and plot wrapper with explanations,
Fullscreen/Download/Copy Embed Link. Original chart/CSV/wrapper paths also resolve
locally when the cache is configured. It uses original frontend code written for
this project, not copied site artwork, donation forms or third-party widgets.
SMS is explicitly unavailable and collects no information. Faction-comparison tables are enabled only when the original aggregate data
is supplied with `--comparisons`; absent data is explicitly unavailable. Player counts without
an imported CSV are disabled rather than displaying four-player data as another
count. The root `/` and existing APIs/health retain their current behavior.

## Public historical CSV and setup-comparison integration

The Mac-local integration uses the original public CSVs without converting or
re-ranking their player records. The 2026-11-01 snapshot contains:

| CSV | Games | Columns | SHA-256 |
| --- | ---: | ---: | --- |
| two_players_data.csv | 16,297 | 255 | 4d8a758d02f24fb197bb8763d8dd93ab1113c36413547c56532cca6b9b4b7f81 |
| three_players_data.csv | 3,845 | 363 | a6e9e70d33bc23111efc176e410fef6ff008c4e13b6d267b35aa98e3913f5795 |
| four_players_data.csv | 10,026 | 471 | b53ffd1d7ffed4c2d6cea379dd5565ecc7407c04617d95e10a78ad4c910cc2f5 |

Sources are `https://gpstats.dev/data/` plus each filename. The newer four-player
CSV has the same analysis fields as the old committed CSV; the 18 removed
columns are redundant serialized indices. No missing gameplay columns are
filled with invented values. Each CSV is served/downloaded byte-for-byte and
its row count, column count and hash are recorded in the cache manifest.

The comparison source is `https://gpstats.dev/dat.json`, SHA-256
`5cf7b816a4f6a7fe46368f2547057fdba90e998bbdbd8542305b7364c938dcb1`.
It is a separate published aggregate snapshot, not recomputed or falsely claimed
to be filtered from the imported CSVs. Its source hash and available counts are
recorded alongside the CSV manifest. Source files and generated caches remain
outside the source checkout.

```bash
python -m gaia_stats.legacy_cache --cache /path/to/classic-cache \
  --csv 2=/path/to/two_players_data.csv \
  --csv 3=/path/to/three_players_data.csv \
  --csv 4=/path/to/four_players_data.csv \
  --comparisons /path/to/dat.json
```

The Who should I play? control now opens player count, six round tiles, six
advanced-tech positions and two final tiles. Legal selections navigate to
`/classic/compare`; the original `/view_tables/index.html` route also works.
The read-only `/classic/api/comparison` consumes the same original query fields.
Results show sortable round, final and advanced-tech tables; faction links open
the corresponding cached chart. The frontend is new code implementing the
observed contract, not copied original JavaScript.

Judgment calls:

- Round means are summed and probability/delta values averaged exactly as the
  original aggregate consumer did. They are explicitly labelled marginal
  historical descriptions, not joint predictions for the chosen setup.
- Advanced-tech weights are `count / (count + missed)` for every track. This
  fixes the original Gaia-only multiplication-denominator typo. The values are
  labelled descriptive indices, not expected total scores or causal effects.
- Missing/nonfinite cells display an em dash, not zero. Zero-count tech cells
  are unobserved. Maxima use observed tracks only and the weighted sum requires
  all six tracks. Valid observed zero point/probability values remain zero.
- Round/final aggregates have no sample-count metadata; their true zero cannot
  be distinguished from an upstream empty-cell sentinel. We retain finite values
  and disclose the absence of counts rather than inventing evidence thresholds.
- All 14 base factions and all eight notebook views remain available. Original
  plotting regressions and notebook files remain unchanged. No expansion plots,
  archive jobs, root-page replacement, or production changes are included.

Python 3.11 works with the pinned dependencies. On macOS, updater tests need a
local `flock -n FD` compatible executable; the development run used a task-local
Python/fcntl helper and a task-local `mktemp` wrapper on PATH, with
`TMPDIR=/tmp`, without global installation. The wrapper ensures the existing
Linux-specific verifier-path assertions use `/tmp` on macOS.
HTTP tests require permission to bind loopback. Baseline suite has 70 tests when
its HTTP test class can start; added comparison tests run in the same discovery.
