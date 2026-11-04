#!/usr/bin/env bash
# Root-owned, app-scoped deployment job invoked by systemd.
set -Eeuo pipefail
case "${1:-}" in
    '') bootstrap=0 ;;
    --bootstrap) bootstrap=1 ;;
    *) echo 'Usage: update-vps.sh [--bootstrap]' >&2; exit 2 ;;
esac
cd /opt/gaia-stats
# Serialize timer, bootstrap and manual invocations before reading Git state.
exec 9>/run/lock/gaia-stats-update.lock
flock -n 9 || { echo 'Another Gaia Stats update is running.' >&2; exit 1; }
# Pin the data bundle once, then serialize against the scheduled refresh for
# the entire update. A legacy install without a release store has no such job.
if [[ -n "${GAIA_DATA_BUNDLE:-}" ]]; then
    data_bundle="$(readlink -f -- "$GAIA_DATA_BUNDLE")"
    data_root="$data_bundle/releases-store"
    data_args=(--bundle "$data_bundle")
else
    data_root="${GAIA_RELEASE_ROOT:-/var/lib/gaia-stats/releases-store}"
    data_args=(--root "$data_root" --seed "${GAIA_SEED_BASE:-/var/lib/gaia-stats/seeds/base.sqlite}" --cache "${GAIA_CLASSIC_CACHE:-/var/lib/gaia-stats/classic-cache}")
fi
if [[ -d "$data_root" ]]; then
    # Never create/truncate an app-owned lock as root: a root-owned new file
    # would prevent the service account from refreshing after this update.
    test -f "$data_root/refresh.lock" || { echo 'Release-store refresh lock is missing; prepare the store as gaia-stats first.' >&2; exit 1; }
    exec 8<"$data_root/refresh.lock"
    flock -n 8 || { echo 'A Gaia Stats data refresh is running; code was not changed.' >&2; exit 1; }
fi
status_path=/var/lib/gaia-stats/deploy-status.json
previous="$(git rev-parse HEAD)"
target="$previous"
changed=0
# Keep this verifier available even if rollback restores code predating it.
verifier="$(mktemp)"
contract_file="$(mktemp)"
trap 'rm -f "$verifier" "$contract_file"' EXIT
cp deploy/verify-health.py "$verifier"

write_status() {
    python3 - "$status_path" "$1" "$previous" "$target" <<'PY'
import datetime,json,os,sys,tempfile
destination,state,previous,target=sys.argv[1:]
with tempfile.NamedTemporaryFile(mode='w',dir=os.path.dirname(destination),delete=False) as handle:
    json.dump({'state':state,'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'previous_commit':previous,'target_commit':target},handle)
    temporary=handle.name
os.chmod(temporary,0o644)
os.replace(temporary,destination)
PY
}

on_failure() {
    trap - ERR
    if [[ "$changed" == 1 ]]; then
        # Do not report recovery until dependencies, restart and health all succeed.
        if git reset --hard "$previous" &&
            .venv/bin/pip install -r requirements-web.txt &&
            systemctl restart gaia-stats &&
            python3 "$verifier" "$previous"; then
            write_status rolled-back
        else
            write_status rollback-failed
        fi
    else
        write_status failed
    fi
    exit 1
}
trap on_failure ERR

# An update must not silently seed examples after production data disappears.
test -s /var/lib/gaia-stats/analysis.json
# Never discard local edits or merge a rewritten branch automatically.
test -z "$(git status --porcelain --untracked-files=no)"
git fetch origin main
git merge-base --is-ancestor HEAD origin/main
target="$(git rev-parse origin/main)"
# This guard must be deployed independently BEFORE a target declares a new data
# contract. The already-running old updater cannot protect its own first update.
# Inspect the target without checking it out, and never activate unprepared code.
contract_entry="$(git ls-tree "$target" -- deploy/data-contract.json)"
if [[ -n "$contract_entry" ]]; then
    git show "$target:deploy/data-contract.json" > "$contract_file"
    chmod 0644 "$contract_file"
    runuser -u gaia-stats -- python3 deploy/check-data-contract.py --contract "$contract_file" "${data_args[@]}"
fi
if [[ "$previous" == "$target" && "$bootstrap" == 0 ]]; then
    python3 "$verifier" "$target"
    write_status up-to-date
    exit 0
fi
if [[ "$previous" != "$target" ]]; then
    changed=1
    git merge --ff-only origin/main
fi
.venv/bin/pip install -r requirements-web.txt
runuser -u gaia-stats -- .venv/bin/python -m unittest discover -s tests
systemctl restart gaia-stats
python3 "$verifier" "$target"
if [[ "$changed" == 1 ]]; then
    write_status deployed
else
    write_status bootstrap-verified
fi
