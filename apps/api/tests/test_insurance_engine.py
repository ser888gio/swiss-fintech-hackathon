"""Deterministic pricing envelope — price() (spec §4/§7)."""

from decimal import Decimal

from app.insurance import engine, risk
from app.insurance.engine import PoolState, PricePolicy, QuoteContext
from app.insurance.risk import TxnFeatures
from app.schemas import QuoteDecision

_BIG_POOL = PoolState(first_loss=Decimal("1000000"))
_POLICY = PricePolicy()


def _ctx(active=("merchant_default",), ead="1000", eligible=True, collateral="0"):
    return QuoteContext(
        agent_address="rAgent",
        eligible=eligible,
        txn=TxnFeatures(),
        active_lines=active,
        ead=Decimal(ead),
        collateral=Decimal(collateral),
        score_band="STANDARD",
    )


def test_ineligible_declines():
    r = risk.from_band("STANDARD", now=0.0)
    q = engine.price(_ctx(eligible=False), r, _BIG_POOL, _POLICY)
    assert q.decision is QuoteDecision.DECLINE
    assert q.reason == "ineligible"


def test_offer_has_positive_premium_and_full_receipt():
    r = risk.from_band("STANDARD", now=0.0)
    q = engine.price(_ctx(), r, _BIG_POOL, _POLICY)
    assert q.decision is QuoteDecision.OFFER
    assert Decimal(q.premium) > 0
    assert len(q.receipt_hash) == 64
    assert 0.0 <= q.credibility <= 1.0


def test_per_line_floor_enforced_on_tiny_exposure():
    r = risk.from_band("ELITE", now=0.0)
    q = engine.price(_ctx(ead="1"), r, _BIG_POOL, _POLICY)
    assert Decimal(q.lines["merchant_default"]) >= Decimal("0.50")


def test_premium_is_additive_across_active_lines():
    r = risk.from_band("STANDARD", now=0.0)
    one = engine.price(_ctx(active=("merchant_default",)), r, _BIG_POOL, _POLICY)
    two = engine.price(_ctx(active=("merchant_default", "mandate_breach")), r, _BIG_POOL, _POLICY)
    assert set(two.lines) == {"merchant_default", "mandate_breach"}
    assert Decimal(two.premium) > Decimal(one.premium)


def test_cap_bounds_total_premium():
    r = risk.from_band("HIGH_RISK", now=0.0)
    tight = PricePolicy(cap=Decimal("2.00"))
    q = engine.price(
        _ctx(active=("merchant_default", "lender_credit", "mandate_breach"), ead="1000000"),
        r, _BIG_POOL, tight,
    )
    assert Decimal(q.premium) <= Decimal("2.00")


def test_capacity_breach_routes_to_review():
    r = risk.from_band("STANDARD", now=0.0)
    tiny_pool = PoolState(first_loss=Decimal("1"))
    q = engine.price(_ctx(active=("lender_credit",), ead="1000000"), r, tiny_pool, _POLICY)
    assert q.decision is QuoteDecision.REVIEW
    assert "capacity" in (q.reason or "")


def test_credibility_shrinks_the_risk_margin():
    fresh = risk.from_band("STANDARD", now=0.0)
    seasoned = fresh
    for _ in range(60):
        seasoned = risk.update(seasoned, defaulted=False, exposure_weight=1.0, now=0.0, tau_days=0)
    qf = engine.price(_ctx(), fresh, _BIG_POOL, _POLICY)
    qs = engine.price(_ctx(), seasoned, _BIG_POOL, _POLICY)
    assert qs.credibility > qf.credibility
    # More credibility + a clean record both push the premium down.
    assert Decimal(qs.premium) <= Decimal(qf.premium)


def test_receipt_hash_is_reproducible():
    r = risk.from_band("STANDARD", now=0.0)
    q1 = engine.price(_ctx(), r, _BIG_POOL, _POLICY)
    q2 = engine.price(_ctx(), r, _BIG_POOL, _POLICY)
    assert q1.receipt_hash == q2.receipt_hash


def test_collateral_reduces_merchant_default_exposure():
    r = risk.from_band("STANDARD", now=0.0)
    uncovered = engine.price(_ctx(ead="10000", collateral="0"), r, _BIG_POOL, _POLICY)
    collateralized = engine.price(_ctx(ead="10000", collateral="9000"), r, _BIG_POOL, _POLICY)
    assert Decimal(collateralized.premium) <= Decimal(uncovered.premium)
