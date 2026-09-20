# Operations runbook

## Current release

The first release serves `/` and `/healthz` through a local Python process. It contains no trading logic or secret material.

## Server setup (new Deathmatch Linode only)

Install `git`, `python3`, and `caddy`. Clone the repository to `/opt/ai-options-deathmatch` as `deploy`. Install `deploy/deathmatch.service` under `/etc/systemd/system/` and an IP or domain-specific Caddyfile under `/etc/caddy/Caddyfile`. Restrict the application to loopback port 8000. Keep inbound firewall rules scoped to 22, 80, and 443. Do not change Quantelle's server.

## Release checks

Run `python3 -m unittest discover -s tests` on the intended revision. Refuse a dirty production worktree. Set `APP_COMMIT` in `/etc/ai-options-deathmatch.env` to the exact deployed SHA, restart the service, verify `curl -fsS http://127.0.0.1:8000/healthz`, then check the public IP or domain through the proxy. Confirm the health response commit matches the revision. Back up any database before applying future schema migrations.

## Recovery

Use `systemctl status deathmatch` and `journalctl -u deathmatch` for the app, and `systemctl status caddy` for the proxy. Redeploy the last known-good commit rather than editing production files. Application rollback and future database recovery are separate operations.

## Automated releases (preparation)

The workflow is manual-only until a dedicated CI SSH identity is installed and verified. On the VPS, checkout the approved revision and run `bash deploy/install-release.sh` as root to install the root-owned guarded release command. This is a one-time setup. It refuses an unexpected hostname or checkout owner.

Create a dedicated Ed25519 keypair for this repository's GitHub Actions identity. Add only the public key to `/home/deploy/.ssh/authorized_keys` on this VPS; store a single-line Base64 encoding of the private key only in GitHub's `production` environment secret `PROD_SSH_KEY_B64`. Add environment secrets `PROD_HOST=172.236.226.103`, `PROD_USER=deploy`, and `PROD_KNOWN_HOSTS` containing the verified ED25519 host-key line. Verify the key fingerprint independently against the first trusted SSH connection before saving it; never accept a fresh key blindly inside CI. Do not use Quantelle's key or secrets. Trigger the workflow manually once, verify both public routes and commit, then enable `push` on `master` after success.

The root-owned release command refuses a dirty checkout, non-SHA input, and commits absent from `origin/master`; it serializes releases and checks the new internal health endpoint. The workflow independently checks the public routes. A failed health check does not automatically roll back data or code; diagnose and redeploy a known-good commit after confirming compatibility.
