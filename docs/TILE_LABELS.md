# Tile descriptions

The cohort UI uses concise effect shorthands, with full descriptions in the
collapsible Shorthand key. Technical identifiers and historical aliases remain
internal keys and CSV values, never display suffixes. Distinct tiles with the
same shorthand retain separate coordinates and filter values. Unknown values
are shown as unknown rather than assigned an invented effect.

Definitions live in `web/cohort/tile-labels.json`; presentation code lives beside
it. Position labels identify source locations, not the tile occupying them.
Gaia and Artificial Intelligence are displayed without a “position” suffix.
The cohort charts, selectors, exact tables, historical comparison pages and
Opening Explorer use this shared mapping. Cached historical plots are relabelled
when served (including standalone downloads), without modifying cached data,
coordinates or statistical calculations. Source VP categories get readable
names; unsupported source categories remain “Other VP”.

## Evidence

Reviewed against BGS source at commit
[`98017d2d8d71d6b36adbfd20dfd4f28b7e4d42fd`](https://github.com/boardgamers/gaia-project/tree/98017d2d8d71d6b36adbfd20dfd4f28b7e4d42fd):

- `engine/src/tiles/techs.ts` and `viewer/src/data/tech-tiles.ts`: standard,
  advanced and ship technologies, including timing.
- `engine/src/tiles/boosters.ts`: incomes, pass scoring and special actions.
- `engine/src/tiles/scoring.ts`, `engine/src/enums.ts`, and the final-scoring
  implementation in `engine/src/player.ts`: round tiles and final objectives.
- `engine/src/actions.ts`: numbered QIC actions in VP source data.
- The committed `parse_jsons.ipynb`: Tim's aliases, retained as identifiers.

Lost Fleet cross-check: [publisher rulebook](https://capstone-games.com/cdn/shop/files/GP_Exp_Rule_EN_V1_Web.pdf?v=6134275372584409409).
Labels paraphrase game effects, not official tile names. No upstream artwork or
implementation is copied.

Important distinctions:

- `advtech4/9` score current buildings immediately; `advtech14/15` score later
  builds. `advtech-deep` is immediate, while `advtech-deeppass` scores on passing.
- Tim's `k_per_terra` and `1vp_per_terra_pass` mean **planet types**, not
  terraforming steps.
- Charging power differs from gaining power tokens.
- `score7` and `score10` have the same effect but remain distinct IDs.
- Space-sector effects follow BGS's exclusion of Deep Space for the base sector
  tiles. BGS documents this as a site-owner ruling; it is not presented here as
  a verified official-rule clarification.
- Satellite final scoring includes Ivits space stations: BGS `player.ts:1184–1185`
  adds `buildings[Building.SpaceStation]` to `data.satellites`, and
  `tiles/scoring.ts:32` uses that condition for the satellite objective.
- `piAcademyDistance` is the distance to the **farthest** academy, not a sum.

Federation tokens, artifacts and power actions currently have no separate tile
selectors/plots in this application. Their mappings are not silently attached
to aggregate sources such as `fed` or `explore`, which combine multiple effects.

## Validation

`python -m unittest discover -s tests` checks registry coverage, historical
aliases, timing distinctions and resource serving without a dataset. Optional
local browser-helper checks (Node is not a deployment dependency):

```sh
python -c "from gaia_stats.cohort import response; print(response(None,'/cohort/tile-labels.js',{})[0].decode())" | node tests/browser/tile_labels.cjs
```

With Playwright and Chromium installed, `PYTHON=python node tests/browser/tile_labels_smoke.cjs` exercises eight chart modes, dropdown labels and unchanged filter IDs against real fixture-derived responses. It captures Plotly calls rather than testing image rendering.
