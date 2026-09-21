# Operations runbook

## Current release

The public service serves the arena, leaderboard, methodology, bot profiles, and `/healthz` through a local Python process. It contains no broker credentials and cannot submit orders. Broker diagnostics, ledger tools, and the disabled paper-submission boundary are separate operator modules that the web process does not import.

## Server setup (new Deathmatch Linode only)

Install `git`, `python3`, and `caddy`. Clone the repository to `/opt/ai-options-deathmatch` as `deploy`. Install `deploy/deathmatch.service` under `/etc/systemd/system/` and an IP or domain-specific Caddyfile under `/etc/caddy/Caddyfile`. Restrict the application to loopback port 8000. Keep inbound firewall rules scoped to 22, 80, and 443. Do not change Quantelle's server.

## Release checks

Run `python3 -m unittest discover -s tests` on the intended revision. Refuse a dirty production worktree. Set `APP_COMMIT` in `/etc/ai-options-deathmatch.env` to the exact deployed SHA, restart the service, verify `curl -fsS http://127.0.0.1:8000/healthz`, then check the public IP or domain through the proxy. Confirm the health response commit matches the revision. Back up any database before applying future schema migrations.

## Recovery

Use `systemctl status deathmatch` and `journalctl -u deathmatch` for the app, and `systemctl status caddy` for the proxy. Redeploy the last known-good commit rather than editing production files. Application rollback and future database recovery are separate operations.

## Automated releases

The workflow deploys verified `master` pushes and supports manual dispatch. A dedicated CI SSH identity is installed and verified. On the VPS, checkout the approved revision and run `bash deploy/install-release.sh` as root to install the root-owned guarded release command. This is a one-time setup. It refuses an unexpected hostname or checkout owner.

Create a dedicated Ed25519 keypair for this repository's GitHub Actions identity. Add only the public key to `/home/deploy/.ssh/authorized_keys` on this VPS; store a single-line Base64 encoding of the private key only in GitHub's `production` environment secret `PROD_SSH_KEY_B64`. Add environment secrets `PROD_HOST=172.236.226.103`, `PROD_USER=deploy`, and `PROD_KNOWN_HOSTS` containing the verified ED25519 host-key line. Verify the key fingerprint independently against the first trusted SSH connection before saving it; never accept a fresh key blindly inside CI. Do not use Quantelle's key or secrets. Trigger the workflow manually once, verify both public routes and commit, then enable `push` on `master` after success.

The root-owned release command refuses a dirty checkout, non-SHA input, and commits absent from `origin/master`; it serializes releases and checks the new internal health endpoint. The workflow independently checks the public routes. A failed health check does not automatically roll back data or code; diagnose and redeploy a known-good commit after confirming compatibility.

## Per-bot ledger (not activated yet)

`ledger.py` is a standard-library SQLite accounting component. It initializes a database only when explicitly called; importing the module or deploying the website does not create one or submit orders. Use integer cents for cash and per-share option premiums, and contract units for quantities. Reserve by unique client order ID, attach the broker order ID upon acceptance, and attribute fills by unique broker fill ID. Replayed identical events are no-ops; conflicting replays fail. A symbol with an unresolved order cannot accept another order. Reconcile the sum of bot holdings with the broker's entire position map and review negative virtual cash before permitting another order. Persist the eventual production database outside the Git worktree, back it up off-server, and test restore before enabling trading.

## Read-only paper account check

After deploying `alpaca_readonly.py`, the operator may run `python3 /opt/ai-options-deathmatch/alpaca_readonly.py --env-file /etc/ai-options-deathmatch/alpaca.env` as root on the Deathmatch VPS. The command accepts only the exact `https://paper-api.alpaca.markets` endpoint, reads a root-only credential file, performs GET requests for account, positions, open orders (up to 500, refusing a full page), and up to 100 recent fill activities, and prints only status and counts. It does not cancel orders or liquidate positions; inventory and flattening must be verified before Generation 1 starts. It does not print keys or account identifiers, place orders, initialize a database, or modify the website service. If recent fills equal 100, history may be longer; do not treat that count as a complete audit. Do not load broker credentials into the web service until ingestion, reconciliation, and order controls are implemented and reviewed.

## Launch-readiness report

Run the phase-aware read-only check as root:

```bash
python3 /opt/ai-options-deathmatch/launch_readiness.py \
  --env-file /etc/ai-options-deathmatch/alpaca.env \
  --ledger /var/lib/ai-options-deathmatch/ledger.sqlite3
```

The command prints only Boolean gates and the generation number. It never prints symbols, positions, orders, account identifiers, or credentials. A missing ledger may still produce `safe_to_initialize: true` when the paper account is active and flat. Initialize Generation 1 only in that state. After initialization, require `safe_to_record_baseline: true` before recording the immutable zero-position/zero-order baseline. `execution_ready: true` requires every gate, including the baseline and reconciliation. The ledger, when present, is opened using SQLite read-only mode. Exit codes are 0 for execution-ready, 1 for a valid but incomplete preflight, and 2 for a diagnostic error.

## Supervised launch cycle

Stage an operator-reviewed JSON plan without broker contact:

```bash
python3 competition_operator.py stage /root/first-cycle.json
```

Only after reviewing the returned tagged client order ID, submit that reservation to the paper endpoint:

```bash
python3 competition_operator.py submit CLIENT_ORDER_ID --confirm ENABLE_DEATHMATCH_PAPER_ORDERS
```

Synchronize post-baseline fills explicitly:

```bash
python3 competition_operator.py sync
```

After synchronization, record a common broker mark and atomically publish the sanitized standings file:

```bash
python3 competition_operator.py mark
```

The public web process reads only `/var/lib/ai-options-deathmatch-public/results.json`. It receives no broker credentials and has no access to the operational ledger.

Install the root-only five-minute updater once after deployment:

```bash
sudo bash deploy/install-operations.sh
```

The timer checks Alpaca's market clock and exits without touching the ledger when the market is closed. While open, it synchronizes attributed fills before recording and publishing a common mark. It never stages decisions or submits, replaces, or cancels orders.

The launch cycle permits at most one buy. It requires all five decisions, forces the cash benchmark to decline, checks expiry, open interest, volume, spread, premium, and exact frozen-ask pricing, and fails closed if broker inventory or local attribution does not reconcile.
