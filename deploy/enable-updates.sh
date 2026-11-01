#!/usr/bin/env bash
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
    echo 'Run with sudo.' >&2
    exit 1
fi

cat > /etc/systemd/system/gaia-stats-update.service <<'SERVICE'
[Unit]
Description=Deploy committed Gaia Stats updates
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/gaia-stats
ExecStart=/bin/bash /opt/gaia-stats/deploy/update-vps.sh
TimeoutStartSec=10min
SERVICE

cat > /etc/systemd/system/gaia-stats-update.timer <<'TIMER'
[Unit]
Description=Check for Gaia Stats updates every two minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=2min
Unit=gaia-stats-update.service

[Install]
WantedBy=timers.target
TIMER

systemctl daemon-reload
# Leave polling stopped if bootstrap validation fails.
systemctl stop gaia-stats-update.timer
bash /opt/gaia-stats/deploy/update-vps.sh --bootstrap
systemctl enable --now gaia-stats-update.timer
echo 'Automatic updates enabled. Status: systemctl status gaia-stats-update.timer'
