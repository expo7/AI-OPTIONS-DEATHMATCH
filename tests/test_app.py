import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from app import Handler
from bots import BOTS


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
