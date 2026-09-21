import unittest

from bots import BOTS, STARTING_CASH_CENTS
from generation_one import BOT_RULES, COMMON_RULES, GENERATION, frozen_rules


class GenerationOneRulesTest(unittest.TestCase):
    def test_every_contender_has_one_versioned_ruleset(self):
        self.assertEqual(GENERATION, 1)
        self.assertEqual(set(BOT_RULES), {bot.slug for bot in BOTS})
        self.assertEqual(len({rules["version_id"] for rules in BOT_RULES.values()}), len(BOTS))

    def test_common_risk_contract_matches_competition(self):
        self.assertEqual(COMMON_RULES["starting_cash_cents"], STARTING_CASH_CENTS)
        self.assertEqual(COMMON_RULES["instrument"], "single-leg long call or put")
        self.assertFalse(COMMON_RULES["short_options_allowed"])
        self.assertFalse(COMMON_RULES["same_day_expiry_allowed"])
        self.assertFalse(COMMON_RULES["trade_required"])

    def test_frozen_rules_include_common_and_strategy_rules(self):
        rules = frozen_rules("trend")
        self.assertEqual(rules["generation"], 1)
        self.assertEqual(rules["bot"]["version_id"], "g1-trend-v1")
        self.assertEqual(rules["common"]["order_type"], "limit")


if __name__ == "__main__":
    unittest.main()
