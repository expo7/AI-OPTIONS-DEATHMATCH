# AI Options Deathmatch — source of truth

Updated 2026-09-20. Owner: Brendan. Repository: `expo7/AI-OPTIONS-DEATHMATCH`.

## Current status

The first code slice is a preparation page and health endpoint. No competition trades, Alpaca integration, analytics, or public deployment are confirmed. Server provisioned separately from Quantelle: Ubuntu 24.04 on a 1 CPU / 1 GB Linode at `172.236.226.103`; laptop SSH key and a dedicated `deploy` login tested. Firewall is configured separately; verify its active rules before deploying.

## Decisions

- Five bots, same starting virtual capital and opportunity set; one dedicated Alpaca paper account as execution pool; separate per-bot ledgers.
- Serialize by exact option contract; reconcile broker aggregate positions to bot allocations; preserve rejected and blocked decisions.
- Begin with a lightweight server and upgrade only on observed resource pressure.
- Exact commit deployment, internal and public health checks; no secrets in Git.

See `V1_LAUNCH_PLAN.md` for the full V1 contract. Current next action: verify a harmless release on the new Linode, then implement one bot's paper order through attribution and reconciliation. Do not infer the presence of broker credentials or a running contest from this document.
