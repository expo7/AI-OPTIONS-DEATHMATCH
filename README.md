# AI Options Deathmatch

A planned public competition between AI-driven options strategies using **paper trading**. Five bots will start with equal virtual capital and rules, trade through a dedicated shared Alpaca paper account, and publish their full results, including losses and eliminated strategies.

**Current state:** The [public preparation page](http://172.236.226.103/) is online. No competition trades have begun. The first release was verified at commit `81944f2570685a6d8aa93619f4a27927a4c5fc86` on 2026-09-20.

Read the [V1 architecture and launch plan](V1_LAUNCH_PLAN.md) for shared-account attribution, the 1 GB VPS target, rules, and launch gates. [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md) tracks verified state and next work.

The broker account is an execution pool. Each competitor's cash, positions, and performance will be tracked separately in the application. Results must never be represented as real-money performance.

Generation 1 strategy and portfolio rules are versioned in `generation_one.py`. `init_generation.py` creates the five equal-capital competitors and freezes their rules in the append-only ledger. Opportunity snapshots and public bot decisions are immutable: corrections require a new identified record rather than rewriting history. This decision layer does not contact Alpaca or submit orders.

## First release

The public site uses Python's standard library and Caddy; it contains no trading integration. Its leaderboard can read immutable equity snapshots from the competition ledger through a read-only SQLite connection, but results remain hidden unless `RESULTS_PUBLIC=true` and `LEDGER_PATH` explicitly identifies the ledger. The web process cannot initialize or mutate that database.

Run `python3 -m unittest discover -s tests` to check public routes and accounting behavior. `deploy/bootstrap-server.sh` provisions and internally verifies the service on the dedicated Linode. Production releases use an automated exact-revision workflow.
