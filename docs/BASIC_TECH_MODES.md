# Basic technology views

These views use the selected ruleset, player count, Elo, variants, setup and graph
faction. Raw exports, historical CSVs, scoring and archive checkpoints are unchanged.

1. **Acquisition by setup** groups by original source location. Lost Fleet shows
   six research tracks, four ships and one Free bucket. Stacks show acquisition
   frequency by final rank: denominator is eligible player-games with the tile
   in that location and known ownership. Hover also reports conditional rank
   frequencies and the cohort rank baseline. Free slots collapse and a
   player-game/tile/bucket counts once.
2. **Score when taken** shows pooled mean final net VP among acquirers at each
   original location, plus Taken and Not taken summaries and the cohort mean.
   Individual free slots remain separate here. This matches the meaning of
   Tim's “By Track Taken”: source location, not the research track advanced.
3. **Score by setup** includes every player-game where the tile occupied that
   location, regardless of acquisition. Free slots combine. Missing ownership
   does not exclude a known setup observation.

Every mode has its own response-cache key. Counts and score sums pool across
whole-game batches; means of subgroup means are not used. Unknown inventory
never counts as “not taken”. Covered tiles still count as acquired. Setup pile
count zero does not mean that the tile was absent.

## Evidence and deliberate differences

Tim's `basic_tech.ipynb` restores auction bids and averages rank-group means,
then location means, equally. These views retain net VP and weight each eligible
player-game equally. Taken/Not taken summaries include free locations, unlike
Tim's original. These are descriptive associations, not causal effects.

BGS owned technology entries preserve the original position. Exhausted spaceship
piles disappear from setup data, so their exact identity is recovered from owned
entries across the complete game before faction/Elo filtering. Contradictory
ship evidence remains unavailable. Historical effect aliases are canonicalized
for basic-tech aggregation only; raw data remain unchanged.

BGS source `98017d2d8d71d6b36adbfd20dfd4f28b7e4d42fd`, especially
`engine/src/spaceships.ts`, `engine/src/move/research.ts` and
`viewer/src/data/spaceships.ts`, plus Lost Fleet rules page 6 support the ship
mapping. Twilight holds artifacts, not a technology tile: its bucket is N/A.
Rebellion is absent in two-player Lost Fleet. Neither is invented as a zero.

The committed Jubilant-rover-3041 export checks TF Mars resource technology:
2 acquirers average 159.5 VP; all 4 setup observations average 139.75 VP;
2 non-acquirers average 120 VP. It also tests an exhausted navigation pile and
a covered tile. Synthetic regressions cover aliases, duplicate free slots,
unknown ownership, conflicting ship evidence and streaming batches.

## Presentation

Internal IDs stay in keys and machine-readable exports. Human labels use effect
shorthands with a full description key. The chart workspace expands to the
viewport, resizes with the window, and exits with Escape; narrow frequency plots
scroll inside their own frame. Faction belongs beside the graph and keeps its
per-mode state. The new-visitor default is Lost Fleet • Live; Base Game • Static
is second. A valid explicit URL overrides a remembered session choice. These
requested labels do not change either ruleset's collection or publication.

Real Chromium checks use fixture data, actual Plotly and desktop/mobile widths.
The supplied Library screenshots could not be materialized through the supported
transfer helper; source and parent-provided screenshot descriptions guided the
layout. Full live-archive visual coverage still requires production review.
