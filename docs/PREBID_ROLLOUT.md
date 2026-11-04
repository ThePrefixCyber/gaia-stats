# Reviewed pre-bid rollout: paired code and data

These are operator steps, not evidence of deployment. Do not merge the scoring
release while the old automatic updater is still running. The first rollout has
two reviewed commits: **guard-only** first, then **scoring + migration**. A guard
inside the scoring commit cannot protect the already-running old updater script.

## 1. Install the harmless guard first

Deploy the separately reviewed guard-only branch based on the current main. It
changes no scoring or datasets. Verify the running updater includes the target
`deploy/data-contract.json` check **before** `git merge --ff-only`. Its read-only
checker rejects missing/incompatible seed, release, cache, incomplete scores,
incorrect rank/win calculations, corrupt hashes, or obsolete policy-2 artifacts.
It also obtains the selected release store's refresh lock before changing code.
Targets without a contract remain compatible with the old dataset.

Once this guard is installed, an accidental scoring-main update is blocked before
checkout/restart unless the selected data satisfy the target contract. The guard
does not rebuild, switch, delete or “fix” production data automatically.

## 2. Inventory, pause and retain rollback evidence

Record current Git SHA, selected release/cache pointers, original seed/CSV paths,
all three relevant unit configurations, timer enabled/active states and counts.
Use a protected timestamped backup location and verify its free disk space first.
Keep backups private. Do not overwrite original CSVs or any raw archive files.

```sh
cd /opt/gaia-stats
git rev-parse HEAD
systemctl cat gaia-stats.service gaia-stats-data-refresh.service gaia-stats-update.service
systemctl is-enabled gaia-stats-data-refresh.timer gaia-stats-update.timer
systemctl is-active gaia-stats-data-refresh.timer gaia-stats-update.timer
systemctl stop gaia-stats-update.timer gaia-stats-data-refresh.timer
# Let active jobs finish; do not check out candidate code while they are running.
systemctl is-active gaia-stats-update.service gaia-stats-data-refresh.service
```

Both services must be inactive before continuing. Save the exact prior unit/drop-in
files, Git SHA and data/cache pointer JSON. The existing app may continue serving
its old generation while staging uses a **different checkout and bundle path**.
The staging tool also obtains source-release and archive-collector locks, so an
unexpected active collector causes a safe failure before preparation.

Identify the genuine original 2/3/4-player wide CSVs used to build the seed. The
committed four-player source is available, but do not assume it covers the full
production base dataset. **Do not substitute filtered classic downloads.** If
original sources are missing, stop: preserved historical rows have unknown
auction provenance and cannot pass activation preflight. Do not drop them merely
to make the check pass. Keep the source registry's version-1 or version-3 evidence;
policy-2 net-score tombstones require rebuilding from genuine original sources,
never changing the version number in place.

## Verified VPS inventory (2026-11-04, read-only)

The running app is healthy at `dc849363817921896ce01e516bb552bc7ada91ca`,
selecting `release-kt28zq1e`. Both code-update and data-refresh timers are active.
Original 2/3/4-player CSVs are retained at:

- `/var/lib/gaia-stats/classic-cache/build-jdu8ksim/data/2.csv`
- `/var/lib/gaia-stats/classic-cache/build-jdu8ksim/data/3.csv`
- `/var/lib/gaia-stats/classic-cache/build-jdu8ksim/data/4.csv`

Their SHA-256 values were checked against the original Mac provenance. These are
verified original files in an old immutable cache build, not newly filtered
downloads. Ignore `._*` AppleDouble files. Recheck hashes before staging and keep
that build untouched. The current seed is `/var/lib/gaia-stats/seeds/base.sqlite`.

Inventory showed 38.59 GiB free, a 36 GiB release store and a 1.2 GiB archive.
Recheck current free space immediately before preparation. The stager copies only
the **selected** release, not the 36 GiB history. Do not create a full same-volume
archive of the entire store: that could nearly exhaust the remaining disk.
Retain the existing immutable history and create a protected, scoped rollback
record containing the selected pointers, unit files, code SHA, counts and hashes.
There is no verified offsite backup; these local retention safeguards do not
protect against loss of the VPS disk. Do not claim an offsite backup was created.

