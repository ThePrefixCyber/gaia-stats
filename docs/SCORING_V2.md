# Phase-aware scoring correction

Normalization version 2 corrects raw base source grouping and makes the base and
Lost Fleet round/final heatmaps comparable. It does not alter final scores, ranks,
win shares, cohort filters, eligibility rules or historical CSV records.

A raw ledger is complete for zero semantics only when all six rounds were logged,
the final state and a log marker both say `endGame`, and VP plus the initial 10
points reconciles to the final score. Missing round/final events in those ledgers
are observed zeros. Historical CSV blanks remain unknown, including when raw and
historical records share a cohort. `score_samples` is the denominator for tile VP;
`samples` is the denominator for final-score and win statistics. Hover counts and
exact observations expose the corresponding denominator.

For base raw exports, `vp_sources` uses the original CSV groups: initial 10 (`init`),
bid, charge, boosters, six rounds, federation, advanced/basic technology, QIC,
in-game Gaia, Gleens, two final tiles, end-game resources and research. Each event
is assigned once. In particular the `gaia` source during final scoring is research,
not in-game Gaia VP. New unknown sources remain explicit `unmapped:*` categories;
no points are dropped. `vp_sources_raw` retains original BGS source totals plus the
initial 10. LF point-source boxes retain their existing raw source vocabulary,
including expansion ship VP; the tile metric is independent of those labels.

Both rulesets now show mean **VP earned from the round tile or final tile pair**
in their scoring heatmaps and comparison tables. The previous LF conditional
final net score is retained as the distinct `mean_final_score` observation column,
not substituted for tile-earned VP. Shared-win heatmaps still use final net scores.
`scoring_vp` records eight phase-checked tile totals. A nonzero scoring event in an
unexpected round/phase makes tile scoring unavailable for that player; its raw VP
and final-score reconciliation remain available. Older LF snapshots without these
fields cannot supply the new tile metric until recomputed.

## Evidence and validation

The checked local archive contains 27 accepted base games / 91 player records and
129 accepted LF games / 332 records. Every ledger reconciles. All 1,820 base
category values match Tim's original `parse_tree_moves` grouping plus the rulebook
research formula (4 VP for each level above 2). LF acceptance remains 129 of 179:
37 cancelled, 7 incomplete, 4 dropped, 2 solo/automa excluded.

Reduced fixtures retain public scoring evidence, not account identities. Examples:
Silly-rocket-2154 Terrans has 26 booster, 22 federation, 12 advanced-tech, 20 research
and 2 resource VP; Vibrant-flagship-1713 Terrans separates 25 raw Gaia VP into 13
in-game Gaia and 12 research VP. Shiny-cypress-1384 final-pair totals are 0, 12, 24,
36, yielding 18 with denominator 4. Jubilant-rover-3041 LF final-pair mean is 18,
whereas its conditional final net score is 139.75. Its round tile means are 4.5,
3.75, 3.75, 5, 4, 5. Admirable-falcon-401 final-pair mean is 24;
Eclipsed-council-7948 (2-player variant) is 30.

Rules references: [official base rules](https://www.feuerland-spiele.de/fileadmin/game/Gaia_Project/GAIA_PROJECT_EN_rules_Web.pdf)
and [official Lost Fleet rules](https://capstone-games.com/cdn/shop/files/GP_Exp_Rule_EN_V1_Web.pdf?v=6134275372584409409).

## Discovery and recomputation

The public `boardgame=gaia-project` ended-game list includes LF games. Verified
listing records expose `game.expansions: ["lost-fleet"]`. A bounded two-entry read
on 2026-11-01 confirmed this for Hyper-shark-5522 and Proper-outpost-7588; response
SHA256 `70d113fbbca77106ffe2399ab9a8457f9371fe55e8fb6cb41ac95724dd1a29ff`. The base collector now
saves that listing evidence locally and marks those queue items `skipped` before
requesting a full export. It also skips old pending entries already accepted in the
local LF archive. Conflicting/missing metadata still requires the full export;
factions never determine ruleset. Existing accepted/rejected records and raw files
are preserved, and skipped records do not consume the download budget. This fixes
redundant requests without assuming an undocumented base-only API filter.

After review and code deployment, use the existing release publisher with the same
seed, archive and legacy paths documented in `REBUILT_RELEASE.md`. The source
fingerprint now includes `normalization_version: 2`; even with unchanged raw
hashes it recomputes **all accepted raw exports** into a new immutable generation.
Historical seed rows remain untouched unless superseded by their exact raw game
ID, and the existing no-record-loss guard applies. No re-download or database
schema migration is needed. Dry-run, inspect, publish, then run rebuilt preflight;
the running app detects the pointer change and replaces its versioned caches.
A subsequent unchanged-input publish is a no-op. Existing prior generations remain
available for scoped rollback; no retention deletion is part of this change.

The release publisher is authoritative for serving data. Archive `rows/` JSON files
are historical import artifacts and are not read by publication; they are not
rewritten by this recomputation. Accepted raw exports lacking verified final-phase
evidence will honestly show unavailable tile metrics rather than fabricated zeros.

Local validation: 120 tests pass, including old-generation recomputation, a second
unchanged-input no-op, raw identity preservation, ambiguous listing metadata and
zero denominators. Browser checks cover round/final/source plots in both modes,
LF two-player standard/both/variant-only (87/90/3 games; 174/180/6 observations),
empty high-Elo selection and recovery. The full local candidate contains 28,631
base games / 78,901 observations and 129 LF games / 332 observations. One historical
base observation retains unknown scoring data; no accepted raw record has unknown
tile VP. These are local evidence counts, not a claim about ongoing live backfill.
