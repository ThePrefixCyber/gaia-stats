# Mandatory game eligibility

Every public statistical route excludes games explicitly marked `more-balanced`
and entire games where any observed player score before auction bids is **below 100 VP**,
for both base Gaia Project and Lost Fleet. Exactly 100 VP remains eligible.
There is no switch to include either excluded class. The rule applies before
faction, Elo, setup and other optional filters, so hiding the low-scoring player
cannot retain their opponents. Missing scores are not zero and are not evidence
of a sub-100 score. Missing bid evidence likewise does not become a zero bid. Raw normalization and historical CSV conversion still reject
missing or invalid final results separately. This is a user-selected inclusion
rule, not proof that every excluded game was abandoned.
This rule is independent of the existing two-player Lost Fleet 4-QIC technology
filter. Standard, beta, future unknown string variants and missing metadata are
not presumed to be more-balanced.

## Evidence and classification

BGS gameplay exports expose `factionVariant` at `game.options.factionVariant` and
`data.options.factionVariant`. Either location explicitly equal to `more-balanced`
is sufficient to exclude the entire game. Both values are retained in normalized
`faction_variant_sources` for audit. Other conflicting nonempty known values are
rejected by normalization rather than chosen by overwrite order. Missing, null,
empty or `unknown` values normalize to unknown unless the other location supplies
a known value. Faction boards, `variantVersion`, faction names, expansion status,
and `lostFleet2pQicTech` are not evidence of this variant.

Historical wide CSVs expose the corresponding `balance_variant` column. The
checked-in `data/remote_four_players_data.csv` has 5,687 game rows: 1,395 marked
more-balanced, 4,169 standard and 123 beta. The cutoff uses the score before bids
where the player’s aligned auction cost is known. Exactly 1,608 games have
someone below 100 before bids, including 411 also marked more-balanced; the
combined eligible download has 3,095 games before dropped-game checks. The Terrans 25-VP
record is in `EU-Timezone-50-Karma`, a standard-variant game. Its bid
cost is 6, giving 31 VP before bids, so the game remains excluded.
The source CSV remains byte-for-byte unchanged.

Reproducible public examples checked on 2026-11-04:

