# Original notebook plotting adapter (local milestone)

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
was deserialized for this milestone. The two-/three-player pickles remain
untouched; those player counts are accepted for caller-supplied compatible
frames but not yet validated against the historical pickle datasets. The
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
SMS is explicitly unavailable and collects no information. Faction-comparison
tables remain explicitly unavailable until their source aggregate data is
imported and checked; no substitute formula is presented. Player counts without
an imported CSV are disabled rather than displaying four-player data as another
count. The root `/` and existing APIs/health retain their current behavior.

For this environment, gpstats.dev and capstone-games.com are absent from the
HTTP allowlist. Web-tool requests for original JS and official PDFs failed.
The remaining two-/three-player CSVs, current four-player CSV, dat.json, and
rulebooks require a supported transfer or approved environment configuration.
No proxy bypass, credentials, or production mutation is part of this work.
