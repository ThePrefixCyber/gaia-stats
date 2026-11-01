#!/usr/bin/env bash
# Run as root on a fresh Ubuntu 24.04 VPS after cloning this repository.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run with sudo: sudo bash deploy/install-vps.sh" >&2
    exit 1
fi

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$APP_DIR" != /opt/gaia-stats ]]; then
    echo "Clone the repository to /opt/gaia-stats before running this script." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv nginx curl ufw

if ! id gaia-stats >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/gaia-stats --shell /usr/sbin/nologin gaia-stats
fi
install -d -o gaia-stats -g gaia-stats -m 750 /var/lib/gaia-stats
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements-web.txt"

cat > /etc/systemd/system/gaia-stats.service <<'SERVICE'
[Unit]
Description=Gaia Stats opening explorer
After=network.target

[Service]
User=gaia-stats
Group=gaia-stats
WorkingDirectory=/opt/gaia-stats
Environment=GAIA_DATASET=/var/lib/gaia-stats/analysis.json
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/gaia-stats/.venv/bin/gunicorn gaia_stats.wsgi:create_app() --bind 127.0.0.1:8000 --workers 1 --threads 4 --timeout 60 --access-logfile - --error-logfile -
Restart=on-failure
RestartSec=5
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/gaia-stats

[Install]
WantedBy=multi-user.target
SERVICE

cat > /etc/nginx/sites-available/gaia-stats <<'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
NGINX

ln -sfn /etc/nginx/sites-available/gaia-stats /etc/nginx/sites-enabled/gaia-stats
# Remove only Ubuntu's default site symlink; retain other sites/configuration.
if [[ -L /etc/nginx/sites-enabled/default ]]; then
    rm /etc/nginx/sites-enabled/default
fi
nginx -t

# Permit SSH before enabling the firewall so the current connection remains usable.
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

systemctl daemon-reload
systemctl enable --now gaia-stats nginx
systemctl restart gaia-stats
systemctl reload nginx
curl --fail --silent --show-error --retry 15 --retry-connrefused --retry-delay 2 http://127.0.0.1:8000/healthz
curl --fail --silent --show-error http://127.0.0.1/healthz
echo
echo 'Gaia Stats is running. Open http://YOUR_SERVER_IP/ in your browser.'
echo 'Starts with 4 verified example games. Use deploy/pull-games.sh to import more.'
echo 'Logs: journalctl -u gaia-stats -n 50 --no-pager'
