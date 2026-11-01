# Rebuilt application release procedure

Prepared locally; these are future operator commands, not evidence of deployment.
Do not run the old installer: this migration does not need firewall, credential,
or Nginx changes. Deploy only a reviewed exact source SHA. Keep the existing
`analysis.json`, historical CSVs, raw archive, and protected backups.

## Data contract and safeguards

The external store has immutable `releases/release-*/base.sqlite`,
`lost-fleet.json`, and hash/count manifests. One atomically replaced `current.json`
pins both modes. Requests retain their selected generation. A new generation
replaces the application's bounded caches without restarting Gunicorn; code
changes still require a restart. Missing/corrupt data fails with 503, never seeds
example records. Base/LF remain separate. Historical base game IDs are replaced
by validated raw exports, never appended twice; prior player-game identities
must survive publication. Conflicting duplicate input exports abort LF builds.

The collector prioritizes two newest listing pages before resuming the historical
cursor, separately for each ruleset. It uses 1.1-second minimum request spacing,
three attempts with backoff, at most 100 export attempts per mode per run and
20 historical pages per mode. The process deadline is 720 seconds, systemd's
outer limit 13 minutes, and memory limit 512 MiB. The lock rejects overlap.
Failed collection/publication retains the prior pointer and last-success time.
A killed run is reported as interrupted after 900 seconds; health reports stale
success after one hour. The timer waits 15 minutes after completion plus up to
two minutes jitter. This is periodic refresh, not a completeness guarantee.

Identical source fingerprints do not create another release. Changed releases
require at least 512 MiB or twice the base database size free, whichever is larger.
No historical generation or backup is automatically deleted. Operators must
monitor disk space and establish a reviewed retention policy before unattended
long-term backfill: at current size each changed generation uses about 160 MiB.
The disk guard fails closed and freshness exposes the failure. Raw archive and
checkpoint files remain resumable even when publication fails.

## Staged migration (on the VPS, only after release approval)

Record the exact current SHA, enabled timers and unit files. Pause the code timer
while changing the service/data contract. Use a root-only timestamped backup
outside `/var/lib/gaia-stats`, preserving all existing data and service overrides:

```sh
cd /opt/gaia-stats
git rev-parse HEAD
systemctl is-enabled gaia-stats-update.timer
systemctl cat gaia-stats.service
systemctl stop gaia-stats-update.timer
backup_dir=$(mktemp -d /var/backups/gaia-rebuilt-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXXXX)
chmod 700 "$backup_dir"
git rev-parse HEAD > "$backup_dir/code-sha"
systemctl cat gaia-stats.service > "$backup_dir/service-before.txt"
if test -d /etc/systemd/system/gaia-stats.service.d; then
  cp -a /etc/systemd/system/gaia-stats.service.d "$backup_dir/"
fi
tar -C /var/lib -czf "$backup_dir/data.tar.gz" gaia-stats
sha256sum "$backup_dir/data.tar.gz"
```

Transfer the verified seed SQLite, original CSVs, classic cache (including its
current pointer and Plotly asset), and raw archive/checkpoint to newly staged
external directories. Preserve any existing archive: do not overwrite it with a
smaller local archive. Resolve overlaps by ID/hash before merging. Required paths:

- `/var/lib/gaia-stats/seeds/base.sqlite` and original source CSVs
- `/var/lib/gaia-stats/classic-cache/`
- `/var/lib/gaia-stats/archive/`
- `/var/lib/gaia-stats/releases-store/`

These directories and files must be readable by `gaia-stats`; archive and release
store must be writable by it (directories 0750, ordinary data files 0640, owner
`gaia-stats:gaia-stats`). Do not recursively change unrelated paths. Verify the
reviewed source SHA and dependency installation before proceeding.

