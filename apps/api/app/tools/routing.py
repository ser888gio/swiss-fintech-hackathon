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
CRYPTO_IDS = {"XRP": "ripple"}
DEMO_CRYPTO_RATES = {("XRP", "USD"): 0.52, ("XRP", "EUR"): 0.48}


async def get_fx_path(intent: PaymentIntent, settle_currency: str) -> RouteQuote:
    """Return a route quote for converting the intent amount into the settlement
    currency. `settle_currency` is the on-ledger token currency (e.g. USD)."""
    return await quote_amount(intent.amount, intent.currency, settle_currency)


async def quote_amount(amount: float, source_currency: str, settle_currency: str) -> RouteQuote:
    """Return a deterministic quote preview for a source amount and currency."""
    rate = await _fetch_rate(source_currency, settle_currency)
    dest_amount = round(amount * rate, 6 if settle_currency.upper() == "XRP" else 2)
    fee = round(dest_amount * ESTIMATED_FEE_RATE, 4)
    # TODO(hackathon): replace the flat summary with ripple_path_find output so
    # the cheapest cross-currency path through XRPL order books is shown.
    path_summary = f"{source_currency.upper()}->{settle_currency.upper()} @ {rate:.6f} (direct)"
    return RouteQuote(
        source_amount=amount,
        dest_amount=dest_amount,
        rate=rate,
        path_summary=path_summary,
        estimated_fee=fee,
    )


async def _fetch_rate(base: str, quote: str) -> float:
    base = base.upper()
    quote = quote.upper()
    if base == quote:
        return 1.0
    if base in CRYPTO_IDS or quote in CRYPTO_IDS:
        return await _fetch_crypto_rate(base, quote)
    return await _fetch_fx_rate(base, quote)


async def _fetch_crypto_rate(base: str, quote: str) -> float:
    if base in CRYPTO_IDS and quote not in CRYPTO_IDS:
        return await _fetch_crypto_to_fiat_rate(base, quote)
    if quote in CRYPTO_IDS and base not in CRYPTO_IDS:
        return 1 / await _fetch_crypto_to_fiat_rate(quote, base)
    raise ValueError(f"unsupported crypto route {base}->{quote}")


async def _fetch_crypto_to_fiat_rate(base: str, quote: str) -> float:
    url = "https://api.coingecko.com/api/v3/simple/price"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(
                url,
                params={"ids": CRYPTO_IDS[base], "vs_currencies": quote.lower()},
            )
            response.raise_for_status()
            data = response.json()
        return float(data[CRYPTO_IDS[base]][quote.lower()])
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        fallback = DEMO_CRYPTO_RATES.get((base, quote))
        if fallback is None:
            raise
        return fallback


async def _fetch_fx_rate(base: str, quote: str) -> float:
    settings = get_settings()
    url = f"{settings.frankfurter_base_url}/latest"
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        response = await client.get(url, params={"from": base, "to": quote})
        response.raise_for_status()
        data = response.json()
    return float(data["rates"][quote])
