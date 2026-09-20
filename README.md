# AI Options Deathmatch

A planned public competition between AI-driven options strategies using **paper trading**. Five bots will start with equal virtual capital and rules, trade through a dedicated shared Alpaca paper account, and publish their full results, including losses and eliminated strategies.

**Current state:** V1 planning; no live competition or deployed website yet.

Read the [V1 architecture and launch plan](V1_LAUNCH_PLAN.md) for the shared-account attribution rules, 1 GB VPS target, initial competition rules, and launch gates.

The broker account is an execution pool. Each competitor's cash, positions, and performance are tracked separately in the application. Results must never be represented as real-money performance.
