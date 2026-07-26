from __future__ import annotations

# Costs computed here are NOTIONAL: token counts priced at Anthropic's published
# API rates. If Claude Code runs under a subscription (Pro/Max) rather than a
# metered API key, no money is actually billed per-token -- this is a shadow
# cost / proxy for AI effort, confirmed against a real Console usage page
# during Gate 1 of the v0 build (see reconcile.py).

from dataclasses import dataclass

from .walker import CostEvent

# USD per 1M tokens, (input, output). Verify against current published rates
# before trusting a number (https://www.anthropic.com/pricing).
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),  # same Opus 4.x rate card as 4-8, per user confirmation
}

# cache_creation_input_tokens is not one price bucket: Anthropic prices a
# 1-hour cache write differently from a 5-minute one. See walker.py -- real
# Claude Code records split this via message.usage.cache_creation.
CACHE_WRITE_1H_MULT = 2.00
CACHE_WRITE_5M_MULT = 1.25
CACHE_READ_MULT = 0.10


class UnknownModelError(ValueError):
    pass


@dataclass(frozen=True)
class CostBreakdown:
    input_cost: float
    cache_write_1h_cost: float
    cache_write_5m_cost: float
    cache_read_cost: float
    output_cost: float

    @property
    def total(self) -> float:
        return (
            self.input_cost
            + self.cache_write_1h_cost
            + self.cache_write_5m_cost
            + self.cache_read_cost
            + self.output_cost
        )


def _prices_for_model(model: str) -> tuple[float, float]:
    for prefix, prices in PRICES.items():
        if model.startswith(prefix):
            return prices
    raise UnknownModelError(
        f"No price table entry matches model {model!r}. "
        f"Add it to PRICES in cost.py rather than defaulting silently."
    )


def cost_for_event(event: CostEvent) -> CostBreakdown:
    price_in, price_out = _prices_for_model(event.model)
    return CostBreakdown(
        input_cost=(event.input_tokens / 1e6) * price_in,
        cache_write_1h_cost=(event.cache_creation_1h_tokens / 1e6) * price_in * CACHE_WRITE_1H_MULT,
        cache_write_5m_cost=(event.cache_creation_5m_tokens / 1e6) * price_in * CACHE_WRITE_5M_MULT,
        cache_read_cost=(event.cache_read_tokens / 1e6) * price_in * CACHE_READ_MULT,
        output_cost=(event.output_tokens / 1e6) * price_out,
    )


def total_cost(events: list[CostEvent]) -> CostBreakdown:
    parts = [cost_for_event(e) for e in events]
    return CostBreakdown(
        input_cost=sum(p.input_cost for p in parts),
        cache_write_1h_cost=sum(p.cache_write_1h_cost for p in parts),
        cache_write_5m_cost=sum(p.cache_write_5m_cost for p in parts),
        cache_read_cost=sum(p.cache_read_cost for p in parts),
        output_cost=sum(p.output_cost for p in parts),
    )