- [Modern-riddle-1723 export](https://www.boardgamers.space/api/gameplay/Modern-riddle-1723):
  more-balanced in both locations (also checked in as a scoring-audit fixture).
- [Vintage-space-3429 export](https://www.boardgamers.space/api/gameplay/Vintage-space-3429):
  more-balanced in both locations.
- [Eclipsed-council-7948 export](https://www.boardgamers.space/api/gameplay/Eclipsed-council-7948):
  standard in both locations, with the separate `lostFleet2pQicTech` option true.

These are metadata examples, not an inference that all historical games have the
same export shape. Missing historical evidence cannot safely be reconstructed
from a game's faction choices. Existing normalized data that discarded original
metadata must be refreshed from preserved raw sources when available.

Raw final-score evidence is the reconciled BGS `players[].score` minus the
**signed** auction VP event. A printed score of 75 with a -50 auction contribution
becomes 125 before bids. Positive state bid amounts are costs, not signed VP
entries, and are never subtracted from printed results.

Historical CSV player metadata is ordered by pre-bid score, while its `score_*`
source bundles were stored by net-score rank. The aligned player total is
`pos_N_score + pos_N_bid`; blindly subtracting `pos_N_score_bid` can use another
player's bid. Untied source bundles are reassigned by printed-score rank and
verified against the player's reported total. Tied source bundles may have been
overwritten by the old parser and remain unavailable unless raw evidence can
restore them. Own research VP and the final pre-bid total remain available.
The starting 10 VP and ship penalties are retained. Non-finite, blank, null,
malformed and missing values remain unknown rather than becoming zero.

## Ingestion, serving and release migration

- Archive collection writes original response bytes and provenance before marking
  a game with explicit variant or low-score evidence `excluded`. It does not publish normalized rows for the
  game or retry it as a download failure. Both recent-head and historical cursor
  or offset scans follow the same rule; excluded downloads count toward budgets.
- Standalone fetch retains the excluded raw export. Analysis/cohort builders skip
  explicit excluded exports. Low-level normalization remains available for audit,
  but all statistical selection and percentile universes apply eligibility first.
  Verified exclusion-only builds may produce an empty dataset; unrelated invalid
  inputs still preserve the prior output rather than silently clearing it.
- Base CSV import excludes marked IDs across all supplied CSVs. The SQLite read
  gate also excludes whole IDs based on the stored column or JSON payload, so old
  databases are safe before their next rebuild. Old historical rows lacking
  corrected bid provenance have unavailable pre-bid scores until source reimport.
  Rebuild the seed from its original CSVs, then publish: newly marked seed rows
  replace preserved historical rows, while verified raw-ledger rows are retained.
  Missing metadata stays unknown.
- LF JSON reads exclude entire game IDs even if only one row retains the marker.
  API options, selected chart/table/CSV cohorts and health counts use eligible rows.
- Release publication rechecks preserved raw exports, including old `accepted`
  records, plus hash/identity-verified rejected raw exports for exclusion evidence
  only, and cleans only the new staged release. A newly fetched explicit marker
  or final score below 100 can remove an older seed/legacy game. It is a verified policy exclusion,
  not permission for arbitrary record loss: the normal no-loss guard remains.
- Release manifests carry `eligibility_policy: 3`. The policy is part of source
  identity, forcing migration with otherwise unchanged inputs. A stamped release
  containing an excluded game fails validation. Version-1 exclusion registries
  and safely emptied releases remain readable during migration. Version-1
  statistical caches must be rebuilt because they did not apply the score rule. Prior release files, source inputs
  and archive bytes are not deleted or modified. Rollback to an older release is
  safe through the same read-time gates and eligible health counts. A monotonic
  release-store exclusion registry prevents reintroduction of games excluded by
  valid more-balanced or pre-bid evidence. Policy 2 used the superseded net-score
  cutoff and was never deployed; any such manifest, registry or source input is
  explicitly rejected. Rebuild from original raw/CSV sources into a new store
  instead of relabelling or carrying forward its potentially incorrect tombstones.
  An unsafe rollback is rejected (including by HTTP serving), until rebuilt from
  eligible sources. An interrupted registry/pointer swap fails closed and is
  recoverable by the next publication.

## Classic cache safety

Existing HTML charts and imported comparison aggregates cannot be filtered at
request time. `legacy_cache` refuses unstamped caches at every chart, catalog and
CSV route, including original URL aliases, until an offline rebuild completes.
The shell remains accessible and reports an explicit unavailability message.

Rebuild classic charts with the existing deployment command and the source CSVs:

```sh
python -m gaia_stats.legacy_cache --cache /path/to/classic-cache \
  --csv 4=data/remote_four_players_data.csv \
  --exclusion-store /path/to/releases-store
```

Pass the available 2- and 3-player source CSVs too on deployments that have them.
The builder filters before every corrected pre-bid chart calculation,
writes a filtered download, stamps the new cache with both eligibility and
`score_basis_version: prebid-v1`, and atomically switches its
pointer only after success. Old caches and superseded calculation stamps are kept intact for recovery, but cannot
be served by this policy. A private eligible-game index also checks caches against
new release-store exclusion evidence. A cache containing newly excluded IDs is
unavailable until rebuilt with `--exclusion-store`; unrelated exclusions do not
disable safe caches. Exclusion IDs are shared across all supplied player-count
CSVs, so inconsistent unknown duplicates cannot survive in another input.

Imported `dat.json` comparison aggregates have no game-level eligibility provenance.
They are not copied or served, even if `--comparisons` is supplied for compatibility.
`comparisons_unavailable` explains this in the new catalog. Use the current cohort
comparison tables, which calculate from eligible records. The old aggregate
calculator remains a private offline audit utility, not an HTTP data route.

Tests cover the strict 100 boundary, missing-score classification, pre-bid-score
basis, whole-game removal before filters, explicit and missing metadata, conflicting flags, base/LF, the separate
4-QIC modes, recent/history collection, old SQLite/JSON reads, raw retention,
backfill removal, release migration/rollback, CSV/percentile consistency, and
all classic route aliases. Original notebook/source hashes remain frozen; plot
parity compares the notebook and adapter on the same eligible cohort.
