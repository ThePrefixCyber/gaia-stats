# Local statistical-correctness pass

Subsequent milestone: [dynamic-cohorts.md](dynamic-cohorts.md) now implements the previously deferred live base filtering and regenerated comparison tables. This document records the earlier bounded stage.

`make_plot` now defaults to `methodology="corrected"`. The original notebook sources
are unchanged and remain available with explicit `methodology="historical"`; the old
frozen-digest tests now request that mode. This is a method change, not a replacement
of the eight chart families.

## Corrections

Six affected families (basic/advanced technology frequencies and score scatter plots,
round/final heatmaps) use one eligible player-game observation as the averaging unit.
The adapter requires every player in a game to have dropped=False, once per game.
It does not concatenate copies for each nondropped position.

All these figures use actual final net scores, stored directly in `pos_N_score` by
`parse_jsons.ipynb`, rather than adding bids back. The CSV position is only a storage
slot: the original parser sorts by score+abs(bid), then breaks ties in player order.
The corrected code recomputes competition rank from net score and assigns tied winners
1 / number-of-tied-winners. Reordering CSV positions therefore leaves results unchanged.

- Basic and advanced score means pool score sums/counts across rank slots and research
  positions, including the overall reference mean. Sample counts accompany each point.
  Nine observations scoring 100 and one scoring 200 produce 110, not 150.
- Advanced score plots no longer filter to score >=130. The score threshold survives
  only in explicit historical mode. Titles describe associations, not causal impact.
- Basic/advanced acquisition frequencies retain games-where-the-tile-was-available as
  denominator for the selected faction. Rank stacks use actual net-score competition
  rank. Absent availability yields null, observed available-but-never-taken yields 0.
  An empty taken or not-taken score group yields null, never an invented score of zero.
- Final heatmaps pool both tile orders and all storage positions, using the sum of the
  two actual final-scoring VP contributions per observation. A single 18+12 observation
  is 30, not divided by unobserved rank/order groups. Both symmetric matrix cells display
  that pair; this does not duplicate observations within either cell. Diagonal is empty.
- Round heatmaps pool actual VP earned from that round tile, with sample counts. The
  second heatmap shows symmetric shared wins. The former additive "optimal setup"
  annotation is removed: independently observed marginal means do not establish an
  attainable or causally optimal setup. The chart family remains a two-panel heatmap.
- Unseen factions yield an explicit no-observations figure instead of division by zero.

The two unaffected-by-this-audit families retain legacy calculations **with explicit
labels**: round-one treemap restores bids, requires all players' restored scores >=100,
and removes structure groups below the 15th percentile of group mean scores. Point-source
boxes restore bids and retain selected player's restored score >100. Their old rank
legend is relabelled "bid-restored order (ties broken by original player order)". These
views are not advertised as actual win rankings or an unfiltered cohort. Removing those
additional historical choices is deferred, rather than silently changing more metrics.

## Base Elo and comparison scope correction

The public 2/3/4-player CSVs have `pos_N_elo`. The original parser explicitly reads
`players[i].elo.initial`. They also contain net score, dropped flags, map layout,
`balance_variant`, round/final setup, technology acquisition and scoring contributions.
Therefore base cohort recalculation **is possible**. The earlier wording suggesting
otherwise was wrong and is corrected in the interface and milestone notes.

The corrected adapter supports `min_elo` for all six corrected plot families, excluding
missing Elo only when a cutoff is supplied. A real two-player CSV check verifies this path (the final report records the counts). The
web cache still serves an offline build without a live Elo selector. Wiring arbitrary
base-cohort choices through the cache/API and rebuilding comparison tables from CSV
would be a separate, larger integration step. The remaining two legacy families reject
a supplied Elo cutoff explicitly instead of silently ignoring it.

`dat.json` comparison tables remain clearly labelled published historical aggregates;
only the prior Gaia denominator fix applies. They are not recomputed/corrected simply
because the six charts are corrected. The original aggregate file lacks per-cell counts
for round/final tables, so its weighted means cannot be repaired from that file alone;
the source CSV must be used to regenerate those tables. CSV option fields do not match
the complete modern raw-export variant schema; no missing auction/variant metadata is
inferred. No base/LF pooling is introduced.

## Lost Fleet audit

LF chart means already use individual records via statistics.mean; they have no rank-cell
averaging or 130-point cutoff. VP ledger reconciliation, net-score ranks and symmetric
win_share are already correct. The complete-game gate rejects dropped/quit/incomplete
exports. LF final heatmaps deliberately show mean *final net score* conditional on the
pair, rather than the base heatmap's *VP earned from the final pair*, and are labelled
accordingly. This difference is retained and documented, not silently presented as the
same measure. LF tech frequencies explicitly use player-game opportunities when viewing
all factions; selecting one faction reduces to games where available. Sparse acquisition
means are null; reconciled absent VP-source contributions are observed zeros.

## Validation

Six new regression tests cover unequal rank-cell means, single/reversed final pairs,
position-invariant ties, complete+dropped games, unseen factions/empty denominators,
and net-score/Elo provenance. Historical parity tests still compare all eight original
figures against unchanged notebooks. Local cache regeneration and focused browser checks
verify the corrected plot families, labels, and sparse cohorts. No publication,
production mutation, or archive collection occurred in this pass.
