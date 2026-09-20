# Operations runbook

## Current release

The first release serves `/` and `/healthz` through a local Python process. It contains no trading logic or secret material.

## Server setup (new Deathmatch Linode only)

Install `git`, `python3`, and `caddy`. Clone the repository to `/opt/ai-options-deathmatch` as `deploy`. Install `deploy/deathmatch.service` under `/etc/systemd/system/` and an IP or domain-specific Caddyfile under `/etc/caddy/Caddyfile`. Restrict the application to loopback port 8000. Keep inbound firewall rules scoped to 22, 80, and 443. Do not change Quantelle's server.

## Release checks

Run `python3 -m unittest discover -s tests` on the intended revision. Refuse a dirty production worktree. Set `APP_COMMIT` in `/etc/ai-options-deathmatch.env` to the exact deployed SHA, restart the service, verify `curl -fsS http://127.0.0.1:8000/healthz`, then check the public IP or domain through the proxy. Confirm the health response commit matches the revision. Back up any database before applying future schema migrations.

## Recovery

Use `systemctl status deathmatch` and `journalctl -u deathmatch` for the app, and `systemctl status caddy` for the proxy. Redeploy the last known-good commit rather than editing production files. Application rollback and future database recovery are separate operations.