## 3. Build a separate candidate bundle

Create a root-approved, service-writable parent such as
`/var/lib/gaia-stats/data-bundles`. Check out the reviewed scoring SHA in a separate
worktree with its own virtual environment and required dependencies; do not change
the live app’s shared environment during preparation. Set these shell variables to verified
values before running the commands:

- `CANDIDATE`: the separate reviewed checkout.
- `NEW_BUNDLE`: a fresh absolute directory under the approved bundle parent.
- `OLD_STORE`: the currently selected release-store directory.
- `ARCHIVE`: the preserved production raw archive/checkpoint directory.
- `LEGACY`: the current original analysis JSON, if still part of production inputs.
- `CSV2`, `CSV3`, `CSV4`: verified original CSV paths for all existing player-count datasets.

```sh
CSV2=/var/lib/gaia-stats/classic-cache/build-jdu8ksim/data/2.csv
CSV3=/var/lib/gaia-stats/classic-cache/build-jdu8ksim/data/3.csv
CSV4=/var/lib/gaia-stats/classic-cache/build-jdu8ksim/data/4.csv
OLD_STORE=/var/lib/gaia-stats/releases-store
ARCHIVE=/var/lib/gaia-stats/archive
LEGACY=/var/lib/gaia-stats/analysis.json
sha256sum "$CSV2" "$CSV3" "$CSV4"
df -B1 /var/lib/gaia-stats
cd "$CANDIDATE"
# Install candidate dependencies in its own environment before running as service user.
python3 -m venv .venv
.venv/bin/pip install -r requirements-web.txt
sudo -u gaia-stats .venv/bin/python -m gaia_stats.migrate_prebid \
  --destination "$NEW_BUNDLE" --source-root "$OLD_STORE" \
  --csv "2=$CSV2" --csv "3=$CSV3" --csv "4=$CSV4" \
  --archive "$ARCHIVE" --legacy "$LEGACY"
sudo -u gaia-stats .venv/bin/python deploy/check-data-contract.py \
  --contract deploy/data-contract.json --bundle "$NEW_BUNDLE"
sudo -u gaia-stats .venv/bin/python deploy/check-rebuilt.py \
  --root "$NEW_BUNDLE/releases-store" --cache "$NEW_BUNDLE/classic-cache"
```

Omit a player-count argument only if production has no retained historical data
for it. Omit `--legacy` only if the existing production process no longer uses it.
The preparation tool:

- Checks staging disk space before creating the destination: at least 1 GiB or
  four selected-release sizes plus twice the original CSV sizes plus 512 MiB,
  whichever is larger. Publication has its independent disk guard too.
- Rebuilds the seed from original CSVs, copies the currently selected release into
  the new store as a preservation baseline, then explicitly migrates served base
  observations to the original CSV seed only. Base raw-only records and raw
  overlays remain in the old baseline and raw archive; they are not served.
  LF no-loss and verified-exclusion safeguards remain active.
- Preserves raw observations, rebuilds historical CSV scoring from aligned bids,
  incrementally stores verified LF games and rebuilds classic charts in the new
  cache. Existing indexed LF objects are copied into the independent new store.
- Verifies every serving score/rank/win and all artifact versions/hashes.
  Unknown CSV score provenance blocks readiness. Unknown archived base-only
  records do not need to be imported into the static CSV dataset.
- Rechecks original input hashes and live-source pointers before marking the
  bundle `ready`. It never changes the active-data link. Failed bundles remain
  marked `failed` for diagnosis and cannot be selected by the app.

