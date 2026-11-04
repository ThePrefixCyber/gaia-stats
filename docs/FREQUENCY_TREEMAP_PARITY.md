# Frequency and opening-tree parity

This restores the chart structures in Tim Gladyshev's original notebooks while retaining the corrected cohort, net-score, competition-rank, and shared-win calculations.

## Tile frequency

The default basic and advanced frequency view has one stacked bar per tile. A tile is available at most once per selected player-game, irrespective of its setup position. An acquisition is counted at most once, including duplicate or covered ownership records. Known aliases in the verified tile registry are canonicalized only for this aggregate view; unknown identifiers remain distinct and raw records are unchanged.

The rank stack is `rank acquisition count / available player-games`. Hover shows:

- `P(rank | taken)`: rank acquisition count / all acquisitions of this tile.
- `P(taken and rank | available)`: rank acquisition count / observed availability.
- The selected faction's overall rank rate, or the selected cohort's rate when no faction is selected.

Unknown ownership is excluded from both availability and acquisition counts. Acquisitions without matching setup evidence are reported separately and do not create an availability denominator. The baseline includes all selected player-game observations, so the note advises choosing a player count for comparable ranks. This preserves Tim's advanced-tile availability conditioning and basic-tile denominator on complete original datasets, while supporting partial Lost Fleet observations without inventing data.

The optional **By tile and position** view retains the existing raw position cells. Its preference is remembered per ruleset, and changing it draws from the existing response without a network request. Raw category keys remain distinct from human-readable display labels.

## Exact opening hierarchy

Tim's `r1_structs.ipynb` creates a three-level tree:

1. Overall root.
2. Structure class.
3. Full configuration, in exact order: mines, trading stations, research labs, planetary institute, academy 1, academy 2.

The class assignment precedence is **ac2, ac1, PI, lab, ts, m**, reflecting the original notebook's successive overrides. It is not a nested level for every building type. The six-count leaf format is `2-m_0-ts_0-lab_1-pi_0-ac1_0-ac2`.

Sparse raw reconstruction counts and complete historical CSV counts are normalized into the same exact leaf. Explicit unknown, invalid, fractional, or negative counts are unavailable, not zero. Parent values are sums of their leaves (`branchvalues: total`). Parent score means are weighted by player observations; parent Elo means use only measured ratings and their actual counts. Thus the root/class colors cannot become an unweighted mean of strategy means. Hover labels counts as player observations rather than distinct games.

The historical notebook's score cutoff, low-frequency trimming, and auction-bid add-back are intentionally not restored. All valid selected observations and corrected final net VP remain in use. The score-style helper is left unchanged by this branch so the independently reviewed fixed 0/100/200/above-200 palette can integrate without a conflicting algorithm.

## Validation

- Full Python suite: 179 tests passed.
- Client suite: 10 tests passed; `node --check web/cohort/app.js` passed.
- Added regression coverage for tile alias/slot deduplication, advanced availability, missing setup/ownership, exact class priority/count order, sparse/complete record equivalence, streaming/batch equality, measured Elo weights, frequency hover probabilities, raw category identity, and parent score weighting.
- A parity test executes the original notebook function on a controlled dataset and verifies every leaf, class total, root total, and `branchvalues`.
- Historical four-player CSV, 4,859 games / 19,436 player observations: 90 advanced position cells reduce to 15 tile bars; 81 basic position cells reduce to 9 tile bars. The opening chart has 91 exact configurations in six classes.
- Original notebook frequency functions on the historical Terrans cohort produce the same tile sets (9 basic / 15 advanced) and total acquisition rates within original percentage-rounding error: maximum absolute probability difference 0.000008395 basic and 0.000005936 advanced. Rank distributions intentionally retain corrected net-score ranking rather than historical leaderboard position.
- Managed browser QA on the real Plotly bundle verified default/position toggles, 15/90/9 exact-table row counts, and nested treemap drill-down and return to root. Preview combined the independently reviewed fixed score anchors with this hierarchy; no application console errors were observed.

## Integration notes

This isolated branch starts at `c7f27f4`. Its backend edits are in technology/structure `statistics` and streaming cell merging; it does not change cohort selection or comparison-table selection. The frontend edits touch `save`, `loadMode`, frequency/structure drawing, and a new frequency view control. Reconcile these small shared areas with the separate tech-mode, shortened-label, and comparison-table branches.

The existing frequency/score response-cache alias remains valid because both technology plot kinds include the same raw position cells and aggregate tile cells. If a later tech-mode implementation changes either response shape, verify or remove that cache alias during integration. Preserve the new fixed color helper, the raw keys used for category identity, and the helper's `{marker, note}` contract.
