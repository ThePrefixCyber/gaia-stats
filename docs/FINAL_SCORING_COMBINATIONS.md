# Final-scoring comparisons: faction conditioning and explicit baselines

The previous default pooled all selected players by final-tile pair. In a
complete four-player game, shared win credits sum to one, so every pair averages
25% wins. Two final objectives ordinarily distribute 72 VP, averaging 18 VP
per player. These pooled constants are not evidence that tile pairs are equally
suited to each faction. Elo filtering, missing VP records, and two-player neutral
scoring can alter the pooled figures; no fixed 18 or 25 is used in this fix.

The original `final_scorings_deltas.ipynb` explicitly iterates over factions. Its
heatmap colors compare faction scoring against all factions on the same pair,
and pair-specific faction wins against that faction's overall win share. Its
VP calculation sums position/orientation means then divides by fixed constants;
that is not observation weighting and behaves poorly with uneven samples. We
retain the comparison question, not that averaging method or its bid-restored
winner convention.

## Current behavior

Select a faction to display the chart. With All / any faction, the chart explains
why a faction is needed instead of rendering pooled constants. Each row is an
unordered final-tile pair **and a player count**. Two-, three-, and four-player
observations are never combined in a comparison cell.

For the selected faction F, tile pair P, and player count N:

- Left: mean VP earned from both final tiles by F on P, minus the mean of all
  eligible factions on P. Both means use only observations with both tile VP
  values known. The all-faction baseline includes F.
- Right: mean shared win credit of F on P, minus mean shared win credit of F
  across all eligible pairs, displayed in **percentage points**. A sole winner
  contributes 1; k tied net-score winners each contribute 1/k. Nonwinners
  contribute 0.

Both reference cohorts preserve ruleset, player count, player Elo cutoff, layout,
auction, faction variant, two-player 4-QIC mode, round setup, and technology setup.
For reference data only, the faction constraint is removed; both final-tile
constraints are relaxed. Pair grouping reimposes the same pair for the VP
baseline; faction grouping reimposes F for the win baseline. Thus selecting a
final pair does not automatically force the win difference to zero. Other active
settings may still legitimately leave only one observed pair; its win difference
is then zero and its baseline sample size is shown.

Tooltips and exact-observation tables retain absolute means, both baselines,
both differences, game counts, player-observation counts, valid tile-VP counts,
and baseline counts. Unknown VP stays unknown; it does not reduce the win
sample or become zero. Missing pairs remain blank. Elo is an individual-player
filter and can leave partial tables. Small-sample differences describe the
observed cohort; they are neither confidence estimates nor causal effects.

The selected cohort totals, faction tables, all other plots and CSV continue to
honor all user filters. Only the explicitly documented reference cohorts relax
faction/final-tile constraints. SQLite reads retain all factions for this chart;
complete-game batches merge scalar summaries before computing baselines and
differences. No archive data, imports, identities or backfill checkpoints change.

## Checks

Regression tests cover deterministic four-player prize-pool constants, reversed
pair ordering, fractional ties, unequal baseline sizes, missing VP, player-count
separation, Elo/settings filters, final-pair baseline relaxation, no-data and
all-faction states, and streaming batches containing only reference opponents.
A SQLite route test checks other factions are actually read for the baseline
while CSV remains selected. Existing real-export scoring tests now verify the
per-faction observations instead of asserting the misleading pooled constant.

Optional actual-Plotly check:

```sh
PYTHON=python node tests/browser/final_scoring.cjs
```

This uses local fixture-derived responses and installed Playwright/Chromium,
asserts both rendered heatmap values and denominators, and writes a screenshot
to `/tmp/gaia-final-scoring.png`. No external game service is contacted.
