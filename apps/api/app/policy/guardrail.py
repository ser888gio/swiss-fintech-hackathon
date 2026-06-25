"""Unified Guardrail Evaluator — ARS G1–G7 constraint engine.

Pure function, no I/O. Callers pre-fetch all inputs atomically and pass them in.

Context dispatch — which guardrails run per context_kind:
  payment          G2 sanctions, G6 threshold
  service_payment  G1 KYA, G4 scope
  delegation_fund  G1 KYA, G4 scope, G5 delegation
  loan_underwrite  G1 KYA, G2 sanctions, G6 threshold
  insurance_payout G2 sanctions, G6 threshold

G3 (VASP/AML enrichment) and G7 (hardware veto) are placeholders whose trail
slots appear so audit records have consistent structure as they are wired in.
"""

from __future__ import annotations

from decimal import Decimal

from ..policy import engine as threshold_engine
from ..policy.scope import AgentScope, ScopeDecision, evaluate_scope
from ..schemas import ConstraintResult, GuardrailResult


def evaluate_guardrails(
    *,
    context_kind: str,
    agent_credential_verified: bool = False,
    sanctioned: bool = False,
    aml_score: int = 0,
    amount: Decimal = Decimal("0"),
    spent_today: Decimal = Decimal("0"),
    scope_max_per_tx: Decimal = Decimal("0"),
    scope_max_per_day: Decimal = Decimal("0"),
    allowed_service_hosts: list[str] | None = None,
    allowed_service_types: list[str] | None = None,
    service_host: str | None = None,
    service_type: str | None = None,
    delegation_budget_remaining: Decimal | None = None,
    threshold_usd: float = threshold_engine.THRESHOLD_USD,
    flag_score: int = threshold_engine.COMPLIANCE_FLAG_SCORE,
) -> ConstraintResult:
    """Run the guardrail chain for the given context and return a full trail.

    Returns ConstraintResult(allowed=True) when all guardrails pass.
    Short-circuits on the first failure and sets action to "block" or "review".
    """
    trail: list[GuardrailResult] = []
    guardrails = _CONTEXT_GUARDRAILS.get(context_kind, [])

    kw = dict(
        agent_credential_verified=agent_credential_verified,
        sanctioned=sanctioned,
        aml_score=aml_score,
        amount=amount,
        spent_today=spent_today,
        scope_max_per_tx=scope_max_per_tx,
        scope_max_per_day=scope_max_per_day,
        allowed_service_hosts=allowed_service_hosts,
        allowed_service_types=allowed_service_types,
        service_host=service_host,
        service_type=service_type,
        delegation_budget_remaining=delegation_budget_remaining,
        threshold_usd=threshold_usd,
        flag_score=flag_score,
    )

    for name in guardrails:
        step = _GUARDRAIL_FNS[name](**kw)
        trail.append(step)
        if not step.passed:
            action = "review" if name == "G6_threshold" else "block"
            return ConstraintResult(
                allowed=False,
                action=action,
                rule_fired=step.rule_fired,
                reasons=[step.reason] if step.reason else [],
                guardrail_trail=trail,
            )

    return ConstraintResult(allowed=True, action="allow", guardrail_trail=trail)


# ── Per-guardrail pure functions ──────────────────────────────────────────────


def _g1_kya(**kw) -> GuardrailResult:
    ok = kw["agent_credential_verified"]
    return GuardrailResult(
        name="G1_kya",
        passed=ok,
        rule_fired=None if ok else "kya_unverified",
        reason=None if ok else "agent credential not verified",
    )


def _g2_sanctions(**kw) -> GuardrailResult:
    blocked = kw["sanctioned"]
    return GuardrailResult(
        name="G2_sanctions",
        passed=not blocked,
        rule_fired="sanctions_block" if blocked else None,
        reason="counterparty on sanctions list" if blocked else None,
    )


def _g3_aml(**kw) -> GuardrailResult:
    # Placeholder — AML enrichment not yet wired to an external VASP source.
    return GuardrailResult(
        name="G3_aml", passed=True, rule_fired=None, reason="not_wired"
    )


def _g4_scope(**kw) -> GuardrailResult:
    scope = AgentScope(
        max_per_transaction=kw["scope_max_per_tx"],
        max_per_day=kw["scope_max_per_day"],
        allowed_service_hosts=kw["allowed_service_hosts"],
        allowed_service_types=kw["allowed_service_types"],
    )
    result: ScopeDecision = evaluate_scope(
        kw["amount"],
        scope,
        kw["spent_today"],
        service_host=kw["service_host"],
        service_type=kw["service_type"],
    )
    return GuardrailResult(
        name="G4_scope",
        passed=result.allowed,
        rule_fired=result.rule_fired,
        reason=result.reasons[0] if result.reasons else None,
    )


def _g5_delegation(**kw) -> GuardrailResult:
    budget = kw["delegation_budget_remaining"]
    if budget is None:
        return GuardrailResult(
            name="G5_delegation", passed=True, rule_fired=None, reason="no_grant"
        )
    ok = kw["amount"] <= budget
    return GuardrailResult(
        name="G5_delegation",
        passed=ok,
        rule_fired=None if ok else "delegation_budget_exceeded",
        reason=None
        if ok
        else f"spend {kw['amount']} exceeds remaining budget {budget}",
    )


def _g6_threshold(**kw) -> GuardrailResult:
    decision = threshold_engine.evaluate(
        float(kw["amount"]),
        kw["aml_score"],
        sanctioned=False,  # G2 already checked sanctions above
        threshold_usd=kw["threshold_usd"],
        flag_score=kw["flag_score"],
    )
    ok = not decision.requires_approval and not decision.blocked
    return GuardrailResult(
        name="G6_threshold",
        passed=ok,
        rule_fired=decision.rule_fired,
        reason="; ".join(decision.reasons) if decision.reasons else None,
    )


def _g7_hardware_veto(**kw) -> GuardrailResult:
    # Hardware veto is enforced out-of-band via Firefly signature verification in
    # release_payment — not at intake time.
    return GuardrailResult(
        name="G7_hardware_veto",
        passed=True,
        rule_fired=None,
        reason="enforced_at_release",
    )


# ── Dispatch tables ───────────────────────────────────────────────────────────

_GUARDRAIL_FNS = {
    "G1_kya": _g1_kya,
    "G2_sanctions": _g2_sanctions,
    "G3_aml": _g3_aml,
    "G4_scope": _g4_scope,
    "G5_delegation": _g5_delegation,
    "G6_threshold": _g6_threshold,
    "G7_hardware_veto": _g7_hardware_veto,
}

_CONTEXT_GUARDRAILS: dict[str, list[str]] = {
    "payment": ["G2_sanctions", "G6_threshold"],
    "agent_payment": ["G2_sanctions", "G4_scope", "G6_threshold"],
    "service_payment": ["G1_kya", "G4_scope"],
    "delegation_fund": ["G1_kya", "G4_scope", "G5_delegation"],
    "loan_underwrite": ["G1_kya", "G2_sanctions", "G6_threshold"],
    "insurance_payout": ["G2_sanctions", "G3_aml", "G6_threshold", "G7_hardware_veto"],
}
