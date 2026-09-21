# Agent instructions

- This repository is independent of Quantelle. Never access, modify, or reuse Quantelle accounts, credentials, servers, or deployment keys.
- Never place Alpaca live credentials in the runtime. `alpaca_submit.py` must remain unwired and uninvoked until the existing paper account is confirmed exclusive to Deathmatch, legacy positions and open orders are resolved, a flat launch baseline is recorded, and per-bot attribution and reconciliation are verified.
- The public site must distinguish preparing state, paper results, and real-money results. Preserve losses and blocked decisions.
- Read `V1_LAUNCH_PLAN.md` and `SOURCE_OF_TRUTH.md` before architectural changes.
- Run `python3 -m unittest discover -s tests` before deploying. Deploy only a verified exact commit, check `/healthz` and `/`, and stop on unexplained production changes.
