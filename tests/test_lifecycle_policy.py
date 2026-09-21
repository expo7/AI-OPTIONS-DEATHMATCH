import unittest

from lifecycle_policy import POLICY_ID, exit_signals


class LifecyclePolicyTest(unittest.TestCase):
    def test_versioned_thresholds_are_inclusive(self):
        self.assertEqual(POLICY_ID, "g1-lifecycle-v1")
        self.assertEqual(exit_signals(-0.50, 20), ["risk_limit"])
        self.assertEqual(exit_signals(1.00, 20), ["target"])
        self.assertEqual(exit_signals(0.10, 7), ["expiry_rule"])
        self.assertEqual(exit_signals(-0.60, 6), ["risk_limit", "expiry_rule"])

    def test_no_signal_inside_limits(self):
        self.assertEqual(exit_signals(-0.49, 8), [])


if __name__ == "__main__":
    unittest.main()
