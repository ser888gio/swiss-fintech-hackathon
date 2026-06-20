"""Tests for cover/tool.py — async settlement layer."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from decimal import Decimal

import pytest

from app.cover import store as cover_store
from app.cover import tool as cover_tool
from app.cover.tool import (
    AlreadyClaimed,
    ClaimRefused,
    CoverUnavailable,
    NoCoveredDivergence,
    PolicyNotFound,
    PaymentNotFound,
)
from app import store as payment_store
from app.schemas import (
    CoverBindRequest,
    CoverClaimEvidence,
    CoverLineKind,
    CoverPolicyStatus,
    CoverQuoteRequest,
    Payment,
    PaymentIntent,
    PaymentStatus,
    ReceiverEntityType,
)


def _settings():
    return SimpleNamespace(
        cover_enabled=True,
        cover_hallucination_rate=0.03,
        cover_rate_min=0.02,
        cover_rate_max=0.10,
        insurance_pool_first_loss_usd=250_000.0,
        insurance_premium_cap_usd=5_000.0,
        insurance_tau_days=120.0,
        policy_threshold_usd=500.0,
        use_mock_xrpl=True,
        treasury_wallet_address="rTREASURY",
        token_currency="RLUSD",
        xrpl_endpoint="wss://s.altnet.rippletest.net:51233",
    )


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    cover_store.reset_mock_state()
    payment_store._payments.clear()
    payment_store._logs.clear()
    monkeypatch.setattr("app.cover.tool.get_settings", _settings)
    monkeypatch.setattr("app.cover.pricing.get_settings", _settings, raising=False)
    monkeypatch.setattr("app.cover.store.get_settings", _settings, raising=False)
    yield
    cover_store.reset_mock_state()
    payment_store._payments.clear()
    payment_store._logs.clear()


def _make_payment(
    payment_id: str,
    amount: float,
    expected_amount: float | None,
    merchant: str,
    expected_recipient: str | None = None,
    status: PaymentStatus = PaymentStatus.settled,
    agent: str = "rTREASURY",
) -> Payment:
    now = datetime.now(timezone.utc)
    intent = PaymentIntent(**{
        "from": agent,
        "to": merchant,
        "senderName": "Agent",
        "senderCountry": "CH",
        "receiverName": "Merchant",
        "receiverCountry": "DE",
        "receiverEntityType": ReceiverEntityType.company,
        "purpose": "invoice",
        "amount": amount,
        "currency": "RLUSD",
        "reference": "REF-001",
        "expectedAmount": expected_amount,
        "expectedRecipient": expected_recipient or merchant,
    })
    p = Payment(
        id=payment_id,
        intent=intent,
        status=status,
        created_at=now,
        updated_at=now,
    )
    payment_store.save(p)
    return p


async def _buy_policy(agent: str = "rTREASURY") -> "CoverPolicy":
    q = cover_tool.quote(CoverQuoteRequest(
        agent_address=agent,
        score_band="STANDARD",
        cover_cap="5000",
        per_claim_limit="500",
        term_days=365,
    ))
    assert q.decision == "OFFER"
    return await cover_tool.bind(CoverBindRequest(
        agent_address=agent,
        score_band="STANDARD",
        cover_cap="5000",
        per_claim_limit="500",
        term_days=365,
        quote=q,
    ))


@pytest.mark.anyio
async def test_bind_creates_active_policy_with_premium():
    policy = await _buy_policy()
    assert policy.status == CoverPolicyStatus.active
    assert Decimal(policy.premium) > 0
    assert policy.cover_remaining == policy.cover_cap
    pool = cover_tool.get_pool_status()
    assert Decimal(pool.premiums_collected) > 0
    assert Decimal(pool.reserved) == Decimal(policy.cover_cap)


@pytest.mark.anyio
async def test_bind_review_refused():
    q = cover_tool.quote(CoverQuoteRequest(
        agent_address="rAGENT",
        score_band="STANDARD",
        cover_cap="999999999",  # exceeds pool
        per_claim_limit="500",
        term_days=365,
    ))
    assert q.decision == "REVIEW"
    with pytest.raises(CoverUnavailable):
        await cover_tool.bind(CoverBindRequest(
            agent_address="rAGENT",
            score_band="STANDARD",
            cover_cap="999999999",
            per_claim_limit="500",
            term_days=365,
            quote=q,
        ))


@pytest.mark.anyio
async def test_underpayment_claim_pays_merchant():
    policy = await _buy_policy()
    _make_payment("pid-1", amount=480.0, expected_amount=500.0, merchant="rMERCHANT")

    payout = await cover_tool.settle_claim(CoverClaimEvidence(
        policy_id=policy.id,
        payment_id="pid-1",
    ))
    assert payout.classification == "underpayment"
    assert payout.destination == "rMERCHANT"
    assert Decimal(payout.amount_paid) == Decimal("20.00")

    # cover_remaining decremented
    updated = cover_store.get_policy(policy.id)
    assert Decimal(updated.cover_remaining) == Decimal(policy.cover_cap) - Decimal("20.00")

    # pool claims up
    pool = cover_tool.get_pool_status()
    assert Decimal(pool.claims_paid) == Decimal("20.00")


@pytest.mark.anyio
async def test_wrong_recipient_claim_refunds_treasury():
    policy = await _buy_policy()
    _make_payment(
        "pid-2", amount=500.0, expected_amount=500.0,
        merchant="rWRONG", expected_recipient="rCORRECT",
    )
    payout = await cover_tool.settle_claim(CoverClaimEvidence(
        policy_id=policy.id,
        payment_id="pid-2",
    ))
    assert payout.classification == "wrong_recipient"
    assert payout.destination == "rTREASURY"


@pytest.mark.anyio
async def test_replay_protection():
    policy = await _buy_policy()
    _make_payment("pid-3", amount=480.0, expected_amount=500.0, merchant="rM")

    await cover_tool.settle_claim(CoverClaimEvidence(policy_id=policy.id, payment_id="pid-3"))
    with pytest.raises(AlreadyClaimed):
        await cover_tool.settle_claim(CoverClaimEvidence(policy_id=policy.id, payment_id="pid-3"))


@pytest.mark.anyio
async def test_no_divergence_raises():
    policy = await _buy_policy()
    _make_payment("pid-4", amount=500.0, expected_amount=500.0, merchant="rM")
    with pytest.raises(NoCoveredDivergence):
        await cover_tool.settle_claim(CoverClaimEvidence(policy_id=policy.id, payment_id="pid-4"))


@pytest.mark.anyio
async def test_unsettled_payment_refused():
    policy = await _buy_policy()
    _make_payment("pid-5", amount=480.0, expected_amount=500.0, merchant="rM", status=PaymentStatus.routing)
    with pytest.raises(ClaimRefused, match="settled"):
        await cover_tool.settle_claim(CoverClaimEvidence(policy_id=policy.id, payment_id="pid-5"))


@pytest.mark.anyio
async def test_payout_capped_at_per_claim_limit():
    policy = await _buy_policy()
    # Shortfall $1000 but per_claim_limit=$500
    _make_payment("pid-6", amount=0.0, expected_amount=1000.0, merchant="rM")
    payout = await cover_tool.settle_claim(CoverClaimEvidence(policy_id=policy.id, payment_id="pid-6"))
    assert Decimal(payout.amount_paid) == Decimal("500.00")


@pytest.mark.anyio
async def test_policy_exhaustion():
    policy = await _buy_policy()
    # File 10 × $500 claims to exhaust $5000 cap
    for i in range(10):
        pid = f"pid-ex-{i}"
        _make_payment(pid, amount=0.0, expected_amount=1000.0, merchant="rM")
        cover_store._claimed_payments.discard(pid)  # allow re-use for exhaustion test
        # Use unique payment ids
    for i in range(10):
        pid = f"pid-exhaust-{i}"
        _make_payment(pid, amount=0.0, expected_amount=1000.0, merchant=f"rM{i}")
        try:
            await cover_tool.settle_claim(CoverClaimEvidence(policy_id=policy.id, payment_id=pid))
        except ClaimRefused:
            break  # exhausted

    updated = cover_store.get_policy(policy.id)
    assert updated.status == CoverPolicyStatus.exhausted


@pytest.mark.anyio
async def test_risk_posterior_repriced_after_claim():
    policy = await _buy_policy()
    _make_payment("pid-7", amount=480.0, expected_amount=500.0, merchant="rM")

    snap_before = cover_store.get_agent_risk_snapshot("rTREASURY")
    pd_before = snap_before["pd"] if snap_before else 0.035

    await cover_tool.settle_claim(CoverClaimEvidence(policy_id=policy.id, payment_id="pid-7"))

    snap_after = cover_store.get_agent_risk_snapshot("rTREASURY")
    assert snap_after is not None
    assert snap_after["pd"] > pd_before


@pytest.mark.anyio
async def test_payment_not_found():
    policy = await _buy_policy()
    with pytest.raises(PaymentNotFound):
        await cover_tool.settle_claim(CoverClaimEvidence(policy_id=policy.id, payment_id="nonexistent"))


@pytest.mark.anyio
async def test_policy_not_found():
    _make_payment("pid-8", amount=480.0, expected_amount=500.0, merchant="rM")
    with pytest.raises(PolicyNotFound):
        await cover_tool.settle_claim(CoverClaimEvidence(policy_id="nonexistent", payment_id="pid-8"))
