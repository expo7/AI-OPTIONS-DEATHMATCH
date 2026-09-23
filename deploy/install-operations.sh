#!/usr/bin/env bash
set -euo pipefail

[[ $(id -u) -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
[[ $(hostname) == ai-options-deathmatch ]] || { echo 'Unexpected server hostname' >&2; exit 1; }
[[ $(pwd -P) == /opt/ai-options-deathmatch ]] || { echo 'Unexpected repository path' >&2; exit 1; }
[[ -f /etc/ai-options-deathmatch/alpaca.env ]] || { echo 'Paper credential file is missing' >&2; exit 1; }
[[ $(stat -c %a /etc/ai-options-deathmatch/alpaca.env) == 600 ]] || { echo 'Paper credential file must be mode 600' >&2; exit 1; }
[[ -f /var/lib/ai-options-deathmatch/ledger.sqlite3 ]] || { echo 'Competition ledger is missing' >&2; exit 1; }

install -o root -g root -m 644 deploy/deathmatch-update.service /etc/systemd/system/deathmatch-update.service
install -o root -g root -m 644 deploy/deathmatch-update.timer /etc/systemd/system/deathmatch-update.timer
install -o root -g root -m 644 deploy/deathmatch-entries.service /etc/systemd/system/deathmatch-entries.service
install -o root -g root -m 644 deploy/deathmatch-entries.timer /etc/systemd/system/deathmatch-entries.timer
install -d -o root -g root -m 755 /var/lib/ai-options-deathmatch-public
systemctl daemon-reload
systemctl enable --now deathmatch-update.timer
systemctl start deathmatch-update.service
systemctl is-active --quiet deathmatch-update.timer
systemctl enable --now deathmatch-entries.timer
systemctl is-active --quiet deathmatch-entries.timer
echo 'Competition update and entry timers installed and active'
