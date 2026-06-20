"""End-to-end credential gate tests — through the full orchestrator pipeline.

Proves the key invariant for the rubric: with CREDENTIAL_KYC_ENABLED=true,
a payment to an un-credentialed receiver escalates to hardware approval; the
same payment after issue+accept auto-settles. Sanctioned parties remain blocked
regardless of credential status.

These tests exercise the full call chain:
  orchestrator.process_payment
    → routing.get_fx_path (FX rate mocked)
    → credentials.verify_kyc (mock XRPL)
    → compliance.check_compliance
    → policy.engine.evaluate (USD-normalized threshold)
    → execution.execute_payment / lock_payment (mock XRPL)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents import orchestrator
from app.credentials.kyc import tool as credentials
from app.schemas import PaymentIntent, PaymentStatus
from app.tools import audit, compliance, routing


# ── Settings fixture ──────────────────────────────────────────────────────────

def _settings(**overrides):
    data = {
        # XRPL
        "use_mock_xrpl": True,
        "token_currency": "USD",
        "token_issuer_address": "",
        "treasury_wallet_seed": "",
        "treasury_wallet_address": "",
        "xrpl_network": "xrpl:1",
        "testnet_settlement_scale": 1.0,
        # Credential gate — ON by default for Phase 2.1
        "credential_kyc_enabled": True,
        "credential_type": "KYC",
        "credential_issuer_address": "rISSUER",
        "credential_issuer_seed": "",
        "credential_subject_seed": "",
        # Policy
        "policy_threshold_usd": 10_000.0,
        "policy_compliance_flag_score": 60,
        # FX
        "route_slippage_bps": 50,
        "route_partial_payment": False,
        "frankfurter_base_url": "https://api.frankfurter.dev/v1",
        # Compliance
        "opensanctions_api_key": "",
        "opensanctions_base_url": "",
        "opensanctions_dataset": "sanctions",
        "opensanctions_match_threshold": 0.85,
        "public_intel_enabled": False,
        # Plaid (disabled in tests)
        "plaid_client_id": "",
        "plaid_secret": "",
        "plaid_env": "sandbox",
        "plaid_watchlist_program_id_individual": "",
        "plaid_watchlist_program_id_entity": "",
        # Insurance (disabled in tests)
        "insurance_enabled": False,
        "insurance_cover_required_above_usd": 10_000.0,
        # Misc
        "openai_api_key": "",
        "openai_model": "gpt-4o",
        "firefly_public_key": "",
        "demo_mode": False,
        # Agent
        "agent_max_amount_usd": 50_000.0,
        "agent_enabled": True,
        "agent_sender_country": "CH",
        # Feature flags
        "x402_enabled": False,
        "delegation_enabled": False,
        "trade_finance_enabled": False,
        "mpt_enabled": False,
        "vault_enabled": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _patch(monkeypatch, **overrides):
    """Patch settings into every module that calls get_settings, and mock FX rates."""
    s = _settings(**overrides)
    for mod in (orchestrator, routing, credentials, compliance, audit):
        monkeypatch.setattr(mod, "get_settings", lambda _s=s: _s)
    # Avoid real HTTP calls for FX rates — USD→USD = 1.0.
    monkeypatch.setattr(routing, "_fetch_rate", _mock_rate)


async def _mock_rate(base: str, quote: str) -> float:
    return 1.0  # same-currency, keeps amounts predictable


def _intent(**overrides) -> PaymentIntent:
    data = {
        "from": "rTREASURY",
        "to": "rReceiver",
        "senderName": "Treasury AG",
        "senderCountry": "CH",
        "receiverName": "Supplier Corp",
        "receiverCountry": "US",
        "receiverEntityType": "company",
        "purpose": "supplier_payment",
        "amount": 500.0,
        "currency": "USD",
        "reference": "INV-GATE-001",
    }
    data.update(overrides)
    return PaymentIntent(**data)


# ── Core gate behaviour ───────────────────────────────────────────────────────

async def test_uncredentialed_receiver_escalates_to_hardware_approval(monkeypatch):
    """Un-KYC'd receiver → AML score raised above flag threshold → hardware approval."""
    _patch(monkeypatch)
    subject = next(iter(credentials.MOCK_UNVERIFIED_SUBJECTS))

    payment = await orchestrator.process_payment(_intent(to=subject))

    assert payment.status is PaymentStatus.pending_approval
    assert payment.compliance is not None
    assert payment.compliance.aml_score >= compliance.KYC_MISSING_SCORE  # 65 > flag score 60
    assert any("KYC credential" in f for f in payment.compliance.flags)
    assert payment.policy_decision is not None
    assert payment.policy_decision.requires_approval is True


