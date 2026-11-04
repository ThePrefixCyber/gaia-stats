# Reviewed chart parity integration

Base: `c7f27f4c3da75041391c825a4cc0bfd29ac6a626`.

Integrated reviewed remote trees:

- Scoring shares and faction-relative round win deltas: `43e3d91385711502243e22c75068cb114ecb63fd`.
- All-faction comparison tables: `8dc199948645bc7a3caaf2bc8ded184303b92a52`.
- Tile-frequency aggregation and exact opening hierarchy: `b5275cfac1ac868de736741c80c035b240bafac6`.
- Fixed red/grey/blue/green score anchors: `8283809d3d53502e45b3b66f44b52f2832dfae28`.

## Conflict decisions

Both backend helper imports are retained. The chart selector first chooses the point-source or round-scoring subview when applicable, otherwise the frequency tile/position subview. Both independent controls are present and hidden on unrelated charts. All scoring, frequency and hierarchy trace implementations are preserved. Scoring controls retain their selected chart mode; frequency grouping retains its ruleset memory.

Streaming preserves the all-faction comparison data even when the selected faction has no observations. It also merges aggregate tile cells, measured Elo counts, rank share distributions and round comparison baselines. The corrected Lost Fleet raw source vocabulary is unchanged.

Test expectations were reconciled with the combined response contract: comparison-scope tests now independently construct the extra selected-faction scoring payload rather than expecting the earlier unaugmented payload. The color test's lightweight DOM stub now includes the scoring control, and checks unchanged leaf colors/areas plus weighted parent colors/areas instead of expecting a flat treemap. A client regression switches among scoring, frequency and tree views to check independent controls and retained modes.

## Verification

- 190 Python tests passed.
- 14 client tests passed.
- 12 frontend table tests passed.
- 8 fixed-color draw-path tests passed.
- JavaScript syntax and `git diff --check` passed.
- Actual Plotly in the managed browser: selected historical Terrans graph has 2,018 observations while the comparison table retains all 14 factions; rank-share boxes and retained absolute VP render; round win deltas and retained raw wins render; treemap has the exact nested classes with fixed color anchors and drill-down; advanced frequency toggles between 15 aggregate tiles and 90 positions.
- Lost Fleet Tinkeroids selection has one observation while the table retains ten factions. At minimum Elo 300, its graph is empty while four eligible other factions remain. Clearing Elo recovers the chart. No application console errors observed.

The separate basic-tech modes and app-wide shortened-label branch is intentionally not included. It must be integrated after its own review, reconciling the shared draw/control sections and rechecking the frequency/score cache alias if its response shape changes. This integration does not change user data or deployment configuration.
