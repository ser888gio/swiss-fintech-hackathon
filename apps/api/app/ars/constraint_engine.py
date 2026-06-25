"""ARS Concrete Constraint Engine — G1 through G7 guardrail chain.

Implements the ConstraintEngine ABC from ars/base.py using the deterministic
policy and scope tools already in the codebase.

Guardrail order (first failure blocks):
  G1  KYA          Agent wallet must hold an accepted KYA credential.
  G2  Sanctions    Counterparty must not be sanctioned (AML score < block threshold).
  G3  AML score    AML score must be below the configured flag threshold.
  G4  Scope        Spend must fit within the agent's per-tx and daily caps.
  G5  Delegation   Sub-agent spend must fit within the remaining delegation budget.
  G6  Service host Request host must be in the allowlist (when allowlist is set).
  G7  Amount cap   Requested amount must not exceed the global agent max (50k USD).

All inputs are passed in by the caller, which fetches them atomically from the
store + KYA verification tool. The engine is pure within an async context:
it calls async tools but does not mutate any store itself.

Policy boundary: this engine only *reports* pass/fail for each guardrail. Whether
to block, review, or allow is read from the ConstraintResult by the orchestrator;
the LLM never interprets these results — only the orchestrator's policy code does.
"""

from __future__ import annotations

from decimal import Decimal

from .base import (
    ConstraintEngine,
    ConstraintResult,
    ContextKind,
    GuardrailOutcome,
)
from ..config import get_settings
from ..credentials.kya import tool as agent_credentials
from ..credentials.kya.uri import AgentScope


