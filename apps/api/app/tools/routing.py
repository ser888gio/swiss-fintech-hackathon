"""Routing tool: get_fx_path.

Deterministic. Pulls an FX rate from Frankfurter, then asks XRPL for the cheapest
on-ledger path via ripple_path_find (real mode) and returns a quote carrying the
Paths set plus SendMax / DeliverMin caps for the execution tool. No policy logic.
"""

from __future__ import annotations

import httpx

from .. import xrpl_client
from ..config import get_settings
from ..ledger import Ledger
from ..schemas import PaymentIntent, RouteQuote

ESTIMATED_FEE_RATE = 0.001
CRYPTO_IDS = {"XRP": "ripple"}
DEMO_CRYPTO_RATES = {("XRP", "USD"): 0.52, ("XRP", "EUR"): 0.48}


async def get_fx_path(intent: PaymentIntent, settle_currency: str) -> RouteQuote:
    """Return a route quote for converting the intent amount into the settlement
    currency. `settle_currency` is the on-ledger token currency (e.g. USD).

    In real mode this enriches the deterministic FX quote with ripple_path_find:
    the cheapest alternative's Paths and source amount cap the on-ledger Payment.
    """
    quote = await quote_amount(intent.amount, intent.currency, settle_currency)
    return await _attach_xrpl_path(intent, settle_currency, quote)


async def convert_to_usd(amount: float, currency: str) -> float:
    """USD-normalize a source amount for the policy threshold comparison.

    Deterministic: the policy engine compares against a USD threshold
    (`POLICY_THRESHOLD_USD`), so the amount handed to it must be in USD too —
    not the settlement-currency amount. Pure FX, no policy logic here.
    """
    if currency.upper() == "USD":
        return amount
    rate = await _fetch_rate(currency, "USD")
    return round(amount * rate, 2)


async def quote_amount(amount: float, source_currency: str, settle_currency: str) -> RouteQuote:
    """Return a deterministic quote preview for a source amount and currency."""
    rate = await _fetch_rate(source_currency, settle_currency)
    is_xrp = settle_currency.upper() == "XRP"
    dest_amount = round(amount * rate, 6 if is_xrp else 2)
    fee = round(dest_amount * ESTIMATED_FEE_RATE, 4)
    settings = get_settings()
    # SendMax caps the source spend with a slippage buffer; DeliverMin floors the
    # delivered amount when partial payments are enabled (best practice so a
    # payment still lands if a path narrows between quote and submission).
    send_max = round(dest_amount * (1 + settings.route_slippage_bps / 10_000), 6 if is_xrp else 2)
    deliver_min = dest_amount if settings.route_partial_payment else None
    path_summary = f"{source_currency.upper()}->{settle_currency.upper()} @ {rate:.6f} (direct)"
    return RouteQuote(
        source_amount=amount,
        dest_amount=dest_amount,
        rate=rate,
        path_summary=path_summary,
        estimated_fee=fee,
        send_max=send_max,
        deliver_min=deliver_min,
    )


async def _attach_xrpl_path(
    intent: PaymentIntent, settle_currency: str, quote: RouteQuote
) -> RouteQuote:
    """Enrich a quote with the cheapest ripple_path_find alternative (real mode).

    Best-effort: any failure leaves the deterministic direct-path quote intact.
    """
    settings = get_settings()
    if settings.use_mock_xrpl or not settings.token_issuer_address:
        return quote

    try:
        source_account = Ledger(settings).treasury_wallet.address
        destination_amount = xrpl_client.token_amount(settle_currency, quote.dest_amount, settings)
        alternatives = await xrpl_client.find_payment_paths(
            source_account, intent.to, destination_amount
        )
        cheapest = _cheapest_alternative(alternatives)
        if cheapest is None:
            return quote
        paths = cheapest.get("paths_computed") or None
        source_value = _alternative_source_value(cheapest.get("source_amount"))
        send_max = (
            round(source_value * (1 + settings.route_slippage_bps / 10_000), 6)
            if source_value is not None
            else quote.send_max
        )
        hops = max((len(path) for path in paths), default=0) if paths else 0
        summary = f"{intent.currency.upper()}->{settle_currency.upper()} via XRPL ({hops}-hop path)"
        return quote.model_copy(
            update={"paths": paths, "send_max": send_max, "path_summary": summary}
        )
    except Exception:
        # Pathfinding is advisory; never block a quote on a ledger hiccup.
        return quote


def _cheapest_alternative(alternatives: list[dict]) -> dict | None:
    ranked = [alt for alt in alternatives if alt.get("paths_computed") is not None]
    if not ranked:
        return None
    return min(ranked, key=lambda alt: _alternative_source_value(alt.get("source_amount")) or float("inf"))


def _alternative_source_value(source_amount) -> float | None:
    if source_amount is None:
        return None
    if isinstance(source_amount, dict):
        return float(source_amount.get("value", 0))
    # XRP is returned as a drops string.
    return float(source_amount) / 1_000_000


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
