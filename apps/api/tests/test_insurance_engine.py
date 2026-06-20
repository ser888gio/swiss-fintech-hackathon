from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.insurance import engine, risk
from app.insurance.engine import PoolState, PricePolicy, QuoteContext
from app.insurance.risk import TxnFeatures


def _txn(**overrides) -> TxnFeatures:
    data = {
        "category": "supplier_payment",
        "tenor_band": "lt_30d",
        "cpty_band": "known",
        "first_seen": False,
        "amount_z": 0.0,
        "velocity_z": 0.0,
        "concentration_z": 0.0,
    }
    data.update(overrides)
    return TxnFeatures(**data)


def _ctx(*, lines=("merchant_default",), ead="500", collateral="0") -> QuoteContext:
    return QuoteContext(
        agent_address="rAGENT",
        eligible=True,
        txn=_txn(),
        active_lines=tuple(lines),
        ead=Decimal(ead),
        collateral=Decimal(collateral),
        score_band="STANDARD",
    )


def _pool(first_loss="100000") -> PoolState:
    return PoolState(first_loss=Decimal(first_loss), currency="USD")


def _risk():
    return risk.from_band("STANDARD", now=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_price_offer_produces_breakdown_and_hash():
    quote = engine.price(_ctx(lines=("merchant_default", "mandate_breach")), _risk(), _pool(), PricePolicy())
    assert quote.decision.value == "OFFER"
    assert Decimal(quote.premium) > Decimal("0")
    assert set(quote.lines) == {"merchant_default", "mandate_breach"}
    assert len(quote.receipt_hash) == 64


def test_price_review_on_capacity_breach():
    quote = engine.price(_ctx(ead="50000"), _risk(), _pool(first_loss="100"), PricePolicy())
    assert quote.decision.value == "REVIEW"


def test_price_decline_without_lines():
    quote = engine.price(_ctx(lines=()), _risk(), _pool(), PricePolicy())
    assert quote.decision.value == "DECLINE"


def test_band_round_uses_tick():
    rounded = engine.band_round(Decimal("12.74"), Decimal("0.50"))
    assert rounded == Decimal("12.50")


def test_receipt_hash_is_reproducible_for_same_inputs():
    first = engine.price(_ctx(), _risk(), _pool(), PricePolicy())
    second = engine.price(_ctx(), _risk(), _pool(), PricePolicy())
    assert first.receipt_hash == second.receipt_hash