Review before/after counts and the explicit exclusion IDs, not just a successful
exit. The expected score change includes Nordic Geodens 221 → 236 and Darkanians
113 → 128. The existing 25-VP historical record remains excluded (31 before bids).
Verify source hashes remain unchanged, every prior LF ID remains unless explicitly
excluded, and the base source migration count matches the intended CSV-only scope.
All old base IDs remain in the preserved baseline, even when no longer served.

## 4. Activate during a controlled stop

This is the only service/data switch. Keep both timers stopped. Save the previous
`active-data` target if one exists. Stop the app and confirm refresh/updater are
inactive before replacing the bundle link or checking out scoring code.

```sh
systemctl stop gaia-stats
systemctl is-active gaia-stats-data-refresh.service gaia-stats-update.service
# Both must be inactive. The NEW_BUNDLE path has passed both preflights above.
ln -s "$NEW_BUNDLE" /var/lib/gaia-stats/active-data.next
mv -T /var/lib/gaia-stats/active-data.next /var/lib/gaia-stats/active-data
# Fast-forward /opt/gaia-stats to the exact reviewed, now-approved scoring SHA.
# Install reviewed dependencies and run the complete Python and Node gates.
install -d -m 0755 /etc/systemd/system/gaia-stats.service.d \
  /etc/systemd/system/gaia-stats-data-refresh.service.d \
  /etc/systemd/system/gaia-stats-update.service.d
install -m 0644 deploy/units/gaia-stats-prebid.conf \
  /etc/systemd/system/gaia-stats.service.d/prebid.conf
install -m 0644 deploy/units/gaia-stats-refresh-prebid.conf \
  /etc/systemd/system/gaia-stats-data-refresh.service.d/prebid.conf
install -m 0644 deploy/units/gaia-stats-update-prebid.conf \
  /etc/systemd/system/gaia-stats-update.service.d/prebid.conf
systemctl daemon-reload
systemd-analyze verify gaia-stats.service gaia-stats-data-refresh.service gaia-stats-update.service
sudo -u gaia-stats .venv/bin/python deploy/check-data-contract.py \
  --contract deploy/data-contract.json --bundle /var/lib/gaia-stats/active-data
systemctl start gaia-stats
.venv/bin/python deploy/verify-health.py "$(git rev-parse HEAD)"
```

Run commands that install repository files from `/opt/gaia-stats` after checking
out the exact approved SHA. Do not run a blind `git pull` or enable polling in the
middle of this sequence. If `active-data.next` already exists, inspect it and use
another fresh temporary link name rather than overwriting unknown state.
The app resolves the bundle once at startup; in-flight/old workers cannot follow
a later bundle swap. Refresh resolves one bundle at invocation, preserving the
same root/seed pairing. Updater validation/locking uses that same selected bundle.

Verify both local Gunicorn and Nginx endpoints, both modes, key example scores,
selected exports, both remaining permanent tables, nine views, spinner dismissal
and the classic cache. Restore only the timer states that were active before
this operation, and only after these checks pass. Run one bounded refresh and
inspect its publication/freshness result before re-enabling its recurring timer.

## 5. Rollback code and bundle together

Stop both timers, wait for updater/refresh to finish, then stop the app. Restore
the previous code SHA and previous unit/drop-in configurations. Restore the prior
active-data link if this was an existing bundle deployment; for the first bundle
migration, restore the saved original units pointing at the untouched old store,
seed and cache. Reload systemd, start the app and verify the previous SHA/counts
before restoring prior timer states.

Never restore an old backup over the raw archive or discovery checkpoint: newer
accepted exports must survive rollback. Do not delete failed/new bundles. Do not
run old code against the new pre-bid generation or new scoring code against old
historical seed rows. A release-pointer-only rollback is not a valid rollback
across this score-basis boundary.

## Local verification boundary

Local tests cover staging isolation, original-byte preservation, no-overwrite,
low disk, failed-stage retention, unknown-provenance blocking, guarded updater
ordering and worker bundle pinning. They do not establish actual VPS disk space,
permissions, original CSV availability, unit overrides or service health. Those
checks above are required before main merge/production activation.
