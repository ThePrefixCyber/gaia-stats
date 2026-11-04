# Static base and incremental Lost Fleet storage

This is a review-branch design, not a claim that production has been migrated.
The separate LF-only collector hotfix can run on the old release format first.
Never promote the bundled scoring/artwork changes without the deployment guard
and reviewed paired-data preparation described in `PREBID_ROLLOUT.md`.

## What caused the growth

The previous refresh collected both base and LF. Any accepted base export changed
publication identity. The publisher then copied the entire prior base SQLite
file and replayed every accepted raw export, even when LF had no new games.
Generation retention amplified this into repeated full base copies. A raw game
is not a reason to duplicate a static historical dataset.

Tim's original notebooks are base-only analyses of wide CSVs. Their archived
source is https://github.com/TimGladyshev/bgs_data_gaia . This implementation keeps
our corrected scoring/eligibility and LF support, without a live base collector.
We have not inferred Tim's exact production disk layout from the notebooks.

## Stored once, selected atomically

- **Base:** rebuild the original CSV seed once with aligned pre-bid scores and
  whole-game eligibility. The first serving snapshot is copied from the seed.
  Later LF releases hardlink that validated, release-owned immutable snapshot.
  No seed inode is linked; no linked release file is opened for writing.
  A changed seed or applicable exclusion set produces a new base snapshot.
- **LF:** `objects/lost-fleet/<sha256>.json` contains one processed game. Object
  bytes are deterministic. Only a new or changed game creates an object. An
  interrupted write leaves an unreferenced temporary file, never a partial final
  hash path. Existing objects are verified before reuse.
- **Release:** `lost-fleet.json` contains a small game-ID-to-hash index. The
  manifest records source versions, counts, hashes, exclusion evidence, and
  per-game raw hashes/statuses. One atomic pointer selects the release.
- **No-op:** identical sources do not create directories or move the pointer.
  A changed source that produces identical observations updates only a small
  source checkpoint. The checkpoint is tied to a validated release and cannot
  carry processing results across policy/normalization/score-version changes.
- **Archive:** existing raw exports, collector rows, provenance, pending base
  queue and checkpoints remain untouched. Ongoing collection is LF only.
  Unavailable historical LF raw does not remove already processed LF records.

Both serving and the standalone deployment gate verify indexed object hashes,
containment, identity and the existing scoring/eligibility rules. Old inline LF
JSON remains readable, so prior release rollback is supported by this code.
The current release is validated before a no-op can be accepted.

Hardlinks require the release snapshots to share a filesystem. Failure to create
a link stops publication, preserving the pointer, rather than silently restarting
full-copy growth. The new format's reader must accompany its data: older code
cannot read an indexed LF dataset. Roll back the paired code/data bundle together.

## CSV-only transition and eligibility

An ordinary refresh refuses an old merged-base release. The reviewed bundle
preparer copies the selected old generation into an independent store, rebuilds
original CSVs and explicitly authorizes the source-policy transition there.
`base_migration` records the previous hash/counts, seed hash, and number of base
records now present only in the preserved baseline. Matching raw overlays also
return to the original CSV values. LF no-loss validation remains in force.

Existing base raw may contain verified whole-game exclusion evidence absent
from historical CSV metadata. It is inspected once during first publication or
source migration for that evidence only. No base raw observations are imported.
After migration, ordinary base-archive changes are outside publication identity;
there is no periodic base backfill. Persisted exclusions remain monotonic.

The seed, original CSVs, every prior release and raw files remain unchanged.
A dry run or interrupted publication can leave an unselected candidate for
inspection. No automatic cleanup is implemented.

## Review and activation checks

1. Record selected old release, code SHA, original CSV hashes, archive counts and
   disk usage. Stop and wait for writers before controlled staging/activation.
2. Run unit/client tests and prepare a separate bundle from actual production
   2/3/4-player CSVs and existing archive. Never substitute generated downloads.
3. Run the standalone contract gate against exact candidate code/data. Compare
   base IDs and payloads to the rebuilt seed minus verified exclusions. Review
   the archive-only count. Verify prior LF IDs, raw/source hashes and old pointers.
4. Inspect both mode APIs, CSV exports, cached classic views, scores and filters.
   In staging, add an eligible recorded LF export: only that raw should normalize,
   exactly one new processed game object should appear, and base inode/hash must
   remain unchanged. Repeat refresh with no change: no new release or pointer swap.
5. Activate only after review and approval using the paired-bundle procedure.
   Observe a real scheduled LF-only pass and no-op, plus disk and service health.

## Cleanup remains a separate operation

This fix does not delete or rewrite the accumulated full-copy generations. After
activation and verification, inventory their exact paths, hashes and identities.
Keep the original CSVs, complete raw/provenance archive, selected new bundle,
required paired rollback bundle, and a validated old merged-base baseline holding
raw-only historical observations. Retain any generation with unique data until
that uniqueness is accounted for. Reclaim estimates must use unique allocated
inodes, not sum apparent hardlink sizes. Obtain approval for the exact permanent
cleanup set and verify archive recoverability before removing anything.

A local rollback copy is not an off-server backup. No broader backup claim is made.
