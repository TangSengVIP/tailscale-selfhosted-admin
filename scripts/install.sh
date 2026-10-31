#!/bin/sh
# Installs only this admin panel; does not install or reconfigure Headscale.
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Run as root.' >&2; exit 1; }
id headscale >/dev/null 2>&1 || { echo 'Install Headscale and create its service user first.' >&2; exit 1; }
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
install -d -o root -g headscale -m 750 /opt/headscale-admin
install -d -o headscale -g headscale -m 700 /etc/headscale-admin
for asset in server.py index.html app.js style.css; do
    install -o root -g headscale -m 640 "$project_dir/src/$asset" "/opt/headscale-admin/$asset"
done
if [ ! -f /etc/headscale-admin/admin.env ]; then
    install -o root -g headscale -m 640 "$project_dir/deploy/admin.env.example" /etc/headscale-admin/admin.env
fi
install -o root -g root -m 644 "$project_dir/deploy/headscale-admin.service" /etc/systemd/system/headscale-admin.service
python3 -m py_compile /opt/headscale-admin/server.py
systemctl daemon-reload
printf '%s\n' 'Installed. Configure admin.env, create auth.json, configure HTTPS, then enable headscale-admin.'