class XRPLConstraintEngine(ConstraintEngine):
    """Concrete ARS constraint engine for the XRPL treasury system."""

    async def evaluate(
        self,
        *,
        context_kind: ContextKind,
        agent_address: str,
        counterparty: str | None,
        amount: Decimal,
        currency: str,
        aml_score: int,
        sanctioned: bool,
        agent_credential_verified: bool,
        spent_today: Decimal,
        scope_max_per_tx: Decimal,
        scope_max_per_day: Decimal,
        allowed_service_hosts: list[str] | None = None,
        service_host: str | None = None,
        delegation_budget_remaining: Decimal | None = None,
    ) -> ConstraintResult:
        settings = get_settings()
        trail: list[GuardrailOutcome] = []
        reasons: list[str] = []

        # ── G1: KYA — agent must hold an accepted KYA credential ─────────────
        required_scope = _context_to_scope(context_kind)
        kya_status = await agent_credentials.verify_agent_kya(
            agent_address, required_scope
        )
        g1_passed = kya_status.verified and kya_status.scope_ok
        g1_reason = kya_status.reason if not g1_passed else None
        trail.append(
            GuardrailOutcome(
                name="G1_kya",
                passed=g1_passed,
                rule_fired="G1_no_kya_credential" if not g1_passed else None,
                reason=g1_reason,
            )
        )
        if not g1_passed:
            reasons.append(f"G1 KYA: {kya_status.reason}")
            return ConstraintResult(
                allowed=False,
                action="block",
                rule_fired="G1_no_kya_credential",
                reasons=reasons,
                guardrail_trail=trail,
            )

        # ── G2: Sanctions — hard block ────────────────────────────────────────
        g2_passed = not sanctioned
        trail.append(
            GuardrailOutcome(
                name="G2_sanctions",
                passed=g2_passed,
                rule_fired="G2_sanctioned" if not g2_passed else None,
                reason="Counterparty is sanctioned" if not g2_passed else None,
            )
        )
        if not g2_passed:
            reasons.append("G2 Sanctions: counterparty is sanctioned — hard block")
            return ConstraintResult(
                allowed=False,
                action="block",
                rule_fired="G2_sanctioned",
                reasons=reasons,
                guardrail_trail=trail,
            )

        # ── G3: AML score — flag threshold triggers review ────────────────────
        threshold = settings.policy_compliance_flag_score
        g3_passed = aml_score < threshold
        trail.append(
            GuardrailOutcome(
                name="G3_aml_score",
                passed=g3_passed,
                rule_fired=f"G3_aml_score_ge_{threshold}" if not g3_passed else None,
                reason=f"AML score {aml_score} ≥ threshold {threshold}"
                if not g3_passed
                else None,
            )
        )
        if not g3_passed:
            reasons.append(
                f"G3 AML: score {aml_score} exceeds flag threshold {threshold}"
            )
            return ConstraintResult(
                allowed=False,
                action="review",
                rule_fired=f"G3_aml_score_ge_{threshold}",
                reasons=reasons,
                guardrail_trail=trail,
            )

        # ── G4: Scope — per-tx and daily spend caps ───────────────────────────
        g4_per_tx = amount <= scope_max_per_tx
        g4_daily = (spent_today + amount) <= scope_max_per_day
        g4_passed = g4_per_tx and g4_daily
        g4_rule = None
        if not g4_per_tx:
            g4_rule = "G4_per_tx_cap"
        elif not g4_daily:
            g4_rule = "G4_daily_cap"
        trail.append(
            GuardrailOutcome(
                name="G4_scope",
                passed=g4_passed,
                rule_fired=g4_rule,
                reason=(
                    f"Amount {amount} {currency} exceeds per-tx cap {scope_max_per_tx}"
                    if not g4_per_tx
                    else f"Daily total {spent_today + amount} {currency} exceeds cap {scope_max_per_day}"
                )
                if not g4_passed
                else None,
            )
        )
        if not g4_passed:
            reasons.append(f"G4 Scope: {trail[-1].reason}")
            return ConstraintResult(
                allowed=False,
                action="block",
                rule_fired=g4_rule,
                reasons=reasons,
                guardrail_trail=trail,
            )

        # ── G5: Delegation budget (sub-agents only) ───────────────────────────
        if delegation_budget_remaining is not None:
            g5_passed = amount <= delegation_budget_remaining
            trail.append(
                GuardrailOutcome(
                    name="G5_delegation",
                    passed=g5_passed,
                    rule_fired="G5_budget_exceeded" if not g5_passed else None,
                    reason=f"Amount {amount} exceeds delegation budget {delegation_budget_remaining}"
                    if not g5_passed
                    else None,
                )
            )
            if not g5_passed:
                reasons.append(f"G5 Delegation: {trail[-1].reason}")
                return ConstraintResult(
                    allowed=False,
                    action="block",
                    rule_fired="G5_budget_exceeded",
                    reasons=reasons,
                    guardrail_trail=trail,
                )
        else:
            trail.append(
                GuardrailOutcome(
                    name="G5_delegation", passed=True, reason="not applicable"
                )
            )

        # ── G6: Service host allowlist ────────────────────────────────────────
        if allowed_service_hosts and service_host:
            g6_passed = service_host in allowed_service_hosts
            trail.append(
                GuardrailOutcome(
                    name="G6_service_host",
                    passed=g6_passed,
                    rule_fired="G6_host_not_allowed" if not g6_passed else None,
                    reason=f"Host '{service_host}' not in allowlist"
                    if not g6_passed
                    else None,
                )
            )
            if not g6_passed:
                reasons.append(f"G6 Service host: '{service_host}' not allowed")
                return ConstraintResult(
                    allowed=False,
                    action="block",
                    rule_fired="G6_host_not_allowed",
                    reasons=reasons,
                    guardrail_trail=trail,
                )
        else:
            trail.append(
                GuardrailOutcome(
                    name="G6_service_host", passed=True, reason="no host restriction"
                )
            )

        # ── G7: Agent amount cap (defense-in-depth) ───────────────────────────
        max_usd = Decimal(str(settings.agent_max_amount_usd))
        g7_passed = amount <= max_usd
        trail.append(
            GuardrailOutcome(
                name="G7_amount_cap",
                passed=g7_passed,
                rule_fired="G7_exceeds_agent_max" if not g7_passed else None,
                reason=f"Amount {amount} exceeds agent max {max_usd}"
                if not g7_passed
                else None,
            )
        )
        if not g7_passed:
            reasons.append(f"G7 Cap: amount {amount} exceeds agent ceiling {max_usd}")
            return ConstraintResult(
                allowed=False,
                action="block",
                rule_fired="G7_exceeds_agent_max",
                reasons=reasons,
                guardrail_trail=trail,
            )

        return ConstraintResult(
            allowed=True,
            action="allow",
            rule_fired=None,
            reasons=[],
            guardrail_trail=trail,
        )


def _context_to_scope(context_kind: ContextKind) -> AgentScope:
    """Map a context kind to the AgentScope the agent must hold."""
    _MAP = {
        "payment": AgentScope.payment,
        "loan_underwrite": AgentScope.compliance,
        "insurance_payout": AgentScope.compliance,
        "delegation_fund": AgentScope.delegation,
    }
    return _MAP.get(context_kind, AgentScope.payment)
