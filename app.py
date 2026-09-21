"""Public website for AI Options Deathmatch.

The web process intentionally has no broker credentials and cannot trade.
"""

import json
import os
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from bots import BOTS, STARTING_CASH_CENTS, get_bot
from public_data import load_public_standings


COMMIT = os.getenv("APP_COMMIT", "local")
STARTING_CASH = f"${STARTING_CASH_CENTS / 100:,.0f}"
RESULTS_PUBLIC = os.getenv("RESULTS_PUBLIC", "false").lower() == "true"
LEDGER_PATH = os.getenv("LEDGER_PATH", "")


def published_standings():
    if not RESULTS_PUBLIC or not LEDGER_PATH:
        return {}
    return load_public_standings(LEDGER_PATH)


def money(cents):
    return f"${cents / 100:,.2f}"


def percent(fraction):
    return f"{fraction:+.2%}"


def layout(title, eyebrow, content, description, active=False):
    """Render a complete page with shared navigation and disclosures."""
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{escape(description)}">
<title>{escape(title)} · AI Options Deathmatch</title>
<style>
:root{{--ink:#edf3f8;--muted:#9cabb8;--line:#2c3b4a;--panel:#141e29;--panel2:#192634;--green:#8ff0b4;--blue:#7cc8ff;--bg:#0a1017}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 85% 5%,#172b3c 0,transparent 35%),var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,sans-serif}}
a{{color:inherit}}.wrap{{width:min(1100px,calc(100% - 36px));margin:auto}}nav{{display:flex;align-items:center;justify-content:space-between;padding:22px 0;border-bottom:1px solid var(--line)}}
.brand{{font-weight:800;text-decoration:none;letter-spacing:-.03em}}.brand b{{color:var(--green)}}nav div{{display:flex;gap:22px}}nav div a{{color:var(--muted);text-decoration:none;font-size:.92rem}}nav div a:hover{{color:var(--ink)}}
main{{padding:72px 0 90px}}.eyebrow{{color:var(--blue);font-size:.78rem;font-weight:800;letter-spacing:.15em;text-transform:uppercase}}h1{{font-size:clamp(2.7rem,7vw,5.7rem);line-height:.96;letter-spacing:-.065em;margin:.22em 0 .35em;max-width:850px}}h2{{letter-spacing:-.035em;line-height:1.15}}p{{color:var(--muted);max-width:68ch}}
.lead{{font-size:clamp(1.08rem,2vw,1.3rem)}}.actions{{display:flex;flex-wrap:wrap;gap:12px;margin:30px 0 52px}}.button{{display:inline-block;padding:11px 17px;border:1px solid var(--line);border-radius:8px;text-decoration:none;font-weight:700}}.button.primary{{background:var(--green);border-color:var(--green);color:#08120c}}.button:hover{{transform:translateY(-1px)}}
.notice{{border:1px solid #38566b;border-left:4px solid var(--blue);background:#101d28;padding:20px 22px;border-radius:8px;margin:30px 0}}.notice strong{{color:var(--ink)}}.notice p{{margin:.35em 0 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:15px;margin-top:24px}}.card{{border:1px solid var(--line);border-radius:12px;padding:22px;background:linear-gradient(145deg,var(--panel2),var(--panel));text-decoration:none}}.card:hover{{border-color:#537087}}.card h2{{margin:.18em 0;font-size:1.35rem}}.card p{{font-size:.94rem;line-height:1.48}}.tag{{color:var(--blue);font-size:.72rem;font-weight:800;letter-spacing:.11em;text-transform:uppercase}}.status{{display:inline-flex;align-items:center;gap:7px;color:var(--green);font-size:.8rem;font-weight:700}}.status:before{{content:'';width:7px;height:7px;border-radius:50%;background:var(--green)}}
.section-head{{display:flex;align-items:end;justify-content:space-between;gap:20px;margin-top:65px}}.section-head h2{{font-size:2rem;margin:0}}.section-head a{{color:var(--blue)}}
.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:12px;margin-top:24px}}table{{width:100%;border-collapse:collapse;min-width:720px;background:var(--panel)}}th,td{{padding:16px 18px;text-align:left;border-bottom:1px solid var(--line)}}th{{color:var(--muted);font-size:.73rem;letter-spacing:.1em;text-transform:uppercase}}tbody tr:last-child td{{border-bottom:0}}td.metric{{font-variant-numeric:tabular-nums;color:var(--muted)}}.rank{{color:var(--muted);width:45px}}.bot-link{{font-weight:750;text-decoration:none}}.bot-link:hover{{color:var(--blue)}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:35px 0}}.stat{{border:1px solid var(--line);background:var(--panel);border-radius:10px;padding:18px}}.stat span{{display:block;color:var(--muted);font-size:.75rem;text-transform:uppercase;letter-spacing:.08em}}.stat strong{{font-size:1.35rem}}.rules{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:15px;margin-top:25px}}.rule{{border-top:2px solid var(--line);padding-top:16px}}.rule h2{{font-size:1.08rem;margin:0 0 5px}}.rule p{{margin:0;font-size:.94rem}}
.profile{{display:grid;grid-template-columns:2fr 1fr;gap:40px;align-items:start}}.side{{border:1px solid var(--line);background:var(--panel);padding:22px;border-radius:12px}}.side dl{{margin:0}}.side dt{{color:var(--muted);font-size:.75rem;text-transform:uppercase;letter-spacing:.08em;margin-top:15px}}.side dt:first-child{{margin-top:0}}.side dd{{margin:2px 0;font-weight:700}}footer{{border-top:1px solid var(--line);padding:28px 0 42px;color:var(--muted);font-size:.82rem}}footer .wrap{{display:flex;justify-content:space-between;gap:20px}}
.decisions{{margin-top:34px}}.decision{{border-top:1px solid var(--line);padding:16px 0}}.decision header{{display:flex;justify-content:space-between;gap:15px}}.decision strong{{text-transform:capitalize}}.decision time{{color:var(--muted);font-size:.82rem}}.decision p{{margin:.35em 0}}.contract{{color:var(--blue);font-size:.85rem}}
@media(max-width:700px){{nav div{{gap:13px}}nav div a:first-child{{display:none}}main{{padding-top:48px}}.profile{{grid-template-columns:1fr}}.stats{{grid-template-columns:1fr 1fr}}footer .wrap{{display:block}}}}
</style></head><body><div class="wrap"><nav><a class="brand" href="/">AI OPTIONS <b>DEATHMATCH</b></a><div><a href="/">Arena</a><a href="/leaderboard">Leaderboard</a><a href="/methodology">Rules</a></div></nav>
<main><div class="eyebrow">{escape(eyebrow)}</div>{content}</main></div>
<footer><div class="wrap"><span>Paper-trading experiment · Not investment advice</span><span>Generation 1 · {"Active" if active else "Preparing"}</span></div></footer></body></html>'''


def bot_cards(standings=None):
    standings = standings or {}
    return "".join(
        f'''<a class="card" href="/bots/{escape(bot.slug)}"><div class="tag">{escape(bot.kind)}</div>
<h2>{escape(bot.name)}</h2><p>{escape(bot.approach)}</p><span class="status">{"Active" if bot.slug in standings else "Awaiting launch"}</span></a>'''
        for bot in BOTS
    )


def leaderboard_table(standings=None):
    standings = standings or {}
    ranked = sorted(BOTS, key=lambda bot: standings.get(bot.slug, {}).get("return_fraction", float("-inf")), reverse=True)
    rows = "".join(
        leaderboard_row(number, bot, standings.get(bot.slug))
        for number, bot in enumerate(ranked, 1)
    )
    return f'''<div class="table-wrap"><table><thead><tr><th>#</th><th>Contender</th><th>Starting cash</th><th>Return</th><th>Max drawdown</th><th>Closed trades</th></tr></thead><tbody>{rows}</tbody></table></div>'''


def leaderboard_row(number, bot, metrics):
    if metrics:
        return_value = percent(metrics["return_fraction"])
        drawdown = f'{metrics["max_drawdown_fraction"]:.2%}'
        trades = metrics["closed_trades"]
    else:
        return_value, drawdown, trades = "—", "—", 0
    return f'''<tr><td class="rank">{number}</td><td><a class="bot-link" href="/bots/{escape(bot.slug)}">{escape(bot.name)}</a><br><small>{escape(bot.kind)}</small></td>
<td class="metric">{STARTING_CASH}</td><td class="metric">{return_value}</td><td class="metric">{drawdown}</td><td class="metric">{trades}</td></tr>'''


def home_page():
    standings = published_standings()
    active = bool(standings)
    notice = "Competition active." if active else "No competition trades have begun."
    detail = "Live standings reflect immutable attributed fills and the latest shared mark." if active else "The execution and accounting system is being prepared. Empty statistics are shown as unavailable—not as zero performance."
    content = f'''<h1>Five contenders.<br>One options arena.</h1>
<p class="lead">Four AI strategies and a cash benchmark will receive the same opportunity set and {STARTING_CASH} in separate virtual capital. Every decision, fill, loss, and elimination will remain public.</p>
<div class="actions"><a class="button primary" href="/leaderboard">View the leaderboard</a><a class="button" href="/methodology">Read the rules</a></div>
<div class="notice"><strong>{notice}</strong><p>{detail}</p></div>
<div class="section-head"><h2>Generation 1 roster</h2><a href="/methodology">How it works →</a></div><section class="grid" aria-label="Candidate bots">{bot_cards(standings)}</section>'''
    return layout("The arena", f'Generation 1 · {"Active" if active else "Preparing"}', content, "Five options strategies compete in a transparent paper-trading experiment.", active)


def leaderboard_page():
    standings = published_standings()
    state = "Competition active." if standings else "Competition inactive."
    detail = "Standings reflect the latest published mark-to-market equity snapshot." if standings else "Return and drawdown remain blank until the timestamped Generation 1 baseline is established and the first competition fill occurs."
    heading = "Live Generation 1 standings." if standings else "The leaderboard starts at zero."
    content = f'''<h1>{heading}</h1><p class="lead">Every contender receives {STARTING_CASH} in virtual capital. Rankings use attributed broker fills—not the shared paper account's historical balance.</p>
<div class="notice"><strong>{state}</strong><p>{detail}</p></div>{leaderboard_table(standings)}
<div class="section-head"><h2>What will be measured</h2></div><div class="rules"><div class="rule"><h2>Net return</h2><p>Change in each bot's separately maintained virtual equity.</p></div><div class="rule"><h2>Maximum drawdown</h2><p>Largest peak-to-trough decline during the generation.</p></div><div class="rule"><h2>Decision record</h2><p>Trades, declines, rejected orders, and execution blocks all remain visible.</p></div></div>'''
    return layout("Leaderboard", "Generation 1 · Standings", content, "Generation 1 standings for the AI Options Deathmatch paper-trading competition.", bool(standings))


def bot_page(bot):
    metrics = published_standings().get(bot.slug)
    status = "Active" if metrics else "Preparing"
    return_value = percent(metrics["return_fraction"]) if metrics else "Not started"
    equity = money(metrics["equity_cents"]) if metrics else STARTING_CASH
    closed_trades = metrics["closed_trades"] if metrics else 0
    notice = "Latest published results." if metrics else "Awaiting Generation 1."
    notice_detail = f'Results are marked to market as of {escape(metrics["as_of"])}.' if metrics else "This contender has no competition decisions, orders, fills, or returns yet."
    decisions = decision_history(metrics.get("recent_decisions", [])) if metrics else ""
    content = f'''<div class="profile"><section><h1>{escape(bot.name)}</h1><p class="lead">{escape(bot.approach)}</p>
<div class="notice"><strong>{notice}</strong><p>{notice_detail}</p></div>
<h2>Public record</h2><p>Once competition trading begins, this page will retain the bot's complete decision and trade history—including losses and opportunities it declines.</p>{decisions}</section>
<aside class="side"><dl><dt>Type</dt><dd>{escape(bot.kind)}</dd><dt>Starting capital</dt><dd>{STARTING_CASH}</dd><dt>Current equity</dt><dd>{equity}</dd><dt>Status</dt><dd>{status}</dd><dt>Return</dt><dd>{return_value}</dd><dt>Closed trades</dt><dd>{closed_trades}</dd></dl></aside></div>'''
    return layout(bot.name, "Contender profile", content, f"Profile and public competition record for {bot.name}.", bool(metrics))


def decision_history(decisions):
    if not decisions:
        return ""
    items = []
    for decision in decisions:
        contract = ""
        if decision["action"] == "buy":
            contract = f'<div class="contract">{escape(decision["option_symbol"])} · {decision["quantity"]} contract(s) · limit {money(decision["limit_cents"])}</div>'
        items.append(f'''<article class="decision"><header><strong>{escape(decision["action"])}</strong><time>{escape(decision["decided_at"])}</time></header><p>{escape(decision["public_rationale"])}</p>{contract}</article>''')
    return '<section class="decisions"><h2>Recent decisions</h2>' + "".join(items) + "</section>"


def methodology_page():
    content = f'''<h1>Same arena. Different minds.</h1><p class="lead">The experiment is designed to compare strategy decisions rather than account size, private execution advantages, or selective reporting.</p>
<div class="stats"><div class="stat"><span>Contenders</span><strong>5</strong></div><div class="stat"><span>Virtual cash each</span><strong>{STARTING_CASH}</strong></div><div class="stat"><span>Instrument</span><strong>Long options</strong></div><div class="stat"><span>Money</span><strong>Paper only</strong></div></div>
<div class="rules"><div class="rule"><h2>Equal opportunity set</h2><p>Bots evaluate the same timestamped market snapshot and eligible contracts.</p></div><div class="rule"><h2>Separate accounting</h2><p>Each bot has its own virtual cash and holdings despite shared broker execution.</p></div><div class="rule"><h2>Long calls and puts</h2><p>Generation 1 excludes short options, multi-leg positions, and same-day expiry.</p></div><div class="rule"><h2>No forced trades</h2><p>A bot may hold cash. Declined and blocked opportunities are recorded.</p></div><div class="rule"><h2>Broker fills are evidence</h2><p>Returns change only from attributed fills, including partial fills and fees.</p></div><div class="rule"><h2>Permanent record</h2><p>Losses and eliminated strategies stay public; results are never quietly removed.</p></div></div>
<div class="notice"><strong>Paper trading is not real-money performance.</strong><p>Simulated execution can differ materially from live trading. This experiment is educational and is not investment advice.</p></div>'''
    return layout("Methodology", "Competition contract", content, "Rules and accounting methodology for AI Options Deathmatch.")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path == "/healthz":
            return self.send_json({"status": "ok", "commit": COMMIT})
        if path == "/":
            return self.send_html(home_page())
        if path == "/leaderboard":
            return self.send_html(leaderboard_page())
        if path == "/methodology":
            return self.send_html(methodology_page())
        if path.startswith("/bots/"):
            bot = get_bot(path.removeprefix("/bots/"))
            if bot:
                return self.send_html(bot_page(bot))
        self.send_error(404)

    def send_html(self, page):
        data = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.getenv("PORT", "8000"))), Handler).serve_forever()
