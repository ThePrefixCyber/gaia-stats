# Pre-bid scoring

All live calculations use score before auction costs. This applies to faction,
technology and opening averages, competition ranks, shared wins, scoring-tile
comparisons and their baselines, score-source percentages, and selected exports.
Auction contributions do not appear in analytical source distributions. Other
costs, including power charging and ship exploration, remain signed.

## Raw BGS exports

Analytical score is printed final score minus the **signed VP ledger** `bid`
contribution. A printed 113 with a −15 auction event becomes 128. The positive
state `bid` is retained as `bid_cost` for audit, not subtracted as a signed event.
An absent bid is zero only with reconciled completed-log evidence. Missing or
invalid evidence never becomes zero. Raw source totals, including the initial
10 VP, still reconcile to printed results.

`score` is the analytical total, `reported_score` is the original printed result,
`bid_delta` is the signed contribution, and `score_basis_version` is `prebid-v1`.
`reported_rank` and `reported_win_share` retain the original result. Analytical
ranks are computed across the entire game before faction or Elo filters. Ties
use competition ranks and divide a win equally. Repeated filtering does not
recompute already normalized ranks from a selected subset.

## Historical CSVs

The committed CSV's player metadata is in pre-bid order, but `score_*` source
bundles are in printed-score competition-rank order. Subtracting a same-position
`score_bid` can use another player's auction. The player's own positive
`pos_N_bid` remains aligned with `pos_N_score`; pre-bid total is their sum.
Missing or negative costs are unavailable rather than guessed from source fields.

Source ownership is recovered only when a candidate source bundle's signed bid
matches the player's own cost **and** its source sum plus that player's own
`tech_score` exactly matches the printed score. Both historical net-rank and
aligned-position layouts are checked; conflicting valid allocations are unknown.
An explicit `score_source_layout=player-position-v1` may identify a separately
verified aligned export. Technology ownership, structures and research totals are
not permuted with source columns.

In the committed 5,687-game four-player CSV, all 22,105 untied player source bundles
reconcile after mapping. The 643 net-tied player rows are conservatively left with
unknown source bundles because the historical parser overwrote tied source slots.
Their own research values, pre-bid totals, ranks, and win shares remain available.
A verified raw export can restore the missing breakdown. Original position source
columns remain in `vp_sources_csv_position`; corrected signed sources remain in
`vp_sources_audit`; analytical `vp_sources` omits `bid`.

## Migration and classic views

Normalization version 3 forces raw recomputation. Old historical SQLite rows lost
the aligned positive bid and cannot establish correct pre-bid results from their
stored source column. Rebuild the seed database from the untouched original CSVs.
The new seed carries `score_basis_version=prebid-v1`; release publication overlays
its corrected historical rows while preserving verified raw observations, then
applies raw replacements. Unknown legacy historical rows are not used to invent
analytical results during migration. Source files and prior releases are retained.

Classic cached charts must be rebuilt. All eight default classic chart families
now use the corrected pre-bid calculations. Original notebooks remain unchanged
and are available only through the explicit offline `methodology="historical"`
comparison adapter; they are not a live statistical fallback.

The independent whole-game eligibility policy excludes `more-balanced` games and
games with any known **pre-bid** score strictly below 100. Exactly 100 is included.
See [GAME_ELIGIBILITY.md](GAME_ELIGIBILITY.md) for release and cache safeguards.
