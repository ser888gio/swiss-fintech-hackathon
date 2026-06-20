from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.insurance import engine, risk
from app.schemas import PoolStatus, TxnContext


def _ctx(**overrides) -> TxnContext:
    data = {
        "category": "supplier_payment",
        "tenorBand": "short",
        "cptyBand": "standard",
        "firstSeen": False,
        "amount": "500",
        "amountZ": 0.0,
        "velocityZ": 0.0,
        "concentrationZ": 0.0,
        "activeLines": ["merchant_default"],
    }
    data.update(overrides)
    return TxnContext(**data)


def _pool(**overrides) -> PoolStatus:
    data = {
        "enabled": True,
        "currency": "USD",
        "deposited": "10000.000000",
        "walletBalance": "5000.000000",
        "availableCapacity": "15000.000000",
        "premiumsCollected": "0.000000",
        "claimsPaid": "0.000000",
    }
    data.update(overrides)
    return PoolStatus(**data)


def _risk():
    return risk.from_band("STANDARD", now=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_price_offer_produces_breakdown_and_hash():
    quote = engine.price(_ctx(activeLines=["merchant_default", "mandate_breach"]), _risk(), _pool())
    assert quote.decision.value == "OFFER"
    assert Decimal(quote.premium) > Decimal("0")
    assert set(quote.lines) == {"merchant_default", "mandate_breach"}
    assert len(quote.receipt_hash) == 64


def test_price_review_on_capacity_breach():
    quote = engine.price(_ctx(amount="50000.000000"), _risk(), _pool(availableCapacity="100.000000"))
    assert quote.decision.value == "REVIEW"


def test_price_decline_without_lines():
    quote = engine.price(_ctx(activeLines=[]), _risk(), _pool())
    assert quote.decision.value == "DECLINE"


def test_band_round_uses_tick():
    rounded = engine.band_round(Decimal("12.740000"), Decimal("0.500000"))
    assert rounded == Decimal("12.500000")


def test_receipt_hash_is_reproducible_for_same_inputs():
    first = engine.price(_ctx(), _risk(), _pool())
    second = engine.price(_ctx(), _risk(), _pool())
    assert first.receipt_hash == second.receipt_hash

