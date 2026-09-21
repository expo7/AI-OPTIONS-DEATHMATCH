# AI Options Deathmatch — V1 launch plan

**Status:** Planning. No live competition or deployed site is claimed by this document.

## Goal

Run five distinct options-trading bots in a public, auditable paper-trading competition. Each bot starts with the same virtual capital, rules, market snapshot, and contract universe. Publish every decision, fill, loss, and elimination. Measure visitor acquisition from day one.

## Confirmed product decisions

- Repository: `expo7/AI-OPTIONS-DEATHMATCH`; existing default branch: `master`. Choose a canonical production branch before configuring deployment.
- The existing Alpaca paper account acts as the execution pool after exclusive-use verification and a timestamped launch baseline. Preserve its approximately $6.8 million historical paper balance and trading history; no reset is required. The broker balance is capacity, never a competitor's score. Resolve legacy open orders and flatten legacy positions before launch if this account is exclusively available; never close Quantelle or another active strategy's positions. Never connect a live account by default.
- The application owns separate virtual cash, positions, equity, and drawdown for each bot. Broker order and fill events, linked by unique client order IDs, are the execution evidence.
- Start on a 1 vCPU / 1 GB RAM VPS and measure actual headroom before upgrading. Use a simple runtime rather than copying Quantelle's full stack.
- The public site must label all results paper trading and disclose the shared-account accounting model.

## Shared-account execution invariant

Alpaca reports one aggregate account position per option contract. Two bots holding the same contract are therefore distinguishable only through our order/fill ledger. Serialize operations per exact option symbol (underlying + expiry + call/put + strike). Submit no closing quantity beyond that bot's confirmed allocated open quantity. Account for pending orders and partial fills; reconcile the sum of bot quantities against Alpaca's aggregate quantity before new orders. An unexplained difference pauses affected-symbol trading and alerts the operator.

Specifically test: Bot A buys a contract, Bot B buys the same contract, A closes while B remains open, simultaneous opposing pending orders, partial fills, cancellation, and expiry. Do this with clearly labeled test orders in the dedicated paper account before opening Generation 1. If broker handling prevents an action, preserve the decision as `blocked_by_execution` with its reason; do not score it as an executed trade. Distinct call and put contracts on the same underlying do not share a position symbol.

Broker fills are authoritative for execution; the per-bot ledger is authoritative for competitor attribution. Never use the paper account's aggregate buying power or equity to rank bots. Reconciliation must include external or unexplained broker activities, not silently allocate them.

## First vertical slice

1. Capture a timestamped opportunity snapshot and fixed bot rules/configuration version.
2. Record one bot decision and validate it against its virtual cash and risk limits.
3. Submit a uniquely tagged order to the paper endpoint.
4. Ingest accepted/rejected/partial/full fill events idempotently; update the bot ledger.
5. Reconcile Alpaca account positions to the sum of attributed bot holdings.
6. Publish the result on the bot profile and leaderboard, with paper-trading disclosure.
7. Repeat for five bots on the same snapshots and rules.

Implemented safety boundary: a proposed order is reserved together with its immutable decision attribution. Broker acceptance is recorded only when Alpaca returns the same client order ID, symbol, side, quantity, limit price, and limit-order type. Fill history is fetched page by page from an explicit post-baseline timestamp, sorted oldest-first, and applied idempotently. Any unattributed fill or incomplete pagination stops synchronization for operator review.

The opening-order submission boundary is implemented but intentionally has no CLI or scheduled caller. It accepts only decision-linked tagged buys, requires an exact paper-execution enable token and immutable flat-account baseline, rechecks account blocks and open orders, and reconciles every broker position before submitting. It remains uninvoked until the launch gates are completed.

## Initial competition rules

Long calls and puts only, liquid approved underlyings, capped premium per position, bounded spread, no same-day expiry, and no obligation to trade. Use fixed virtual starting capital for each bot. Include a simple deterministic baseline. Freeze model/prompt, strategy parameters, data cutoff, contract selection rules, and portfolio rules for the generation. Record concise structured rationales, not hidden model reasoning.

The first frozen implementation uses $10,000 virtual cash per contender, a maximum $1,000 premium per position, at most three open positions, 14–45 days to expiry, limit orders, minimum open interest of 500, minimum contract volume of 100, and a maximum 10% bid/ask spread. These values are versioned in `generation_one.py`; changing them after ledger initialization requires a new version rather than editing the frozen record.

Publish net return, maximum drawdown, closed-trade count, win rate, and time in market. The initial provisional fitness proposal is return minus 0.5 times maximum drawdown, with no elimination before eight trading weeks and 20 closed trades per eligible bot. Freeze the scoring rule before launch; preserve all eliminated bots and losing trades. Do not automatically mutate bots during Generation 1.

## Minimum site and data

Server-rendered leaderboard, bot profile, trade detail/history, methodology, and dated result summaries. Stable shareable URLs and honest metadata. Minimum records: generation, bot, immutable bot version, opportunity snapshot, decision, broker order, broker fill/activity, bot ledger entry, position allocation, equity snapshot, and traffic event. Record source/referrer/UTM, landing pages, bot/trade clicks, and share clicks. Check options-data entitlement and public display terms before launch.

## Small-server stack proposal

Python/Django, SQLite in WAL mode, Caddy, and scheduled idempotent management commands. One small web process; serialize trading jobs with a lock. Build immutable runtime artifacts in CI rather than compiling on the VPS. Back up the database off-server and verify a restore. Add PostgreSQL or a job queue only when measured load, concurrency, or reliability requires them.

## Deployment contract

Follow the [Quantelle-derived deployment blueprint](https://chatgpt.com/api/library/files/libfile_b1d36ee44fb88191abdce526d24f90cd/download): product request → inspect repository → implement and test → deploy exact verified commit → internal health check → public health check. Refuse dirty production state, missing secrets, failed migrations, failed checks, and unexpected service state. Expose deployed commit in a health endpoint. Maintain `README.md`, `AGENTS.md`, `.env.example`, deployment workflow, `OPERATIONS_RUNBOOK.md`, and `SOURCE_OF_TRUTH.md` as implementation begins.

## Launch gates

1. Repository conventions, VPS, domain/TLS, backups, and exact-revision deployment verified by a harmless release.
2. Existing paper account confirmed exclusive, legacy orders resolved, positions flattened, timestamped baseline captured, and options data entitlement validated; no live keys present.
3. Same-contract opposing-order and partial-fill behavior tested; reconciliation passes.
4. One complete paper order → broker fill → attributed ledger → public result verified.
5. Five bots operate from a shared market snapshot and public results update.
6. Traffic events and search indexing verified; run tracked distribution experiments.

No real-money trading, multi-leg/short options, elaborate evolutionary machinery, paid subscriptions, or large frontend/worker stack in V1.
