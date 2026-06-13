"""Routing tool: get_fx_path.

Deterministic. Pulls an FX rate from Frankfurter and (TODO) an XRPL path from
ripple_path_find, returning the cheapest path summary. No policy logic.
"""

from __future__ import annotations

import httpx

from ..config import get_settings
from ..schemas import PaymentIntent, RouteQuote

# Flat estimate until ripple_path_find is wired in (see TODO below).
ESTIMATED_FEE_RATE = 0.001


async def get_fx_path(intent: PaymentIntent, settle_currency: str) -> RouteQuote:
    """Return a route quote for converting the intent amount into the settlement
    currency. `settle_currency` is the on-ledger token currency (e.g. USD)."""
    rate = await _fetch_fx_rate(intent.currency, settle_currency)
    dest_amount = round(intent.amount * rate, 2)
    fee = round(dest_amount * ESTIMATED_FEE_RATE, 4)
    # TODO(hackathon): replace the flat summary with ripple_path_find output so
    # the cheapest cross-currency path through XRPL order books is shown.
    path_summary = f"{intent.currency}->{settle_currency} @ {rate:.4f} (direct)"
    return RouteQuote(
        source_amount=intent.amount,
        dest_amount=dest_amount,
        rate=rate,
        path_summary=path_summary,
        estimated_fee=fee,
    )


async def _fetch_fx_rate(base: str, quote: str) -> float:
    base = base.upper()
    quote = quote.upper()
    if base == quote:
        return 1.0
    settings = get_settings()
    url = f"{settings.frankfurter_base_url}/latest"
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        response = await client.get(url, params={"from": base, "to": quote})
        response.raise_for_status()
        data = response.json()
    return float(data["rates"][quote])
