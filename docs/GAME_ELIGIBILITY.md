# Mandatory game eligibility

Every public statistical route excludes games explicitly marked `more-balanced`,
for both base Gaia Project and Lost Fleet. There is no switch to include them.
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
more-balanced, 4,169 standard and 123 beta. The eligible classic download contains
4,292 rows before the additional dropped-game chart eligibility rule is applied.
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

## Ingestion, serving and release migration

- Archive collection writes original response bytes and provenance before marking
  an explicit variant game `excluded`. It does not publish normalized rows for the
  game or retry it as a download failure. Both recent-head and historical cursor
  or offset scans follow the same rule; excluded downloads count toward budgets.
- Standalone fetch retains the excluded raw export. Analysis/cohort builders skip
  explicit excluded exports. Low-level normalization remains available for audit,
  but all statistical selection and percentile universes apply eligibility first.
  Verified exclusion-only builds may produce an empty dataset; unrelated invalid
  inputs still preserve the prior output rather than silently clearing it.
- Base CSV import excludes marked IDs across all supplied CSVs. The SQLite read
  gate also excludes whole IDs based on the stored column or JSON payload, so old
  databases are safe before their next rebuild. Missing metadata stays unknown.
- LF JSON reads exclude entire game IDs even if only one row retains the marker.
  API options, selected chart/table/CSV cohorts and health counts use eligible rows.
- Release publication rechecks preserved raw exports, including old `accepted`
  records, plus hash/identity-verified rejected raw exports for exclusion evidence
  only, and cleans only the new staged release. A newly fetched explicit marker
  can remove an older unknown seed/legacy game. It is a verified policy exclusion,
  not permission for arbitrary record loss: the normal no-loss guard remains.
- Release manifests carry `eligibility_policy: 1`. The policy is part of source
  identity, forcing migration with otherwise unchanged inputs. A stamped release
  containing a marked game fails validation. Prior release files, source inputs
  and archive bytes are not deleted or modified. Rollback to an older release is
  safe through the same read-time gates and eligible health counts. A monotonic
  release-store exclusion registry prevents reintroduction of old unknown copies.
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
The builder filters before either corrected or historical notebook calculations,
writes a filtered download, stamps the new cache, and atomically switches its
pointer only after success. Old caches are kept intact for recovery, but cannot
be served by this policy. A private eligible-game index also checks caches against
new release-store exclusion evidence. A cache containing newly excluded IDs is
unavailable until rebuilt with `--exclusion-store`; unrelated exclusions do not
disable safe caches. Exclusion IDs are shared across all supplied player-count
CSVs, so inconsistent unknown duplicates cannot survive in another input.

Imported `dat.json` comparison aggregates have no game-level variant provenance.
They are not copied or served, even if `--comparisons` is supplied for compatibility.
`comparisons_unavailable` explains this in the new catalog. Use the current cohort
comparison tables, which calculate from eligible records. The old aggregate
calculator remains a private offline audit utility, not an HTTP data route.

Tests cover explicit and missing metadata, conflicting flags, base/LF, the separate
4-QIC modes, recent/history collection, old SQLite/JSON reads, raw retention,
backfill removal, release migration/rollback, CSV/percentile consistency, and
all classic route aliases. Original notebook/source hashes remain frozen; plot
parity compares the notebook and adapter on the same eligible cohort.
