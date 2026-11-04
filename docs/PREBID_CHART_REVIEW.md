# Pre-bid candidate chart review

Reviewed 4 November 2026 after the static-base/LF-incremental integration.
This is a bounded regression review, not a claim of full parity with Tim's
notebooks. Earlier chart integration documents describe their then-current
methodology; the pre-bid score and whole-game eligibility corrections supersede
those documents' references to net-score ranking.

## Fixed before rollout

- The corrected classic round-one chart had flattened the original hierarchy.
  It now retains faction → structure class → exact six-count opening, including
  Tim's class precedence. Every parent count and color is calculated from its
  eligible player observations, with pre-bid VP. No low-score quantile pruning
  or historical score formula is restored.
- The exact technology acquisition table inherited its plot's “Acquisition
  frequency” label for its mean-score column. It now distinguishes Acquisition
  rate from Mean pre-bid VP. Values, rates, chart data, and readable tile labels
  are unchanged. Round/final scoring keep their metric-specific VP headings.
- Retired faction-variant selectors and stale saved query filters are removed.
  Actual more-balanced-game exclusion remains enforced in data and backend
  eligibility, not dependent on a visible control.

## Independent checks

The full committed original four-player CSV produces 3,018 eligible games. Its
Terrans opening chart has 1,205 player observations. The repaired classic tree
has 36 nodes (one faction, six classes, 29 exact openings) and 35 parent links.
All 29 leaf counts and pre-bid means match the corrected flat chart exactly.
Root mean 153.8755186722 VP and every class mean match direct observation means.
The singleton mines opening with 101 VP is retained, confirming no old quantile
filter. Unknown structures remain unavailable rather than invented zero counts.

Fixtures compare the restored semantic hierarchy to the original notebook and
exercise unequal group sizes, score/bid correction, unknown structures, and
input immutability. Client regression checks both basic/advanced acquisition
headings, exact numeric values, displayed labels and unchanged response data.
Full integrated suites: 294 Python tests and 66 client/frontend tests passed.
An independent pass also ran 44 focused Python and all 32 cohort client tests.

## Existing differences requiring separate product review

These differences already exist on the preceding main `82f6c09`; the treemap
regression fix does not introduce them:

- Classic round/final heatmaps show raw win rates, while the dynamic comparison
  view provides faction-baseline differences. For example, the eligible Terrans
  Round 1 mine cell is 28.187919% observed wins versus a 28.091286% faction
  baseline, or +0.096633 percentage points in the dynamic comparison.
- Classic final scoring shows observed tile-pair VP rather than the dynamic
  all-faction pair-baseline difference. For Terrans gaia/planetType, raw pair VP
  is 18.847059 versus 18.036785 all-faction baseline, difference +0.810274 VP.
- Dynamic advanced-tech score remains 90 tile/location acquisition-only rows.
  It does not yet reproduce Tim's 15 tile rows with Taken, Not taken and faction
  mean comparisons. The corrected classic chart does retain its tile-level
  location/taken/not-taken/overall-mean comparisons.

Comparing identical prepared observations before and after the pre-bid
integration confirms the classic round/final matrices were unchanged. These
remaining presentation differences must not be described as completed parity.

## Production staging: classic download correction

The first production bundle for candidate `26955b4` was not activated. Its charts
and serving seed excluded dropped games, but classic downloadable CSVs/indexes
retained 194 additional dropped games (69 two-player, 32 three-player, 93
four-player). The initial gate checked the cache only against its own metadata,
so it missed this inconsistency. The source CSVs and raw archive were unchanged.

The corrected cache builds downloads, counts, indexes and charts from the same
complete-game frame. Source status parsing accepts only the seed importer’s
literal `False` dropped flags. Unknown/malformed status and incomplete scores
cannot become eligible through pandas coercion. Whole-game policy exclusion
records and seed import policy are unchanged; unknown seed auction provenance
still blocks activation rather than silently dropping source history.

The independently reviewed gate now requires exact per-player-count CSV game
identities against seed minus verified exclusions, rejects duplicates, missing
partitions and non-false dropped flags, and verifies SQLite identity columns
against observation payloads. Old ready markers do not bypass these checks.

Regression verification: the committed original four-player source now produces
exactly 3,018 games in seed, downloads and classic index (previous download
3,095). Synthetic 2/3/4-player cases test malformed and missing completion data.
Full corrected-candidate suites: 302 Python tests and 66 client/frontend tests.
Standalone guard suite: 226 Python tests. Independent guard review: 24 tests on
each branch, with no remaining blocker. Production needs a fresh staged bundle
and the strengthened installed guard before activation; retain the first bundle.
