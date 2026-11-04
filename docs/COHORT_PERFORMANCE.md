# Cohort response and rendering performance

## What changed

- Setup comparisons visit each player observation once, looking up each scoring
  contribution once and each acquired technology slot once. The statistical
  formulas, missing-value handling and duplicate-acquisition semantics are unchanged.
- Warm server responses and the static interface no longer wait for an unrelated
  cold calculation. A separate small lock protects the response LRU; expensive
  cache misses remain serialized, including across release changes. Cache entries
  are still bounded to eight responses / 16 MiB, with a 2 MiB individual limit.
- Metadata and statistics requests start while Plotly downloads. Exact tables are
  usable before the plotting library is ready, and remain usable if it fails.
- The browser reuses recent chart responses for the same cohort for at most 60
  seconds, with a maximum of eight entries. Applying filters or changing mode
  clears this cache. Technology frequency/score pairs share identical observations,
  so viewing all eight charts needs six stats requests rather than eight.
- Superseded fetches are aborted and late responses ignored. Repeated Apply clicks
  for a pending identical request do not queue duplicate calculations. Aborting a
  browser fetch does **not** guarantee cancellation of server work already running.
- Plotly updates its existing graph with `react`, heatmap cells use indexed lookups,
  and unchanged comparison tables are preserved when only the chart changes.
- While updating, prior results stay visible with explicit loading status; CSV is
  disabled until the new result arrives. No background prefetch workload is added.

## Measurements

Baseline: `868b3f7a0d48dcd4abdcf3d8c3784a5ce6a75696`.

The repository's real `data/remote_four_players_data.csv` produced 4,859 eligible
four-player games / 19,436 player-game observations (828 dropped/ineligible games
were rejected by the existing importer). CSV SHA-256:
`32d360bcc0e4896bba27ff6e936530274d18759abd33b2fcfac133b533e35432`.

Five alternating before/after runs per plot, Python 3.12, uncached API computation
with warm filesystem cache on the same shared runner, 2026-11-04:

| Plot | Before median | After median | Reduction |
|---|---:|---:|---:|
| Advanced technology frequency | 1.274 s | 1.158 s | 9.1% |
| Point sources | 1.475 s | 1.355 s | 8.1% |
| Round scoring | 1.525 s | 1.399 s | 8.3% |

All before/after response bytes were identical. Raw trials are retained in
[performance-benchmark.json](performance-benchmark.json). The script swaps only
setup traversal, isolating its effect. Timings are environment-specific and are
not a production latency promise. The production archive is larger and includes
raw exports absent from this historical CSV benchmark.

A baseline cProfile run attributed about 32% of cumulative response CPU time to
setup comparisons and 18% to JSON decoding. This patch reduces repeated traversal;
it does not eliminate the cost of decoding and scanning the selected cohort.

## Reproduce

```sh
python -m gaia_stats.base_cohort \
  --csv 4=data/remote_four_players_data.csv --output /tmp/gaia-base.sqlite
python tools/benchmark_cohort.py /tmp/gaia-base.sqlite --repeats 5
python -m unittest discover -s tests -v
npm ci --ignore-scripts
npm run test:client
node --check web/cohort/app.js
```

Node/jsdom is development-only; production remains Python plus static JavaScript.
`PYTHON` may select the Python interpreter used by client test fixtures.

Validation on this branch:

- 156 Python tests passed, including exact setup parity, duplicate technology
  observations, both rulesets, cached response concurrency, and static asset
  isolation from the calculation lock.
- Eight jsdom tests passed: delayed/failed Plotly, all chart types, paired/revisited
  cache reuse, expiry and Apply refresh, mode changes, duplicate requests, stale
  responses, API-error recovery, interrupted catalog round trips preserving saved
  filters, and failed-catalog retry. Plotly itself is mocked in these tests.
- Real cloud-browser smoke checks against a managed local preview rendered all
  eight Plotly chart families, a cached technology switch, empty-filter results,
  recovery into Lost Fleet and its heatmap. No application console error appeared.
- The optional `tests/browser/test_cohort_client.py` is provided for a normal
  Playwright/Chromium environment. Its standalone browser process could not start
  in this container because process sockets are restricted, even with escalation;
  it is **not** included in the passing test count. The managed preview provided
  the actual-browser checks instead.

No live data, deployed code, release pointers, timers or production settings were
changed. The cache can show a response up to 60 seconds old during chart browsing;
Apply always requests fresh data unless that exact request is already in flight.

## Integration

This branch starts from the baseline independently of table styling/sorting and
tile naming work. Preserve the performance request lifecycle and `renderResult`
wrapper when applying table changes; place the table worker's raw-numeric setup
rendering inside that wrapper. Keep its `tables.js` before `app.js`. Plotly is now
loaded by `app.js`, so do not restore the old blocking Plotly script in HTML.
The early WSGI static allowlist already includes `tables.js` and `styles.css` so
those companion assets also avoid the calculation lock when their routes exist.

## Integration verification (2026-11-04)

The reviewed performance tree is integrated on top of the readable-table,
tile-label and corrected final-scoring work. The interrupted-catalog
`loadedMode` guard remains intact. Comparison tables receive raw numeric values
and preserve sort state; final-scoring means and observed baselines are unchanged.
Plotly loads asynchronously and updates through `react`. Both scoring heatmaps
use keyed cell lookup. Only the mean-net-VP treemap adopts the separately
reviewed grey-zero / darkest-blue-observed-maximum scale.

Integration checks: 172 Python tests; 26 Node tests (8 client, 11 table, 7 color);
25 tile-helper assertions; 7 actual Chromium/Plotly client tests; dedicated
final-scoring desktop/mobile checks; and the eight-mode smoke test. The actual
rendered treemap includes the expected darkest-blue SVG fill. Browser tests use
fixture responses, not production data. Earlier benchmark figures above belong
to the original performance experiment and are not new production timings.
