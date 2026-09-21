"""Provisional Generation 1 roster; no strategy executes from this module."""

from dataclasses import dataclass

STARTING_CASH_CENTS = 1_000_000  # $10,000 per bot, independent of broker equity.


@dataclass(frozen=True)
class Bot:
    slug: str
    name: str
    approach: str
    kind: str = "AI candidate"


BOTS = (
    Bot("trend", "Trend Rider", "Looks for liquid calls or puts aligned with a sustained underlying trend."),
    Bot("reversal", "Reversal Scout", "Looks for a defined reversal after an unusually large move."),
    Bot("breakout", "Breakout Watch", "Looks for options after a price breaks a recent range."),
    Bot("catalyst", "Catalyst Reader", "Considers dated public events while respecting the same data cutoff as every bot."),
    Bot("cash", "Cash Keeper", "Deterministic hold-cash benchmark; records every opportunity it declines.", "Benchmark"),
)


def get_bot(slug):
    """Return the bot matching a stable public slug, if one exists."""
    return next((bot for bot in BOTS if bot.slug == slug), None)
