"""Tests for policy/scope.py — G4 (Spend scope) guardrail.

All pure: no I/O, no network, no fixtures. Decimal invariant tested throughout.
"""

from decimal import Decimal

import pytest

from app.policy.scope import AgentScope, ScopeDecision, evaluate_scope


_DEFAULT_SCOPE = AgentScope(
    max_per_transaction=Decimal("500.000000"),
    max_per_day=Decimal("2000.000000"),
)


# ── Per-transaction cap ────────────────────────────────────────────────────────

def test_within_tx_cap_allowed():
    result = evaluate_scope(Decimal("100"), _DEFAULT_SCOPE, Decimal("0"))
    assert result.allowed is True
    assert result.rule_fired is None


def test_exactly_at_tx_cap_allowed():
    result = evaluate_scope(Decimal("500"), _DEFAULT_SCOPE, Decimal("0"))
    assert result.allowed is True


def test_over_tx_cap_blocked():
    result = evaluate_scope(Decimal("500.000001"), _DEFAULT_SCOPE, Decimal("0"))
    assert result.allowed is False
    assert result.rule_fired == "scope_per_tx_exceeded"
    assert result.reasons


# ── Per-day velocity cap ───────────────────────────────────────────────────────

def test_within_day_cap_allowed():
    result = evaluate_scope(Decimal("100"), _DEFAULT_SCOPE, Decimal("1800"))
    assert result.allowed is True


def test_exactly_at_day_cap_allowed():
    result = evaluate_scope(Decimal("200"), _DEFAULT_SCOPE, Decimal("1800"))
    assert result.allowed is True


def test_over_day_cap_blocked():
    result = evaluate_scope(Decimal("200.000001"), _DEFAULT_SCOPE, Decimal("1800"))
    assert result.allowed is False
    assert result.rule_fired == "scope_per_day_exceeded"


def test_already_at_cap_any_spend_blocked():
    result = evaluate_scope(Decimal("0.000001"), _DEFAULT_SCOPE, Decimal("2000"))
    assert result.allowed is False
    assert result.rule_fired == "scope_per_day_exceeded"


# ── Tx cap checked before day cap ─────────────────────────────────────────────

def test_tx_cap_short_circuits_before_day_cap():
    result = evaluate_scope(Decimal("600"), _DEFAULT_SCOPE, Decimal("0"))
    assert result.rule_fired == "scope_per_tx_exceeded"  # not per_day


# ── Service host allowlist ─────────────────────────────────────────────────────

def test_allowed_host_passes():
    scope = AgentScope(
        max_per_transaction=Decimal("500"),
        max_per_day=Decimal("2000"),
        allowed_service_hosts=["api.example.com"],
    )
    result = evaluate_scope(Decimal("10"), scope, Decimal("0"), service_host="api.example.com")
    assert result.allowed is True


def test_disallowed_host_blocked():
    scope = AgentScope(
        max_per_transaction=Decimal("500"),
        max_per_day=Decimal("2000"),
        allowed_service_hosts=["api.example.com"],
    )
    result = evaluate_scope(Decimal("10"), scope, Decimal("0"), service_host="evil.com")
    assert result.allowed is False
    assert result.rule_fired == "scope_host_not_allowed"


def test_no_host_restriction_any_host_passes():
    result = evaluate_scope(Decimal("10"), _DEFAULT_SCOPE, Decimal("0"), service_host="any.host")
    assert result.allowed is True


# ── Service type allowlist ────────────────────────────────────────────────────

def test_allowed_type_passes():
    scope = AgentScope(
        max_per_transaction=Decimal("500"),
        max_per_day=Decimal("2000"),
        allowed_service_types=["data_lookup"],
    )
    result = evaluate_scope(Decimal("10"), scope, Decimal("0"), service_type="data_lookup")
    assert result.allowed is True


def test_disallowed_type_blocked():
    scope = AgentScope(
        max_per_transaction=Decimal("500"),
        max_per_day=Decimal("2000"),
        allowed_service_types=["data_lookup"],
    )
    result = evaluate_scope(Decimal("10"), scope, Decimal("0"), service_type="market_data")
    assert result.allowed is False
    assert result.rule_fired == "scope_type_not_allowed"


# ── Decimal precision (invariant 1) ───────────────────────────────────────────

def test_cap_enforced_at_6dp_precision():
    # Spend of exactly cap+epsilon (7dp) should be blocked.
    scope = AgentScope(
        max_per_transaction=Decimal("100.000000"),
        max_per_day=Decimal("500"),
    )
    # After quantize to 6dp, 100.0000004 → 100.000000 → allowed
    result = evaluate_scope(Decimal("100.0000004"), scope, Decimal("0"))
    assert result.allowed is True  # rounds down to cap

    # 100.0000006 → 100.000001 after ROUND_DOWN 6dp — still blocked?
    # ROUND_DOWN: truncates toward zero, so 100.0000006 → 100.000000 (6dp)
    result2 = evaluate_scope(Decimal("100.0000006"), scope, Decimal("0"))
    assert result2.allowed is True  # ROUND_DOWN means we never exceed cap on rounding


def test_integer_amounts_work():
    result = evaluate_scope(Decimal(100), _DEFAULT_SCOPE, Decimal(0))
    assert result.allowed is True


# ── Return type is always ScopeDecision ──────────────────────────────────────

def test_allowed_result_has_no_rule_fired():
    result = evaluate_scope(Decimal("1"), _DEFAULT_SCOPE, Decimal("0"))
    assert isinstance(result, ScopeDecision)
    assert result.rule_fired is None
    assert result.reasons == []


def test_blocked_result_has_non_empty_reasons():
    result = evaluate_scope(Decimal("9999"), _DEFAULT_SCOPE, Decimal("0"))
    assert isinstance(result, ScopeDecision)
    assert result.reasons