```sh
sudo -u gaia-stats .venv/bin/python -m gaia_stats.releases --root /var/lib/gaia-stats/releases-store --seed-base /var/lib/gaia-stats/seeds/base.sqlite --archive /var/lib/gaia-stats/archive --legacy /var/lib/gaia-stats/analysis.json --dry-run
# Inspect counts, hashes and exclusions before publishing the pointer.
sudo -u gaia-stats .venv/bin/python -m gaia_stats.releases --root /var/lib/gaia-stats/releases-store --seed-base /var/lib/gaia-stats/seeds/base.sqlite --archive /var/lib/gaia-stats/archive --legacy /var/lib/gaia-stats/analysis.json
sudo -u gaia-stats .venv/bin/python deploy/check-rebuilt.py --root /var/lib/gaia-stats/releases-store --cache /var/lib/gaia-stats/classic-cache
install -d -m 0755 /etc/systemd/system/gaia-stats.service.d
install -m 0644 deploy/units/gaia-stats-rebuilt.conf /etc/systemd/system/gaia-stats.service.d/rebuilt.conf
install -m 0644 deploy/units/gaia-stats-data-refresh.service /etc/systemd/system/
install -m 0644 deploy/units/gaia-stats-data-refresh.timer /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/gaia-stats-data-refresh.service /etc/systemd/system/gaia-stats-data-refresh.timer
systemctl daemon-reload
systemctl restart gaia-stats
.venv/bin/python deploy/verify-health.py "$(git rev-parse HEAD)"
```

The preflight MUST run as `gaia-stats`, before switching services: root readability
is insufficient. It validates SQLite, manifests, both catalogues, statistics and
the Plotly asset. The post-restart verifier checks both Gunicorn and Nginx, expected
commit, rebuilt root, Plotly and full cohort counts (no full CSV download).
One worker/four threads is intentional: measured full-base CSV requests reached
1.13 GiB; the service has 1.5 GiB soft/1.8 GiB hard limits and 90-second timeout.

Only after these checks pass, and the timer stage is approved, run one refresh,
inspect its health freshness/checkpoint/counts, then enable scheduling and restore
the original code timer state:

```sh
systemctl start gaia-stats-data-refresh.service
systemctl status gaia-stats-data-refresh.service --no-pager
curl --fail http://127.0.0.1:8000/healthz
systemctl enable --now gaia-stats-data-refresh.timer
systemctl start gaia-stats-update.timer
```

Base coverage is the historical seed plus accepted raw exports; full base backfill
is not claimed complete. LF counts include all accepted public discoveries and
preserved prior records. Rejections/provenance live in the archive database/files.

## Rollback

Pause both timers and stop any running refresh before reverting. For a data-only
rollback select a recorded validated generation; no data files are deleted:

```sh
systemctl stop gaia-stats-data-refresh.timer gaia-stats-data-refresh.service gaia-stats-update.timer
sudo -u gaia-stats .venv/bin/python -m gaia_stats.releases --root /var/lib/gaia-stats/releases-store --seed-base /var/lib/gaia-stats/seeds/base.sqlite --archive /var/lib/gaia-stats/archive --rollback RELEASE_NAME
```

For the first migration rollback, restore the recorded code SHA and prior service
configuration. If `rebuilt.conf` was newly introduced, remove only that new file;
otherwise restore its backup. Reload systemd and restart the app. The untouched
legacy `analysis.json` remains available. Verify old commit and old dataset counts
before restoring the prior timer state. Keep failed candidate data for diagnosis;
do not restore the whole backup over newer data without reconciliation.

## Local validation boundary

Unit tests mock network, systemd and permissions where needed. Full-size dry-run
publication and local preflight use real seed/archive data. Mac checks do not prove
Linux systemd parsing or actual `gaia-stats` account access; the explicit on-VPS
preflight and systemd validation above remain mandatory before rollout.

## Bounded base-request computation

Base statistics and filtered CSV exports decode at most 1,024 observations plus
one game's boundary at a time. Complete games stay together, so per-cell distinct
game counts add correctly. Each batch uses the reference statistics implementation;
means are merged with observation weights and `math.fsum`, with only floating-point
roundoff differences (regression tolerance 1e-10). Filter selection, cohort identity,
rank counts, frequencies, missing-value treatment and comparison denominators are
unchanged. Point-source quartiles/minimum/maximum are computed from the exact
selected values, not an approximate sketch. No displayed outlier detail is removed;
the existing API raw-value limit of 2,000 observations remains unchanged.

Requests retain scalar summaries and point-source arrays rather than the complete
nested dataset. JSON result caches remain limited to eight entries/16 MiB and tied
to the data version. All generations in a worker share the expensive-work lock,
including activation validation. The running code SHA is captured at worker startup
and stays fixed across data refreshes. An interruption after atomic publication never
deletes the possibly published generation; uncertain pointer reads retain it safely.
