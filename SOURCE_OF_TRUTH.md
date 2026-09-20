# AI Options Deathmatch — source of truth

Updated 2026-09-20. Owner: Brendan. Repository: `expo7/AI-OPTIONS-DEATHMATCH`.

## Current status

First verified public release: preparation page at http://172.236.226.103/ and health endpoint at http://172.236.226.103/healthz. Brendan verified both the browser page and the public health response on 2026-09-20; the health response identified deployed commit `81944f2570685a6d8aa93619f4a27927a4c5fc86`. A manual GitHub Actions release passed at `656b2f014def63cd5de88781b9d6b24136fe0d61`, and the first `master` push release passed at `43fa0870c3e53b41482e94d378ee7f7dfb97f2fd` (GitHub Actions run 35502180586). These are historical verified releases; verify live before operational claims. No competition trades, Alpaca integration, analytics, domain, or TLS yet.

Server: independent Ubuntu 24.04, 1 CPU / 1 GB Linode at `172.236.226.103`, hostname `ai-options-deathmatch`. Laptop SSH key and dedicated `deploy` login tested. Caddy serves HTTP on port 80 and forwards to the loopback app. Firewall is separate from Quantelle. Initial bootstrap ran successfully after fixing Git ownership checks and adding bounded startup health retries.

## Decisions

- Five bots, same starting virtual capital and opportunity set; one dedicated Alpaca paper account as execution pool; separate per-bot ledgers.
- Serialize by exact option contract; reconcile broker aggregate positions to bot allocations; preserve rejected and blocked decisions.
- Begin with a lightweight server and upgrade only on observed resource pressure.
- Exact commit deployment, internal and public health checks; no secrets in Git. CI now tests and deploys every `master` push through the dedicated `deploy` identity, then verifies internal and public routes.

See `V1_LAUNCH_PLAN.md` for the full V1 contract. The repository now contains a tested, standalone SQLite ledger for per-bot cash and holdings, idempotent broker fill attribution, per-contract unresolved-order exclusion, and aggregate position reconciliation. It is not connected to the web process or Alpaca, creates no production database, and places no trades. Brendan saved dedicated paper credentials on the new server in a root-only file; their validity has not been checked and they are not loaded by the site. Next: add read-only paper-account validation and broker event ingestion, then explicitly test same-contract conflicts. Public results must continue to disclose that no competition trades have begun until the experiment actually runs.
