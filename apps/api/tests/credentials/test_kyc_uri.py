"""Tests for credentials/kyc/uri.py — Plaid-modelled verification step encoding.

All pure: no I/O, no DB, no network, no xrpl-py.
Covers: URI build/parse round-trip, step property helpers, score weights,
convenience constructors, and edge cases (missing fields, unknown values).
"""

from __future__ import annotations

import json

import pytest

from app.credentials.kyc.uri import (
    StepStatus,
    VerificationSteps,
    build_uri,
    full_pass,
    parse_uri,
    sanctions_only,
)


# ── URI build / parse round-trip ──────────────────────────────────────────────

def test_full_pass_round_trips():
    steps = full_pass(ref="KYC-001")
    uri = build_uri(steps)
    parsed = parse_uri(uri)

    assert parsed is not None
    assert parsed.documentary == StepStatus.pass_
    assert parsed.selfie == StepStatus.pass_
    assert parsed.kyc == StepStatus.pass_
    assert parsed.sanctions == StepStatus.pass_
    assert parsed.pep == StepStatus.pass_
    assert parsed.ref == "KYC-001"


def test_sanctions_only_round_trips():
    steps = sanctions_only(sanctioned=False, is_pep=False, ref="SCR-99")
    uri = build_uri(steps)
    parsed = parse_uri(uri)

    assert parsed is not None
    assert parsed.sanctions == StepStatus.pass_
    assert parsed.pep == StepStatus.pass_
    assert parsed.documentary == StepStatus.skip
    assert parsed.selfie == StepStatus.skip


def test_pep_flagged_round_trips():
    steps = sanctions_only(sanctioned=False, is_pep=True, ref="PEP-42")
    uri = build_uri(steps)
    parsed = parse_uri(uri)

    assert parsed is not None
    assert parsed.pep == StepStatus.flagged
    assert parsed.sanctions == StepStatus.pass_


def test_sanctions_flagged_round_trips():
    steps = sanctions_only(sanctioned=True, is_pep=False)
    uri = build_uri(steps)
    parsed = parse_uri(uri)

    assert parsed is not None
    assert parsed.sanctions == StepStatus.flagged


def test_partial_steps_only_encodes_non_skip():
    steps = VerificationSteps(
        documentary=StepStatus.pass_,
        selfie=StepStatus.pass_,
        # kyc, sanctions, pep left as skip
    )
    uri = build_uri(steps)
    payload = json.loads(uri)

    assert "doc" in payload
    assert "selfie" in payload
    assert "kyc" not in payload       # skip omitted
    assert "sanctions" not in payload
    assert "pep" not in payload


def test_failed_step_round_trips():
    steps = VerificationSteps(
        documentary=StepStatus.fail,
        selfie=StepStatus.pass_,
    )
    uri = build_uri(steps)
    parsed = parse_uri(uri)

    assert parsed.documentary == StepStatus.fail
    assert parsed.selfie == StepStatus.pass_


def test_uri_fits_in_256_byte_limit():
    steps = full_pass(ref="REF-" + "A" * 20)
    uri = build_uri(steps)
    assert len(uri) <= 256, f"URI too long: {len(uri)} chars"


# ── Step property helpers ─────────────────────────────────────────────────────

def test_identity_verified_requires_doc_and_selfie():
    both = VerificationSteps(
        documentary=StepStatus.pass_,
        selfie=StepStatus.pass_,
    )
    assert both.identity_verified is True

    doc_only = VerificationSteps(documentary=StepStatus.pass_)
    assert doc_only.identity_verified is False

    selfie_only = VerificationSteps(selfie=StepStatus.pass_)
    assert selfie_only.identity_verified is False


def test_sanctions_cleared_requires_pass():
    cleared = VerificationSteps(sanctions=StepStatus.pass_)
    assert cleared.sanctions_cleared is True

    skipped = VerificationSteps()
    assert skipped.sanctions_cleared is False

    flagged = VerificationSteps(sanctions=StepStatus.flagged)
    assert flagged.sanctions_cleared is False


def test_is_pep_requires_flagged():
    pep = VerificationSteps(pep=StepStatus.flagged)
    assert pep.is_pep is True

    clear = VerificationSteps(pep=StepStatus.pass_)
    assert clear.is_pep is False

    skip = VerificationSteps()
    assert skip.is_pep is False


def test_has_failures_detects_failed_steps():
    no_fail = VerificationSteps(documentary=StepStatus.pass_, selfie=StepStatus.pass_)
    assert no_fail.has_failures is False

    with_fail = VerificationSteps(documentary=StepStatus.fail)
    assert with_fail.has_failures is True


# ── AML weight ────────────────────────────────────────────────────────────────

def test_clean_full_pass_has_negative_or_zero_weight():
    steps = full_pass()
    assert steps.aml_weight() == 0


def test_pep_adds_weight():
    steps = VerificationSteps(pep=StepStatus.flagged)
    assert steps.aml_weight() >= 20


def test_sanctions_flagged_adds_weight():
    steps = VerificationSteps(sanctions=StepStatus.flagged)
    assert steps.aml_weight() >= 30


