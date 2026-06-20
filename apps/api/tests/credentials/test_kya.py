"""Tests for KYA (Know Your Agent) — URI codec, credential tool, constraint engine.

All pure / mock-mode: no network, no DB, no XRPL node.
Covers:
  - kya/uri    : build/parse round-trips, convenience constructors, edge cases
  - kya/tool   : issue / verify in mock mode, auto-seed, scope check
  - XRPLConstraintEngine : G1 KYA, G2 sanctions, G3 AML, G4 scope guardrails
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest


# ── kya/uri module ────────────────────────────────────────────────────────────

from app.credentials.kya.uri import (
    AgentIdentity,
    AgentScope,
    AgentType,
    build_kya_uri,
    monitor_identity,
    orchestrator_identity,
    parse_kya_uri,
    sub_agent_identity,
)


def test_orchestrator_round_trip():
    identity = orchestrator_identity(principal="rTREASURY", ref="demo-01")
    uri = build_kya_uri(identity)
    parsed = parse_kya_uri(uri)

    assert parsed is not None
    assert parsed.agent_type == AgentType.orchestrator
    assert parsed.principal == "rTREASURY"
    assert parsed.ref == "demo-01"
    assert parsed.can_pay()
    assert parsed.can_delegate()
    assert parsed.can_issue_credentials()
    assert parsed.has_scope(AgentScope.x402)


def test_sub_agent_round_trip():
    identity = sub_agent_identity(
        principal="rORG",
        scopes=[AgentScope.payment, AgentScope.x402],
        ref="sub-02",
    )
    uri = build_kya_uri(identity)
    parsed = parse_kya_uri(uri)

    assert parsed is not None
    assert parsed.agent_type == AgentType.sub_agent
    assert parsed.can_pay()
    assert not parsed.can_delegate()
    assert not parsed.can_issue_credentials()


def test_monitor_round_trip():
    identity = monitor_identity(principal="rAUDITOR")
    uri = build_kya_uri(identity)
    parsed = parse_kya_uri(uri)

    assert parsed is not None
    assert parsed.agent_type == AgentType.monitor
    assert parsed.has_scope(AgentScope.read_only)
    assert not parsed.can_pay()


def test_uri_fits_in_256_byte_limit():
    identity = orchestrator_identity(
        principal="r" + "A" * 33,  # max-length XRPL address
        ref="REF-" + "X" * 20,
    )
    uri = build_kya_uri(identity)
    assert len(uri) <= 256, f"KYA URI too long: {len(uri)} chars"


def test_parse_none_returns_none():
    assert parse_kya_uri(None) is None


def test_parse_empty_returns_none():
    assert parse_kya_uri("") is None


def test_parse_wrong_version_returns_none():
    # v=1 is KYC steps, not KYA
    bad = json.dumps({"v": 1, "t": "orch"})
    assert parse_kya_uri(bad) is None


def test_parse_malformed_json_returns_none():
    assert parse_kya_uri("{not valid json}") is None


def test_parse_unknown_agent_type_becomes_unknown():
    uri = json.dumps({"v": 2, "t": "future_type", "s": ["pay"]})
    parsed = parse_kya_uri(uri)
    assert parsed is not None
    assert parsed.agent_type == AgentType.unknown


def test_parse_unknown_scope_silently_dropped():
    uri = json.dumps({"v": 2, "t": "orch", "s": ["pay", "future_scope"]})
    parsed = parse_kya_uri(uri)
    assert parsed is not None
    assert AgentScope.payment in parsed.scopes
    assert len(parsed.scopes) == 1  # unknown scope dropped


def test_scope_summary_empty_when_no_scopes():
    identity = AgentIdentity()
    assert identity.scope_summary == "none"


def test_scope_summary_lists_all():
    identity = monitor_identity(principal="rX")
    assert "compliance" in identity.scope_summary
    assert "read_only" in identity.scope_summary


# ── kya/tool module ───────────────────────────────────────────────────────────

import asyncio

from app.credentials.kya.tool import (
    issue_kya_credential,
    reset_kya_mock_state,
    verify_agent_kya,
)


@pytest.fixture(autouse=True)
def _reset_kya(monkeypatch):
    """Isolate mock KYA state and ensure use_mock_xrpl=True for all tests."""
    reset_kya_mock_state()

    def _mock_settings(**kw):
        return SimpleNamespace(
            use_mock_xrpl=True,
            credential_issuer_address="rISSUER",
            token_issuer_address="rISSUER",
            credential_issuer_seed="",
            treasury_wallet_address="rTREASURY_MOCK",
            policy_compliance_flag_score=60,
            agent_max_amount_usd=50_000.0,
        )

    import app.credentials.kya.tool as ac_mod
    monkeypatch.setattr(ac_mod, "get_settings", _mock_settings)

    import app.ars.constraint_engine as ce_mod
    monkeypatch.setattr(ce_mod, "get_settings", _mock_settings)

    yield
    reset_kya_mock_state()


def _run(coro):
    return asyncio.run(coro)


def test_issue_and_verify_orchestrator():
    identity = orchestrator_identity(principal="rORG", ref="test")
    result = _run(issue_kya_credential(agent_address="rAGENT1", identity=identity))

    assert result.status == "accepted"
    assert result.mock is True
    assert "pay" in result.uri or "payment" in result.uri  # short-key encoded

    status = _run(verify_agent_kya("rAGENT1"))
    assert status.verified is True
    assert status.agent_type == "orchestrator"
    assert "payment" in status.scopes


def test_verify_missing_credential():
    status = _run(verify_agent_kya("rUNKNOWN_AGENT"))
    # auto-seed only applies to treasury wallet; unknown address has no credential
    assert status.verified is False
    assert "No KYA credential" in status.reason


def test_auto_seed_treasury_wallet():
    """Treasury wallet address is auto-credentialed as orchestrator in mock mode."""
    status = _run(verify_agent_kya("rTREASURY_MOCK"))
    assert status.verified is True
    assert status.agent_type == "orchestrator"


def test_scope_check_pass():
    identity = orchestrator_identity(principal="rORG")
    _run(issue_kya_credential(agent_address="rAGENT2", identity=identity))

    status = _run(verify_agent_kya("rAGENT2", required_scope=AgentScope.payment))
    assert status.verified is True
    assert status.scope_ok is True


def test_scope_check_fail():
    identity = monitor_identity(principal="rORG")  # read-only, no payment scope
    _run(issue_kya_credential(agent_address="rMONITOR", identity=identity))

    status = _run(verify_agent_kya("rMONITOR", required_scope=AgentScope.payment))
    assert status.verified is False
    assert status.scope_ok is False
    assert "payment" in status.scope_reason


def test_issue_response_contains_identity_dict():
    identity = sub_agent_identity(principal="rPARENT", scopes=[AgentScope.x402])
    result = _run(issue_kya_credential(agent_address="rSUB", identity=identity))

    assert result.identity["agent_type"] == "sub_agent"
    assert "x402" in result.identity["scopes"]


# ── XRPLConstraintEngine ──────────────────────────────────────────────────────

from app.ars.constraint_engine import XRPLConstraintEngine


def _evaluate(**kwargs):
    engine = XRPLConstraintEngine()
    defaults = dict(
        context_kind="payment",
        agent_address="rAGENT_OK",
        counterparty="rRECEIVER",
        amount=Decimal("100"),
        currency="RLUSD",
        aml_score=10,
        sanctioned=False,
        agent_credential_verified=True,
        spent_today=Decimal("0"),
        scope_max_per_tx=Decimal("10000"),
        scope_max_per_day=Decimal("50000"),
    )
    defaults.update(kwargs)
    return asyncio.run(engine.evaluate(**defaults))


def test_g1_blocks_uncredentialed_agent():
    result = _evaluate(agent_address="rNO_CRED_EVER")
    assert result.allowed is False
    assert result.rule_fired == "G1_no_kya_credential"
    assert any(o.name == "G1_kya" and not o.passed for o in result.guardrail_trail)


def test_g1_passes_treasury_autoseed():
    """Auto-seeded treasury wallet passes G1."""
    result = _evaluate(agent_address="rTREASURY_MOCK")
    assert result.allowed is True


def test_g2_blocks_sanctioned():
    identity = orchestrator_identity(principal="rORG")
    _run(issue_kya_credential(agent_address="rAGENT_SANC", identity=identity))
    result = _evaluate(agent_address="rAGENT_SANC", sanctioned=True)
    assert result.allowed is False
    assert result.rule_fired == "G2_sanctioned"


def test_g3_review_on_high_aml():
    identity = orchestrator_identity(principal="rORG")
    _run(issue_kya_credential(agent_address="rAGENT_AML", identity=identity))
    result = _evaluate(agent_address="rAGENT_AML", aml_score=75)
    assert result.allowed is False
    assert result.action == "review"
    assert "G3" in result.rule_fired


def test_g4_blocks_over_per_tx_cap():
    identity = orchestrator_identity(principal="rORG")
    _run(issue_kya_credential(agent_address="rAGENT_CAP", identity=identity))
    result = _evaluate(
        agent_address="rAGENT_CAP",
        amount=Decimal("5000"),
        scope_max_per_tx=Decimal("1000"),
    )
    assert result.allowed is False
    assert result.rule_fired == "G4_per_tx_cap"


def test_g4_blocks_over_daily_cap():
    identity = orchestrator_identity(principal="rORG")
    _run(issue_kya_credential(agent_address="rAGENT_DAY", identity=identity))
    result = _evaluate(
        agent_address="rAGENT_DAY",
        amount=Decimal("100"),
        spent_today=Decimal("9950"),
        scope_max_per_day=Decimal("10000"),
    )
    assert result.allowed is False
    assert result.rule_fired == "G4_daily_cap"


def test_full_pass_all_guardrails():
    identity = orchestrator_identity(principal="rORG")
    _run(issue_kya_credential(agent_address="rAGENT_FULL", identity=identity))
    result = _evaluate(agent_address="rAGENT_FULL")
    assert result.allowed is True
    assert result.action == "allow"
    assert result.rule_fired is None
    # All 7 guardrails evaluated
    assert len(result.guardrail_trail) == 7
    assert all(g.passed for g in result.guardrail_trail)


def test_guardrail_trail_stops_at_first_failure():
    """When G1 fails, G2–G7 are not evaluated."""
    result = _evaluate(agent_address="rNOCRED_STOP")
    assert result.allowed is False
    # Only G1 in trail
    assert len(result.guardrail_trail) == 1
    assert result.guardrail_trail[0].name == "G1_kya"
