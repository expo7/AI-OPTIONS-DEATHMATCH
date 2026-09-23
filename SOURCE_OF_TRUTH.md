# AI Options Deathmatch — source of truth

Updated 2026-09-21. Owner: Brendan. Repository: `expo7/AI-OPTIONS-DEATHMATCH`.

Generation 1 is active in Alpaca paper trading. The flat launch baseline was
recorded at 2026-09-21T16:43:32.071542Z. Trend Rider's first attributed order,
one QQQ261009C00745000 contract, filled and reconciled. A five-minute systemd
timer synchronizes fills and publishes common marks; lifecycle thresholds create
alerts but do not automatically sell. Opening and closing submissions remain
supervised and require the explicit paper-only confirmation token.

The next operating layer is now a supervised decision queue. A reviewed shared
market snapshot can be recorded once, each of the five contenders can append one
immutable decision, and queue status exposes missing responses. A complete queue
can be assembled for review or staged into the existing attributed reservation
flow, but the queue cannot contact Alpaca or submit an order.

Automated market discovery and decision generation are now implemented, code
reviewed, and unit tested, but **not yet verified against live Alpaca
endpoints** (this sandbox has no network access or live credentials). A new
GET-only `market_data.py` adapter reads daily bars, latest trade price, and
options-chain snapshots from Alpaca's market data API using the same paper
key/secret; it fails closed (abstains) on any missing or malformed field,
including `openInterest`, whose presence in this account's actual options
snapshot response has not been confirmed live. Five per-bot strategies in
`strategies.py` (trend, reversal, breakout, catalyst, cash) independently
evaluate a shared daily-bar/option-chain snapshot; catalyst and cash always
decline honestly since no dated public catalyst feed exists. A new
`autonomous_entries.py` script, run by its own systemd timer
(`deathmatch-entries.timer`, every 30 minutes, independent of the existing
5-minute fill/mark/exit timer) builds one shared, idempotent, time-bucketed
opportunity per cadence window, lets every bot propose independently, applies
the existing `max_open_positions` cap and the existing single-buy-per-cycle
rule via a deterministic rotation if more than one bot wants to buy, and
stages (and attempts to submit) the result through the unchanged
`stage_plan`/`submit` gates. **Remaining blocker before this can run
unattended in production:** confirm live, against the real Alpaca paper
account, that the options snapshot endpoint actually returns usable
`latestQuote`/`dailyBar`/`openInterest` data for the configured data
entitlement; if it does not, every cycle will simply decline for lack of a
valid contract (fail closed, not fail dangerous), but the goal of routine
autonomous trades will not be met until that entitlement is confirmed or the
data source is adjusted.

## Current status

First verified public release: preparation page at http://172.236.226.103/ and health endpoint at http://172.236.226.103/healthz. Brendan verified both the browser page and the public health response on 2026-09-20; the health response identified deployed commit `81944f2570685a6d8aa93619f4a27927a4c5fc86`. A manual GitHub Actions release passed at `656b2f014def63cd5de88781b9d6b24136fe0d61`, and the first `master` push release passed at `43fa0870c3e53b41482e94d378ee7f7dfb97f2fd` (GitHub Actions run 35502180586). These are historical verified releases; verify live before operational claims. No competition trades, Alpaca integration, analytics, domain, or TLS yet.

Server: independent Ubuntu 24.04, 1 CPU / 1 GB Linode at `172.236.226.103`, hostname `ai-options-deathmatch`. Laptop SSH key and dedicated `deploy` login tested. Caddy serves HTTP on port 80 and forwards to the loopback app. Firewall is separate from Quantelle. Initial bootstrap ran successfully after fixing Git ownership checks and adding bounded startup health retries.

## Decisions

- Five bots, same starting virtual capital and opportunity set; one dedicated Alpaca paper account as execution pool; separate per-bot ledgers.
- Serialize by exact option contract; reconcile broker aggregate positions to bot allocations; preserve rejected and blocked decisions.
- Begin with a lightweight server and upgrade only on observed resource pressure.
- Exact commit deployment, internal and public health checks; no secrets in Git. CI now tests and deploys every `master` push through the dedicated `deploy` identity, then verifies internal and public routes.

See `V1_LAUNCH_PLAN.md` for the full V1 contract. The repository contains a tested standalone SQLite ledger for per-bot cash and holdings, idempotent fill attribution, per-contract unresolved-order exclusion, aggregate position reconciliation, and immutable mark-to-market equity snapshots. Generation 1 now has versioned common risk limits and five strategy rulesets. The initialization command freezes each configuration in the ledger. Timestamped market opportunities and each bot's buy-or-decline decision are append-only, limited to one decision per bot per opportunity, and retain a concise public rationale without private model reasoning. Each reserved competition order can be atomically linked to the exact buy decision whose bot, contract, quantity, and limit price it matches. The GET-only diagnostic adapter can validate an Alpaca acceptance against that reservation and synchronize every fill page after an explicit launch baseline. Fill synchronization processes oldest-first, is idempotent, rejects unknown or inconsistent activity, and fails closed on duplicate tokens, malformed pages, or a safety-bound overrun. A separate paper submission module now exists but is deliberately unwired: it has no CLI and is not imported by the web service. It permits only tagged, decision-linked opening buys and requires the exact enable token, an immutable zero-position/zero-order baseline, an active unblocked paper account, no current broker orders, and complete position reconciliation before POSTing the reserved terms. It has been tested only with fake broker responses and has never been invoked against Alpaca. A sanitized launch-readiness command now checks the live paper account and optional ledger without mutation. It reports Boolean gates for safe initialization, safe baseline recording, and execution readiness; it opens the ledger read-only and prints no account identifiers, symbols, positions, or orders. The website can publish recent decisions with performance data. A read-only publication layer calculates return, maximum drawdown, and closed-trade count from snapshots. The website publishes this data only when `RESULTS_PUBLIC=true` and a ledger path are explicitly configured; the web process cannot create or mutate the ledger. The read-only paper credential check on 2026-09-20 returned ACTIVE status, options trading level 3, 23 open positions, and 100 recent fill activities (the page maximum, so total history is unknown). Brendan will retain this existing paper account and its historical approximately $6.8 million paper balance; no account reset is required. Its prior return and activities are excluded from all competitor results. Before Generation 1, record a timestamped broker baseline, ensure no other system (including Quantelle) is actively using this account, resolve open orders, and flatten existing positions if this account is exclusively available for the competition. Verify zero broker positions and open orders before starting the equal per-bot virtual ledgers; attribute only competition-tagged orders and post-launch fills. Quantelle uses a separate account. On 2026-09-20, a one-time paper closeout requested exits for 23 legacy positions; 15 equity sell orders were accepted and remained pending, seven long-option and one short-option close attempts were rejected. A one-time read-only inventory is scheduled on the Deathmatch VPS for 2026-09-21 13:45 UTC. Do not repeat the bulk closeout while orders remain open; review the timer output and resolve the remaining options individually. The broker account's history is retained; no competition orders have been placed. Credentials remain in a root-only file and are not loaded by the web service. The site now provides a pre-launch arena, an honest empty leaderboard, a methodology page, and stable profile URLs for four AI strategy candidates and a deterministic cash benchmark. Each contender is planned for $10,000 virtual starting capital. Unstarted return and drawdown values remain unavailable rather than appearing as fabricated zero performance. No results are published until trades occur. Next: finish legacy closeout, run the readiness command, record and verify the flat launch baseline, then run one controlled end-to-end decision-to-fill test.
