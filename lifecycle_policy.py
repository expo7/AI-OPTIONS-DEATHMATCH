"""Versioned common position-lifecycle policy for Generation 1.

The policy produces public exit signals only. It cannot stage or submit orders.
"""

POLICY_ID = "g1-lifecycle-v1"
MAX_PREMIUM_LOSS_FRACTION = -0.50
PROFIT_TARGET_FRACTION = 1.00
MANDATORY_EXIT_DAYS_TO_EXPIRY = 7


def exit_signals(return_fraction, days_to_expiry):
    signals = []
    if return_fraction <= MAX_PREMIUM_LOSS_FRACTION:
        signals.append("risk_limit")
    if return_fraction >= PROFIT_TARGET_FRACTION:
        signals.append("target")
    if days_to_expiry <= MANDATORY_EXIT_DAYS_TO_EXPIRY:
        signals.append("expiry_rule")
    return signals
