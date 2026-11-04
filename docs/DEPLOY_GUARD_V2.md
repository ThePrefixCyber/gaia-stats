# Standalone deployment guard v2

This branch is based on main `82f6c09`. It adds only the updater gate, a
standard-library-only data checker, tests, and this document. It does **not**
include `deploy/data-contract.json`, change statistical methods, collect data,
select a release, alter systemd overrides, or enable cleanup.

The combined candidate `c16d37c` declares deployment contract version 2. It must
not be promoted until this guard has separately been approved and verified on
the server. Approval to prepare/publish this review branch is not approval to
promote it to main or deploy it.

## Behavior

When a target Git commit has no contract, the existing update path and health
verification are unchanged. When it has a contract, the running updater reads
that target's contract with `git show` and checks the currently configured data
as `gaia-stats` **before** checkout, dependency installation or restart. A failure
retains the running code/data, records failure and does not trigger rollback of
an unchanged checkout. The existing updater and refresh locks remain in force.

The checker imports no application code or third-party package. It supports
contract v1 for the earlier scoring migration and contract v2 for static base
plus incremental LF. It verifies source/serving/cache policies, exact scores,
ranks and wins, hashes, counts, exclusion registry, CSV provenance and assets.
For v2 it also requires the new LF storage format, verifies every referenced LF
object, and compares every serving base payload against the selected original
CSV seed minus verified exclusions. Unknown contracts fail closed.

It never writes dataset or cache files. Its temporary contract file is the
updater's own transient working file; no archive cleanup is performed.

## Safe deployment prerequisites

1. Obtain explicit approval for this exact guard-only main promotion/deployment.
   The earlier guard promotion remains blocked until that approval is given.
2. Verify production is still on the expected clean main lineage and record its
   current code SHA, release/cache pointers, data counts and service health.
   Check actual Python is compatible and `gaia-stats` can read the chosen data.
3. Promote **only this standalone guard branch**. Do not include the combined
   scoring/storage candidate or any data-contract file in this first promotion.
   The normal code-updater pipeline can restart the app; account for that brief
   interruption. Alternatively use an expressly approved controlled deployment.
4. Verify the exact deployed guard SHA and both endpoints. Let any updater
   process that started with the old script finish before relying on the guard.
   A guard added to a target cannot protect the old updater's first transition
   to that same target, which is why the guard must land separately first.
5. Invoke the installed checker read-only against the combined candidate's v2
   contract and **current old data**. Expect refusal before any checkout or
   restart. Verify the updater's no-contract path remains healthy on guard main.
6. Stage/review the production bundle separately. Before later activation, verify
   the installed checker passes against its exact 2/3/4-player source CSVs,
   seed, release, LF objects and classic cache. The app, refresh service and
   updater must resolve the same approved bundle. The guard does not switch
   their paths or activate a bundle itself.
7. Only then obtain/confirm authorization for the combined code/data transition.
   Keep prior paired code/data and the raw archive for rollback. Do not remove
   historical data as part of deploying the guard.

A missing/incorrect bundle path, old score provenance, old inline LF format or
raw-merged base must block combined-code activation. Fix those prerequisites
through the reviewed staging procedure rather than weakening the gate.
