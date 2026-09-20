#!/usr/bin/env bash
set -euo pipefail

# Run once as root from the checked-out Deathmatch repository on its own VPS.
[[ $(id -u) -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
[[ $(hostname) == ai-options-deathmatch ]] || { echo 'Unexpected server hostname' >&2; exit 1; }
[[ $(pwd -P) == /opt/ai-options-deathmatch ]] || { echo 'Unexpected repository path' >&2; exit 1; }
[[ $(stat -c %U .) == deploy ]] || { echo 'Repository must be owned by deploy' >&2; exit 1; }
[[ -z $(runuser -u deploy -- git status --porcelain) ]] || { echo 'Refusing dirty checkout' >&2; exit 1; }

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y caddy git python3 curl

revision=$(runuser -u deploy -- git rev-parse HEAD)
printf 'APP_COMMIT=%s\n' "$revision" > /etc/ai-options-deathmatch.env
chmod 644 /etc/ai-options-deathmatch.env
install -m 644 deploy/deathmatch.service /etc/systemd/system/deathmatch.service
install -m 644 deploy/Caddyfile.ip /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now deathmatch caddy
systemctl restart deathmatch caddy

ready=false
for attempt in {1..20}; do
    if curl -fsS http://127.0.0.1:8000/healthz 2>/dev/null | grep -Fq "$revision" &&
       curl -fsS http://127.0.0.1/ 2>/dev/null | grep -Fq 'No competition trades have begun'; then
        ready=true
        break
    fi
    sleep 1
done
[[ $ready == true ]] || { echo 'Internal or proxy health check failed after 20 attempts' >&2; exit 1; }
echo "Internal deployment verified: $revision"
