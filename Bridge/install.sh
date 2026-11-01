#!/bin/sh
# Run as root on the CLIProxyAPI host after provisioning management.key there.
set -eu
cd "$(dirname "$0")"
test "$(id -u)" = 0 || { echo "Run this installer as root." >&2; exit 1; }
test -s /etc/tinybar-bridge/management.key || {
    echo "Provision /etc/tinybar-bridge/management.key on this host first." >&2
    exit 1
}
python3 -c 'import tomllib'
getent passwd tinybar-bridge >/dev/null || useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin tinybar-bridge
install -d -m 0755 /opt/tinybar-bridge
install -m 0644 claude_accounts.py /opt/tinybar-bridge/claude_accounts.py
chown root:tinybar-bridge /etc/tinybar-bridge
chmod 0750 /etc/tinybar-bridge
chown root:tinybar-bridge /etc/tinybar-bridge/management.key
chmod 0640 /etc/tinybar-bridge/management.key
if test ! -f /etc/tinybar-bridge/config.toml; then
    install -m 0640 -o root -g tinybar-bridge config.example.toml /etc/tinybar-bridge/config.toml
fi
install -m 0644 tinybar-bridge.service /etc/systemd/system/tinybar-bridge.service
systemd-analyze verify /etc/systemd/system/tinybar-bridge.service
systemctl daemon-reload
systemctl enable tinybar-bridge.service
systemctl restart tinybar-bridge.service
systemctl is-active tinybar-bridge.service
