# Faithful score-share and round-preference views

Sources: Tim's `scoring_methods.ipynb::make_corr_plots` and
`round_scoring.ipynb::make_round_scoring_heatmap` in
https://github.com/TimGladyshev/bgs_data_gaia .

## Point sources

Tim plots source contribution / bid-restored score as percentages, separately
by rank and faction. He combines six round tiles and two final tiles, drops
scores <=100 and reverses charging costs to positive values. Our previous
cohort view instead pooled absolute VP distributions.

The default now restores per-player percentages and separate finishing-rank
boxes. The denominator is **positive final net score**, not restored bids.
Ranks are actual net-score competition ranks: tied players retain the same
rank, rather than being separated by player order. Player counts are also
separate. Each observed ratio has equal weight; this is not a ratio of sums.
Round tiles and final tiles are combined, requiring all component values.
All other source IDs follow the dataset: canonical historical categories for
base, verbatim raw BGS IDs for Lost Fleet. No base category is inserted into a
Lost Fleet distribution. Thus `federation`, `spend`, and `initial` remain those
raw IDs; they are not accompanied by invented zero `fed`, `resource`, or `init`
series. Sources remain signed, including bid and charging costs, and starting
VP is shown. Therefore valid contributions in a reconciled complete ledger sum to
100% per player (category medians need not). A positive source can exceed 100%
when deductions reduce the denominator. No historical >100 cutoff is applied.
Nonpositive/nonfinite scores are excluded only from the percentage mode, with
an explicit exclusion count. Missing historical CSV sources remain unknown;
only complete-ledger absence implies zero. Unknown aggregate tiles remain
unknown even if other sources are complete. Counts are source-specific.

The prior absolute VP distributions remain accessible under Scoring view.
They preserve detailed individual round/final sources and selected filters.
The faction filter applies to either view; All factions is explicitly a pooled
rank distribution rather than a faction-strength estimate. Quartiles use the
existing inclusive definition, and whiskers show observed min/max.

## Round scoring

The default requires a faction. Its first panel retains observed VP earned
from each tile in each round. Its second shows the selected faction's shared
win rate in that cell minus its overall shared win rate, in percentage points.
Player counts are separated, never averaged into a single comparison cell.

The baseline removes **only round1–round6 setup filters**, while preserving
faction, ruleset, player count, final-tile filters, technology, Elo and all other
settings. This avoids forcing a zero difference merely by selecting the same
round tile being compared. The selected observations, totals, CSV and other
charts still honor every filter. The baseline counts every eligible player-game
once, not six times. Each k-way tie for first receives 1/k win credit.
Missing tile VP reduces its own denominator, not the win denominator.

Both absolute win rates and reference rates/counts appear in tooltips and the
exact table. The previous raw VP/win heatmaps remain an explicit alternate,
with a warning that pooled all-player rates are mechanically fixed by player
count. No predicted optimal combination is fabricated by adding marginal means.

## Verification

`tests/test_scoring_views.py` covers signed ratios, low/zero scores, ranks,
player counts, aggregate tiles, unknowns, complete-ledger zeros, late sources,
real-export ratios, baseline relaxation, retained settings, ties and streaming.
Existing streaming parity tests also compare the extra distributions.
`tests/client/cohort.test.cjs` covers mode switching and retained raw views.
`tests/browser/scoring_views.cjs` is an actual Plotly check for rank boxes,
round differences, denominator tooltips, repeated mode switches and mobile.

These are observed associations, not causal effects or adjusted estimates of
faction strength. Small or selectively missing samples remain a limitation.