async def test_credentialed_receiver_auto_settles(monkeypatch):
    """KYC-verified receiver → clean compliance → small payment auto-settles."""
    _patch(monkeypatch)
    credentials.reset_mock_state()

    # A receiver not in MOCK_UNVERIFIED_SUBJECTS is considered verified in mock mode.
    payment = await orchestrator.process_payment(_intent(to="rVERIFIED_RECEIVER"))

    assert payment.status is PaymentStatus.settled
    assert payment.compliance is not None
    assert payment.compliance.credential is not None
    assert payment.compliance.credential.verified is True
    assert payment.policy_decision is not None
    assert payment.policy_decision.requires_approval is False


async def test_issue_accept_flips_gate_escalate_to_settle(monkeypatch):
    """Full gate demo cycle: uncredentialed → escalated; issue+accept → auto-settle."""
    _patch(monkeypatch)
    credentials.reset_mock_state()
    subject = next(iter(credentials.MOCK_UNVERIFIED_SUBJECTS))

    # Step 1: payment escalates because subject has no credential.
    payment1 = await orchestrator.process_payment(_intent(to=subject))
    assert payment1.status is PaymentStatus.pending_approval

    # Step 2: issue + accept credential on behalf of the subject.
    await credentials.accept_credential(
        subject,
        issuer="rISSUER",
        credential_type="KYC",
    )

    # Step 3: retry — same amount, same subject — now auto-settles.
    payment2 = await orchestrator.process_payment(_intent(to=subject))
    assert payment2.status is PaymentStatus.settled
    assert payment2.compliance is not None
    assert payment2.compliance.credential is not None
    assert payment2.compliance.credential.verified is True

    credentials.reset_mock_state()


async def test_credential_gate_does_not_override_sanctions(monkeypatch):
    """Sanctioned counterparty stays blocked even after credential acceptance.

    A credential proves KYC identity; it can't override a sanctions designation.
    """
    _patch(monkeypatch)
    credentials.reset_mock_state()
    sanctioned = next(iter(compliance.SANCTIONED_ACCOUNTS))

    # Accept a (mock) credential for the sanctioned address.
    await credentials.accept_credential(sanctioned, issuer="rISSUER", credential_type="KYC")

    payment = await orchestrator.process_payment(_intent(to=sanctioned))

    assert payment.status is PaymentStatus.blocked
    assert payment.policy_decision is not None
    assert payment.policy_decision.blocked is True
    assert payment.policy_decision.rule_fired == "sanctions_block"

    credentials.reset_mock_state()


async def test_large_credentialed_payment_still_requires_hardware_approval(monkeypatch):
    """KYC credential removes the risk flag but cannot bypass the amount threshold.

    A $50,000 payment to a credentialed receiver must still go to Firefly approval
    because the amount exceeds POLICY_THRESHOLD_USD ($10,000).
    """
    _patch(monkeypatch)

    payment = await orchestrator.process_payment(
        _intent(to="rVERIFIED_RECEIVER", amount=50_000.0)
    )

    assert payment.status is PaymentStatus.pending_approval
    assert payment.policy_decision is not None
    assert payment.policy_decision.rule_fired == "amount_threshold"
    # KYC was verified — the escalation is purely due to amount, not credential.
    assert payment.compliance is not None
    assert payment.compliance.credential is not None
    assert payment.compliance.credential.verified is True


async def test_gate_disabled_does_not_check_credential(monkeypatch):
    """With CREDENTIAL_KYC_ENABLED=false, unverified subjects auto-settle (if otherwise clean)."""
    _patch(monkeypatch, credential_kyc_enabled=False)
    subject = next(iter(credentials.MOCK_UNVERIFIED_SUBJECTS))

    payment = await orchestrator.process_payment(_intent(to=subject))

    assert payment.status is PaymentStatus.settled
    assert payment.compliance is not None
    # Credential not checked → no KYC flag → no escalation for a small clean payment.
    assert not any("KYC credential" in f for f in payment.compliance.flags)


async def test_kyc_flag_score_is_above_default_compliance_flag_score():
    """Structural invariant: KYC_MISSING_SCORE must exceed COMPLIANCE_FLAG_SCORE.

    If it didn't, an un-KYC'd receiver wouldn't trigger escalation on its own.
    This is the code-level proof that the gate is wired correctly.
    """
    from app.policy.engine import COMPLIANCE_FLAG_SCORE
    assert compliance.KYC_MISSING_SCORE > COMPLIANCE_FLAG_SCORE, (
        f"KYC_MISSING_SCORE ({compliance.KYC_MISSING_SCORE}) must be > "
        f"COMPLIANCE_FLAG_SCORE ({COMPLIANCE_FLAG_SCORE}) or the gate is silent"
    )
