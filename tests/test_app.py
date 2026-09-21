import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from app import Handler
from bots import BOTS
from ledger import Ledger


class PublicRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def get_page(self, path):
        with urlopen(self.base + path) as response:
            self.assertEqual(response.headers.get_content_type(), "text/html")
            return response.read().decode()

    def test_health(self):
        with urlopen(self.base + "/healthz") as response:
            self.assertEqual(json.load(response)["status"], "ok")

    def test_home_is_honest_and_links_every_bot(self):
        page = self.get_page("/")
        self.assertIn("No competition trades have begun", page)
        self.assertIn("paper-trading", page)
        for bot in BOTS:
            self.assertIn(f'/bots/{bot.slug}', page)
            self.assertIn(bot.name, page)

    def test_leaderboard_has_unstarted_metrics(self):
        page = self.get_page("/leaderboard")
        self.assertIn("Competition inactive", page)
        self.assertIn("$10,000", page)
        self.assertNotIn("0.00%", page)

    def test_explicit_publication_flag_renders_ledger_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite3"
            ledger = Ledger(path)
            ledger.initialize()
            ledger.add_bot("trend", 1_000_000)
            ledger.record_bot_version("trend-g1", "trend", 1, {"strategy": "trend"}, "2026-09-21T15:00:00Z")
            ledger.record_opportunity("opp-1", "2026-09-21T15:30:00Z", "2026-09-21T15:30:00Z", {"symbol": "SPY"})
            ledger.record_decision(
                "decision-1", "opp-1", "trend", "trend-g1", "decline",
                "The trend was mixed, so no option qualified.", "2026-09-21T15:35:00Z",
            )
            ledger.record_equity_snapshot("trend", 950_000, "2026-09-21T16:00:00Z")
            ledger.close()
            with patch("app.RESULTS_PUBLIC", True), patch("app.LEDGER_PATH", str(path)):
                leaderboard = self.get_page("/leaderboard")
                profile = self.get_page("/bots/trend")
            self.assertIn("Competition active", leaderboard)
            self.assertIn("-5.00%", leaderboard)
            self.assertIn("$9,500.00", profile)
            self.assertIn("2026-09-21T16:00:00Z", profile)
            self.assertIn("Recent decisions", profile)
            self.assertIn("The trend was mixed, so no option qualified.", profile)

    def test_methodology_discloses_rules(self):
        page = self.get_page("/methodology/")
        self.assertIn("Long calls and puts", page)
        self.assertIn("Paper trading is not real-money performance", page)

    def test_each_bot_has_a_profile(self):
        for bot in BOTS:
            page = self.get_page(f"/bots/{bot.slug}")
            self.assertIn(bot.name, page)
            self.assertIn("Awaiting Generation 1", page)

    def test_unknown_route_and_bot_return_404(self):
        for path in ("/missing", "/bots/not-a-bot"):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.base + path)
            self.assertEqual(error.exception.code, 404)
