# Tile descriptions

The live cohort UI labels technologies, round scoring, final objectives and
booster VP sources with their effects and timing. The exact BGS identifier stays
in brackets. Select values, statistics, cached data, CSVs, archive identities and
backfill checkpoints are unchanged. A shared key includes Tim's historical
aliases. The historical comparison wizard and results also use these labels.
Previously generated historical plot files and direct downloads retain their
original labels; the plot wrapper supplies the matching key rather than rewriting
those reproducible artifacts.

Definitions live in `web/cohort/tile-labels.json`; presentation code lives beside
it. Unknown tiles are explicitly marked unmapped. Technology positions such as
`adv-terra` and `tech-terra` are **not** tile identities. Tech plots already pair
actual tile identity with its position; pooled VP sources at a position keep
that distinction instead of claiming one fixed effect.

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
