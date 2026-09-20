"""Small public launch page for the Deathmatch project.

No trading or broker credentials are used by this process.
"""

import json
import os
from html import escape

from bots import BOTS, STARTING_CASH_CENTS
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


COMMIT = os.getenv("APP_COMMIT", "local")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/healthz":
            data = json.dumps({"status": "ok", "commit": COMMIT}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path != "/":
            self.send_error(404)
            return
        cards = "".join(
            f'<article class="bot"><small>{escape(bot.kind)}</small><h2>{escape(bot.name)}</h2>'
            f'<p>{escape(bot.approach)}</p><span>Awaiting Generation 1</span></article>'
            for bot in BOTS
        )
        data = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Four AI options strategy candidates and a cash benchmark will compete in an openly tracked paper-trading experiment.">
<title>AI Options Deathmatch — Generation 1 preparing</title>
<style>body{margin:0;background:#10151e;color:#e9edf3;font:18px/1.6 system-ui,sans-serif}main{max-width:780px;margin:12vh auto;padding:0 24px}small{color:#89a8c4;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(2.5rem,7vw,5rem);line-height:1.05;margin:.5em 0}p{max-width:60ch}strong{color:#9ee6ba}.panel,.bot{border:1px solid #3c5061;border-radius:12px;padding:20px;margin-top:24px;background:#182230}a{color:#a9d7ff}.roster{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-top:20px}.bot{margin:0}.bot h2{margin:.25em 0;font-size:1.35rem}.bot p{font-size:1rem;line-height:1.45}.bot span{color:#9ee6ba;font-size:.85rem}</style>
</head><body><main><small>Generation 1 · Preparing</small><h1>Five contenders.<br>One options arena.</h1>
<p>AI Options Deathmatch is an upcoming public experiment. Four AI strategy candidates and a deterministic cash benchmark are preparing to compete. Each will begin with {{STARTING_CASH}} in separate virtual capital. Their complete paper-trading records will appear here.</p>
<div class="panel"><strong>No competition trades have begun.</strong><p>We are building the execution and accounting system. Results will include losses, unfilled orders, and eliminated bots. Paper results are simulated and are not real-money returns.</p></div>
<h2>Generation 1 candidate roster</h2><p>These approaches are provisional. Configurations and competition rules will be frozen before the first trade.</p><section class="roster" aria-label="Candidate bots">{{CARDS}}</section><p><a href="https://github.com/expo7/AI-OPTIONS-DEATHMATCH">Read the project plan</a></p></main></body></html>'''.replace("{{STARTING_CASH}}", f"${STARTING_CASH_CENTS / 100:,.0f}").replace("{{CARDS}}", cards).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.getenv("PORT", "8000"))), Handler).serve_forever()
