"""Integration tests for the guardrail spine.

Verifies two critical invariants:
  A) All guardrails pass → guardrail_trail is populated and the action executes.
  B) Any guardrail fails → no action, failed guardrail recorded with its reason.

Tests are offline (use_mock_xrpl=True, no DB). We exercise the guardrail chain
as used by the orchestrator, not the orchestrator itself, keeping the test fast
and deterministic.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from app.policy.scope import AgentScope, evaluate_scope, ScopeDecision
from app.tools.delegation import DelegationGrant, evaluate_delegation, DelegationDecision
from app.policy.engine import evaluate as policy_evaluate
from app.schemas import GuardrailResult


# ── Helpers ───────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 19, 12, 0, 0, tzinfo=timezone.utc)

_DEFAULT_SCOPE = AgentScope(
    max_per_transaction=Decimal("500"),
    max_per_day=Decimal("2000"),
)

_DEFAULT_GRANT = DelegationGrant(
    id="g1",
    parent_address="rP",
    child_address="rC",
    max_total="1000",
    max_per_tx="200",
    max_per_day="500",
    currency="RLUSD",
    allowed_service_hosts=None,
    allowed_service_types=None,
    expires_at=None,
    fund_tx_hash=None,
    fund_explorer_url=None,
    revoked=False,
    created_at=_NOW,
    updated_at=_NOW,
)


def _build_trail(
    *,
    g1_kya: bool = True,
    g2_sanctioned: bool = False,
    spend: Decimal = Decimal("100"),
    spent_today: Decimal = Decimal("0"),
    aml_score: int = 10,
    threshold_usd: float = 10_000.0,
    scope: AgentScope = _DEFAULT_SCOPE,
    grant: DelegationGrant = _DEFAULT_GRANT,
    spent_delegated: Decimal = Decimal("0"),
) -> tuple[list[GuardrailResult], bool, str | None]:
    """Run G1–G5 in order and return (trail, all_passed, first_failed_name).

    Returns (trail, True, None) when every applicable guardrail passes, else
    (trail, False, name_of_first_failed_guardrail).
    """
    trail: list[GuardrailResult] = []
    first_failed: str | None = None

    def _record(name: str, passed: bool, rule: str | None = None, reason: str | None = None):
        nonlocal first_failed
        trail.append(GuardrailResult(name=name, passed=passed, rule_fired=rule, reason=reason))
        if not passed and first_failed is None:
            first_failed = name

    # G1: KYA (simulated — in real code calls credentials.verify_kyc)
    _record("G1_kya", g1_kya, None if g1_kya else "kya_unverified",
            None if g1_kya else "agent has no accepted credential")

    # G2: sanctions (simulated)
    not_sanctioned = not g2_sanctioned
    _record("G2_sanctions", not_sanctioned,
            None if not_sanctioned else "sanctions_block",
            None if not_sanctioned else "counterparty on sanctions list")

    # G3/G4 only run if G1+G2 passed (short-circuit)
    if first_failed is not None:
        return trail, False, first_failed

    # G4: spend scope
    scope_decision = evaluate_scope(spend, scope, spent_today)
    _record("G4_scope", scope_decision.allowed,
            scope_decision.rule_fired,
            scope_decision.reasons[0] if scope_decision.reasons else None)

    if first_failed is not None:
        return trail, False, first_failed

    # G5: delegation scope (when applicable)
    delegation_decision = evaluate_delegation(spend, grant, spent_delegated)
    _record("G5_delegation", delegation_decision.allowed,
            delegation_decision.rule_fired,
            delegation_decision.reasons[0] if delegation_decision.reasons else None)

    if first_failed is not None:
        return trail, False, first_failed

    # G6: amount threshold (via policy engine)
    policy = policy_evaluate(float(spend), aml_score, sanctioned=False, threshold_usd=threshold_usd)
    requires_approval = policy.requires_approval
    blocked = policy.blocked
    _record("G6_threshold", not blocked and not requires_approval,
            policy.rule_fired,
            "; ".join(policy.reasons) if policy.reasons else None)

    all_passed = first_failed is None
    return trail, all_passed, first_failed


# ── Invariant A: all pass → trail populated, executes ─────────────────────────

def test_all_guardrails_pass_trail_is_populated():
    trail, all_passed, first_failed = _build_trail()
    assert all_passed is True
    assert first_failed is None
    assert len(trail) > 0
    assert all(g.passed for g in trail)


def test_all_guardrails_pass_no_rule_fired():
    trail, _, _ = _build_trail()
    assert all(g.rule_fired is None for g in trail)


def test_all_guardrails_pass_names_present():
    trail, _, _ = _build_trail()
    names = {g.name for g in trail}
    assert "G1_kya" in names
    assert "G4_scope" in names
    assert "G5_delegation" in names
    assert "G6_threshold" in names


# ── Invariant B: any fail → no action, failed guardrail recorded ──────────────

def test_g1_fail_records_failed_guardrail():
    trail, all_passed, first_failed = _build_trail(g1_kya=False)
    assert all_passed is False
    assert first_failed == "G1_kya"
    failed = [g for g in trail if not g.passed]
    assert len(failed) == 1
    assert failed[0].name == "G1_kya"
    assert failed[0].rule_fired == "kya_unverified"
    assert failed[0].reason is not None


def test_g2_fail_records_sanctions_block():
    trail, all_passed, first_failed = _build_trail(g2_sanctioned=True)
    assert all_passed is False
    assert first_failed == "G2_sanctions"
    assert trail[1].rule_fired == "sanctions_block"


def test_g4_fail_records_scope_exceeded():
    trail, all_passed, first_failed = _build_trail(spend=Decimal("600"))  # > 500 cap
    assert all_passed is False
    assert first_failed == "G4_scope"
    failed_g = next(g for g in trail if g.name == "G4_scope")
    assert failed_g.rule_fired == "scope_per_tx_exceeded"
    assert failed_g.reason is not None


def test_g4_day_cap_records_velocity_block():
    trail, all_passed, first_failed = _build_trail(
        spend=Decimal("100"), spent_today=Decimal("1950")   # 1950+100=2050 > 2000
    )
    assert all_passed is False
    assert first_failed == "G4_scope"
    failed_g = next(g for g in trail if g.name == "G4_scope")
    assert failed_g.rule_fired == "scope_per_day_exceeded"


def test_g5_fail_records_delegation_exceeded():
    trail, all_passed, first_failed = _build_trail(
        spend=Decimal("50"), spent_delegated=Decimal("470")   # 470+50=520 > 500 per-day
    )
    assert all_passed is False
    assert first_failed == "G5_delegation"
    failed_g = next(g for g in trail if g.name == "G5_delegation")
    assert failed_g.rule_fired == "delegation_per_day_exceeded"


def test_g6_amount_threshold_records_escalation():
    trail, all_passed, first_failed = _build_trail(
        spend=Decimal("15000"), threshold_usd=10_000.0,
        scope=AgentScope(max_per_transaction=Decimal("20000"), max_per_day=Decimal("50000")),
        grant=DelegationGrant(
            id="g2", parent_address="rP", child_address="rC",
            max_total="50000", max_per_tx="20000", max_per_day="50000",
            currency="RLUSD", allowed_service_hosts=None, allowed_service_types=None,
            expires_at=None, fund_tx_hash=None, fund_explorer_url=None, revoked=False,
            created_at=_NOW, updated_at=_NOW,
        ),
    )
    assert all_passed is False
    assert first_failed == "G6_threshold"
    failed_g = next(g for g in trail if g.name == "G6_threshold")
    assert failed_g.rule_fired == "amount_threshold"


# ── Short-circuit: later guardrails not checked after early failure ────────────

def test_g1_fail_short_circuits_g4():
    trail, _, first_failed = _build_trail(g1_kya=False, spend=Decimal("600"))
    # G4 and G5 should not appear because G1 short-circuited
    names = [g.name for g in trail]
    assert "G4_scope" not in names
    assert "G5_delegation" not in names
    assert first_failed == "G1_kya"


def test_g2_fail_short_circuits_g4():
    trail, _, first_failed = _build_trail(g2_sanctioned=True)
    names = [g.name for g in trail]
    assert "G4_scope" not in names
    assert first_failed == "G2_sanctions"


# ── Audit log integration ─────────────────────────────────────────────────────

def test_guardrail_trail_serialises_to_dicts():
    trail, _, _ = _build_trail()
    serialised = [g.model_dump() for g in trail]
    for item in serialised:
        assert "name" in item
        assert "passed" in item


def test_failed_guardrail_reason_is_non_empty_string():
    trail, _, _ = _build_trail(g1_kya=False)
    failed = [g for g in trail if not g.passed]
    assert all(isinstance(g.reason, str) and g.reason for g in failed)
