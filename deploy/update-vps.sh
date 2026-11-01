#!/usr/bin/env bash
# Root-owned, app-scoped deployment job invoked by systemd.
set -euo pipefail
cd /opt/gaia-stats
status_path=/var/lib/gaia-stats/deploy-status.json
previous="$(git rev-parse HEAD)"
changed=0

write_status() {
    python3 - "$status_path" "$1" <<'PY'
import datetime,json,os,sys,tempfile
destination,state=sys.argv[1:]
with tempfile.NamedTemporaryFile(mode='w',dir=os.path.dirname(destination),delete=False) as handle:
    json.dump({'state':state,'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},handle)
    temporary=handle.name
os.chmod(temporary,0o644)
os.replace(temporary,destination)
PY
}

on_failure() {
    trap - ERR
    if [[ "$changed" == 1 ]]; then
        # Only reached after verifying a clean tracked checkout before deployment.
        git reset --hard "$previous"
        .venv/bin/pip install -r requirements-web.txt || true
        systemctl restart gaia-stats || true
        write_status rolled-back
    else
        write_status failed
    fi
    exit 1
}
trap on_failure ERR

# Never discard local edits or merge a rewritten branch automatically.
test -z "$(git status --porcelain --untracked-files=no)"
git fetch origin main
git merge-base --is-ancestor HEAD origin/main
if [[ "$previous" == "$(git rev-parse origin/main)" ]]; then
    write_status up-to-date
    exit 0
fi
changed=1
git merge --ff-only origin/main
.venv/bin/pip install -r requirements-web.txt
runuser -u gaia-stats -- .venv/bin/python -m unittest discover -s tests
systemctl restart gaia-stats
curl --fail --silent --show-error --retry 15 --retry-all-errors --retry-delay 2 http://127.0.0.1:8000/healthz
write_status deployed