def test_doc_failure_adds_weight():
    steps = VerificationSteps(documentary=StepStatus.fail)
    assert steps.aml_weight() >= 15


def test_pep_and_sanctions_accumulate():
    steps = VerificationSteps(
        pep=StepStatus.flagged,
        sanctions=StepStatus.flagged,
    )
    assert steps.aml_weight() >= 50


# ── Risk flags ────────────────────────────────────────────────────────────────

def test_pep_flagged_produces_risk_flag():
    steps = VerificationSteps(pep=StepStatus.flagged)
    flags = steps.risk_flags()
    assert any("PEP" in f for f in flags)


def test_sanctions_flagged_produces_risk_flag():
    steps = VerificationSteps(sanctions=StepStatus.flagged)
    flags = steps.risk_flags()
    assert any("sanctions" in f for f in flags)


def test_documentary_fail_produces_risk_flag():
    steps = VerificationSteps(documentary=StepStatus.fail)
    flags = steps.risk_flags()
    assert any("ID scan failed" in f for f in flags)


def test_sanctions_skip_produces_risk_flag():
    steps = VerificationSteps(documentary=StepStatus.pass_)  # no sanctions step
    flags = steps.risk_flags()
    assert any("sanctions screen not recorded" in f for f in flags)


def test_full_pass_has_no_risk_flags():
    steps = full_pass()
    assert steps.risk_flags() == []


# ── parse_uri edge cases ──────────────────────────────────────────────────────

def test_parse_none_returns_none():
    assert parse_uri(None) is None


def test_parse_empty_string_returns_none():
    assert parse_uri("") is None


def test_parse_plain_url_returns_none():
    assert parse_uri("https://kyc.example.com/vc/abc123") is None


def test_parse_unknown_version_returns_none():
    bad = json.dumps({"v": 99, "doc": "pass"})
    assert parse_uri(bad) is None


def test_parse_unknown_status_value_treated_as_skip():
    uri = json.dumps({"v": 1, "doc": "unknown_future_value"})
    parsed = parse_uri(uri)
    assert parsed is not None
    assert parsed.documentary == StepStatus.skip


def test_parse_plaid_aliases():
    """Plaid uses 'success' and 'clear' — we accept both as pass."""
    uri = json.dumps({"v": 1, "doc": "success", "pep": "clear", "sanctions": "failed"})
    parsed = parse_uri(uri)
    assert parsed.documentary == StepStatus.pass_
    assert parsed.pep == StepStatus.pass_
    assert parsed.sanctions == StepStatus.fail


def test_parse_malformed_json_returns_none():
    assert parse_uri("{not valid json}") is None


# ── Credential URI ↔ compliance integration ───────────────────────────────────

def test_step_weight_fed_into_compliance_score(monkeypatch):
    """PEP-flagged credential raises the AML score in check_compliance."""
    from types import SimpleNamespace

    from app.schemas import CredentialStatus, VerificationStepStatus, VerificationSteps
    from app.tools import compliance, public_intel

    def _settings(**kw):
        return SimpleNamespace(
            opensanctions_api_key="",
            opensanctions_base_url="https://api.opensanctions.org",
            opensanctions_dataset="sanctions",
            opensanctions_match_threshold=0.85,
            public_intel_enabled=False,
            policy_threshold_usd=10_000.0,
        )

    def _intent():
        from app.schemas import PaymentIntent
        return PaymentIntent(**{
            "from": "rSender", "to": "rReceiver",
            "senderName": "Alice AG", "senderCountry": "CH",
            "receiverName": "Bob Smith", "receiverCountry": "GB",
            "receiverEntityType": "individual",
            "purpose": "supplier_payment", "amount": 500.0,
            "currency": "USD", "reference": "INV-001",
        })

    monkeypatch.setattr(compliance, "get_settings", _settings)
    monkeypatch.setattr(public_intel, "assess_public_intel",
                        lambda i: __import__("app.schemas", fromlist=["PublicIntelResult"])
                        .PublicIntelResult(score=0, confidence="test", flags=[], sources=[], summary=""))

    # Verified credential with PEP flag
    pep_steps = VerificationSteps(
        documentary=VerificationStepStatus.pass_,
        selfie=VerificationStepStatus.pass_,
        sanctions=VerificationStepStatus.pass_,
        pep=VerificationStepStatus.flagged,
    )
    pep_credential = CredentialStatus(
        checked=True, verified=True,
        subject="rReceiver", issuer="rISSUER",
        credential_type="KYC",
        reason="verified",
        verification_steps=pep_steps,
    )

    # Clean credential (no steps)
    clean_credential = CredentialStatus(
        checked=True, verified=True,
        subject="rReceiver", issuer="rISSUER",
        credential_type="KYC",
        reason="verified",
    )

    result_pep = compliance.check_compliance(_intent(), credential=pep_credential)
    result_clean = compliance.check_compliance(_intent(), credential=clean_credential)

    assert result_pep.aml_score > result_clean.aml_score, (
        "PEP-flagged credential should raise AML score above clean credential"
    )
    assert any("PEP" in f for f in result_pep.flags)
