"""Small public launch page for the Deathmatch project.

No trading or broker credentials are used by this process.
"""

import json
import os
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
        data = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Five AI options strategies will compete in an openly tracked paper-trading experiment.">
<title>AI Options Deathmatch — Generation 1 preparing</title>
<style>body{margin:0;background:#10151e;color:#e9edf3;font:18px/1.6 system-ui,sans-serif}main{max-width:780px;margin:12vh auto;padding:0 24px}small{color:#89a8c4;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(2.5rem,7vw,5rem);line-height:1.05;margin:.5em 0}p{max-width:60ch}strong{color:#9ee6ba}.panel{border:1px solid #3c5061;border-radius:12px;padding:20px;margin-top:36px;background:#182230}a{color:#a9d7ff}</style>
</head><body><main><small>Generation 1 · Preparing</small><h1>Five bots.<br>One options arena.</h1>
<p>AI Options Deathmatch is an upcoming public experiment. Five strategies will start with equal virtual capital and rules, and their complete paper-trading records will be shown here.</p>
<div class="panel"><strong>No competition trades have begun.</strong><p>We are building the execution and accounting system. Results will include losses, unfilled orders, and eliminated bots. Paper results are simulated and are not real-money returns.</p></div>
<p><a href="https://github.com/expo7/AI-OPTIONS-DEATHMATCH">Read the project plan</a></p></main></body></html>'''.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.getenv("PORT", "8000"))), Handler).serve_forever()
