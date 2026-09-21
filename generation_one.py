"""Frozen Generation 1 strategy and portfolio configuration.

This module describes decision rules only. It does not fetch market data,
invoke a model, or submit an order.
"""

GENERATION = 1

COMMON_RULES = {
    "instrument": "single-leg long call or put",
    "starting_cash_cents": 1_000_000,
    "max_position_premium_cents": 100_000,
    "max_open_positions": 3,
    "days_to_expiry": {"minimum": 14, "maximum": 45},
    "minimum_open_interest": 500,
    "minimum_contract_volume": 100,
    "maximum_bid_ask_spread_fraction": 0.10,
    "order_type": "limit",
    "same_day_expiry_allowed": False,
    "short_options_allowed": False,
    "multi_leg_allowed": False,
    "trade_required": False,
}

BOT_RULES = {
    "trend": {
        "version_id": "g1-trend-v1",
        "strategy": "trend continuation",
        "entry": "Select a call in a confirmed uptrend or put in a confirmed downtrend after momentum persists across the shared snapshot.",
        "decline": "Decline when trend direction is mixed, liquidity fails common rules, or premium exceeds the risk cap.",
        "exit": "Exit on thesis invalidation, risk limit, target, or seven calendar days before expiry.",
    },
    "reversal": {
        "version_id": "g1-reversal-v1",
        "strategy": "mean reversal",
        "entry": "Select the option opposing an unusually extended move only after the shared snapshot contains reversal confirmation.",
        "decline": "Decline when the move remains directionally accelerating or no confirmation is present.",
        "exit": "Exit at mean-reversion target, thesis invalidation, risk limit, or seven calendar days before expiry.",
    },
    "breakout": {
        "version_id": "g1-breakout-v1",
        "strategy": "range breakout",
        "entry": "Select a call or put after price leaves a documented recent range with confirming participation in the shared snapshot.",
        "decline": "Decline false breaks, low-participation moves, or contracts outside common liquidity rules.",
        "exit": "Exit on return into the prior range, risk limit, target, or seven calendar days before expiry.",
    },
    "catalyst": {
        "version_id": "g1-catalyst-v1",
        "strategy": "dated public catalyst",
        "entry": "Select a directional option only when a timestamped public catalyst and market response support the same thesis.",
        "decline": "Decline undated rumors, stale events, ambiguous reactions, or contracts outside common rules.",
        "exit": "Exit when the catalyst thesis resolves or fails, at the risk limit or target, or seven calendar days before expiry.",
    },
    "cash": {
        "version_id": "g1-cash-v1",
        "strategy": "cash benchmark",
        "entry": "Never enter an option position.",
        "decline": "Decline every opportunity and retain cash.",
        "exit": "Not applicable.",
    },
}


def frozen_rules(bot_id):
    """Return the complete serializable ruleset for a Generation 1 bot."""
    return {"generation": GENERATION, "common": COMMON_RULES, "bot": BOT_RULES[bot_id]}
