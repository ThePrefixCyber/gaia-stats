# Local Lost Fleet cohort milestone

Subsequent milestone: [dynamic-cohorts.md](dynamic-cohorts.md) now implements the previously deferred live base filtering and regenerated comparison tables. This document records the earlier bounded stage.

The historical base-game path remains `/classic/`. `/cohort/` provides the same eight
chart families over normalized Lost Fleet player-game observations. The selector
switches between these separate datasets; no base/LF pooling occurs.

Build the local sample (raw exports remain outside Git):

```sh
python -m gaia_stats.cohort --raw /path/to/public-exports --output /path/to/cohort.json
GAIA_DATASET=/path/to/cohort.json GAIA_CLASSIC_CACHE=/path/to/classic-cache \
  gunicorn 'gaia_stats.wsgi:create_app()' --bind 127.0.0.1:8766
```

The existing classic cache supplies the locally hosted Plotly library. The normalized
cohort is read through the existing atomic dataset reload. No external chart requests,
production import, automatic data collection, or deployment are added here.

## Data and rule evidence

30 paced public LF exports collected earlier were used: 29 complete games accepted,
102 player-game observations, all 18 factions. `Pale-signal-3586-4-c6238557` is rejected
because its log does not contain all six rounds. All accepted VP ledgers reconcile
exactly to final scores, with the standard initial 10 VP accounted for explicitly.
Each build records input file SHA-256 and acceptance/rejection reason.

Accepted counts: 21 four-player games (84 observations), two three-player games (6),
five standard two-player games (10), one variant two-player game (2).
New-faction observations: Moweyds 12, Tinkeroids 10, Darkanians 9, Space Giants 8.
This is a deliberately bounded coverage sample, not a representative archive.

Rules consulted locally:
- Base: https://www.feuerland-spiele.de/fileadmin/game/Gaia_Project/GAIA_PROJECT_EN_rules_Web.pdf
- Lost Fleet: https://capstone-games.com/cdn/shop/files/GP_Exp_Rule_EN_V1_Web.pdf?v=6134275372584409409
  Appendix I specifies Tinkeroids start with their institute and each other new faction
  with one mine. Setup is reconstructed from actual logged placements, not assumed
  base-game starting buildings. Raw BGS identifiers remain visible; no unsupported
  mapping from an ID to artwork or a guessed rule effect is introduced.

The saved ended-game listing is a JSON array whose game identifiers are `_id`, not
`slug`. The collector now accepts this observed identifier and fails closed on conflicting
`_id`/`slug`. Saved pages demonstrate BGS UI pagination: count=11, skip+=10 (lookahead).
The collector's existing count=N, skip+=actual-length scheme uses non-overlapping pages;
it does not adopt the UI lookahead, which would duplicate one row per page. Existing
persistent deduplication and overlap rescans remain unchanged. No new live scan ran.

## Calculations and filtering

- One `cohort()` function feeds chart cells, faction comparison rows, and CSV exports.
- Filters: player count, faction, initial player Elo minimum, layout, auction,
  faction variant, six round scoring slots, two final tiles, seven advanced-tech slots.
- `lostFleet2pQicTech`: standard-only default, include-both, variant-only. Absent means
  the documented false default; observed and effective values remain distinct.
- Missing Elo is included without a cutoff and excluded with one. This sample has no
  missing Elo; a regression injects missing data to verify the policy.
- Tech frequency is acquired / available **player-game opportunities** at a tile/slot,
  stacked by final competition rank. Covered basic technologies still count as acquired.
  This is not a percentage of games in which someone acquired the tile.
- Tech score is mean final net VP among acquirers at each tile/slot. No acquisition means
  unavailable score, while an observed zero acquisition frequency is legitimately zero.
- Round-one structures use setup and round-one building coordinates to replace upgrades.
  Only mines, trading stations, labs, institutes, and academies are included. Space
  stations, Gaiaformers, and ambiguous special building actions are not silently inferred;
  affected records have explicit unavailable structure metrics, without losing other data.
- Round scoring heatmaps show mean final net VP conditional on a tile at a round position.
  Final heatmaps show unordered final-tile pairs. These are descriptive associations,
  not VP earned directly from the tile, expected strategy value, or causal effects.
- Point-source boxes show the full signed reconciled VP ledger, including initial VP,
  charging, bids, ships, and expansion source IDs. Missing source in a complete ledger
  is a real zero; missing metric reconstruction is unavailable.
- Comparisons recompute mean net VP, rank, and shared wins from the exact selected LF
  records, never from historical `dat.json`. Complete setup matching can yield zero games;
  no interpolation, additive pseudo-prediction, or fallback to a different cohort occurs.
- Historical base aggregates retain the prior original notebook path and comparison
  correction. The precomputed aggregate file alone cannot support Elo re-filtering. The source
  CSV does contain pregame Elo, so regeneration is possible; the subsequent statistical
  pass implements offline Elo filtering for six base chart families. Live base cohort
  controls and CSV-derived comparison regeneration remain to be integrated.

## Verification and remaining limits

84 tests pass (76 preserved + 8 new tests), including reduced real-export regressions for
all four new factions, institute setup, covered technology, ship VP, mode isolation,
variant switching, missing Elo, setup filters, listing IDs, and API/CSV/chart consistency.
Browser QA: all 8 LF plots across 2/3/4 players render (24 combinations), no NaN/Infinity;
standard/both/variant-only changes 5/6/1 two-player games; high Elo clears old chart/table
content; base selector opens the existing historical chart. No browser console errors.

Remaining scope: full archive and incremental ingestion, representative statistical
coverage, friendly rule-verified tile labels/artwork, special-action structure replay,
normalized base Elo filtering, and production deployment. The LF charts preserve chart
families and controls but do not claim pixel-identical rendering or identical historical
notebook formulas. Mixed player-count means/ranks are descriptive only; select one player
count for interpretable comparisons. The sample's only layout is standard, so alternate
layout filters are supported structurally but not demonstrated by this sample.
