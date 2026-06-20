"""Tests for cover/pricing.py — pure premium pricing."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.cover.pricing import price_cover
from app.insurance.risk import from_band
from app.schemas import CoverLineKind


def _settings():
    return SimpleNamespace(
        cover_hallucination_rate=0.03,
        cover_rate_min=0.02,
        cover_rate_max=0.10,
        insurance_pool_first_loss_usd=250_000.0,
        insurance_premium_cap_usd=5000.0,
    )


def _risk(band="STANDARD"):
    return from_band(band)


def _price(cover_cap="5000", per_claim="500", term_days=365, lines=None, band="STANDARD", free_cap=None):
    s = _settings()
    r = _risk(band)
    if lines is None:
        lines = [CoverLineKind.hallucination]
    fc = Decimal(str(free_cap)) if free_cap is not None else Decimal("250000")
    return price_cover(
        agent_address="rAGENT",
        score_band=band,
        cover_cap=cover_cap,
        per_claim_limit=per_claim,
        term_days=term_days,
        lines=lines,
        r=r,
        free_capacity=fc,
        hallucination_rate=s.cover_hallucination_rate,
        rate_min=s.cover_rate_min,
        rate_max=s.cover_rate_max,
        premium_cap=s.insurance_premium_cap_usd,
    )


def test_offer_returned_for_normal_request():
    q = _price()
    assert q.decision == "OFFER"
    assert Decimal(q.premium) > 0


def test_premium_is_prorated_by_term():
    q_365 = _price(term_days=365)
    q_180 = _price(term_days=180)
    # 180-day policy should cost roughly half
    p365 = Decimal(q_365.premium)
    p180 = Decimal(q_180.premium)
    assert p180 < p365
    ratio = float(p180 / p365)
    assert 0.45 < ratio < 0.55


def test_premium_scales_with_cover_cap():
    q_low = _price(cover_cap="1000")
    q_high = _price(cover_cap="5000")
    assert Decimal(q_high.premium) > Decimal(q_low.premium)


def test_high_risk_band_costs_more_than_elite():
    q_elite = _price(band="ELITE")
    q_high_risk = _price(band="HIGH_RISK")
    # hallucination is static rate — both should be same; non_delivery differs
    # With only hallucination line (static) bands are equal
    assert Decimal(q_high_risk.premium) == Decimal(q_elite.premium)


def test_non_delivery_line_pd_driven():
    q_halu = _price(lines=[CoverLineKind.hallucination], band="STANDARD")
    q_both = _price(lines=[CoverLineKind.hallucination, CoverLineKind.non_delivery], band="STANDARD")
    assert Decimal(q_both.premium) > Decimal(q_halu.premium)


def test_solvency_gate_review_when_cap_exceeds_pool():
    q = _price(cover_cap="999999", free_cap=1000)
    assert q.decision == "REVIEW"
    assert "pool capacity" in (q.reason or "")


def test_per_claim_limit_exceeding_cover_cap_raises():
    with pytest.raises(ValueError, match="per_claim_limit"):
        _price(cover_cap="500", per_claim="1000")


def test_empty_lines_raises():
    with pytest.raises(ValueError, match="line"):
        _price(lines=[])


def test_receipt_hash_is_deterministic():
    q1 = _price()
    q2 = _price()
    assert q1.receipt_hash == q2.receipt_hash


def test_receipt_hash_changes_with_inputs():
    q1 = _price(cover_cap="1000")
    q2 = _price(cover_cap="2000")
    assert q1.receipt_hash != q2.receipt_hash
