"""Audit tool.

LLM-assisted: turns a payment's decision trail into a plain-language explanation
stored alongside the record. If no OpenAI key is configured it falls back to a
deterministic template so the audit trail is never empty.

ARS extension: after writing the explanation, appends an Ed25519-signed AuditEvent
to the immutable log (tools/audit_log.py) covering the guardrail trail, so every
decision — including guardrail blocks — is hash-chained and tamper-evident.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from ..config import get_settings
from ..schemas import ComplianceResult, GuardrailResult, PolicyDecision, RouteQuote
from . import audit_log

_SYSTEM_PROMPT = (
    "You write one short, plain-language paragraph explaining a corporate payment "
    "decision for an audit log. State the route, the compliance result, the "
    "policy outcome, and any guardrail that blocked or escalated the payment. "
    "Do not invent facts beyond the data given."
)


async def write_audit(
    route: RouteQuote,
    compliance: ComplianceResult,
    decision: PolicyDecision,
    guardrail_trail: list[GuardrailResult] | None = None,
    context_kind: str = "payment",
    payment_id: str | None = None,
) -> str:
    settings = get_settings()

    blocked_guardrail = None
    if guardrail_trail:
        blocked_guardrail = next((g for g in guardrail_trail if not g.passed), None)

    explanation = await _generate_explanation(
        route, compliance, decision, blocked_guardrail, settings
    )

    # Append an Ed25519-signed AuditEvent so this decision is in the immutable log.
    trail_dicts = [g.model_dump() for g in guardrail_trail] if guardrail_trail else []
    audit_log.append(
        event_type="payment_decision" if not blocked_guardrail else "guardrail_block",
        actor="constraint_engine",
        context_kind=context_kind,
        payload={
            "payment_id": payment_id,
            "route_summary": route.path_summary,
            "dest_amount": str(route.dest_amount),
            "aml_score": compliance.aml_score,
            "sanctioned": compliance.sanctioned,
            "requires_approval": decision.requires_approval,
            "blocked": decision.blocked,
            "rule_fired": decision.rule_fired,
            "guardrail_trail": trail_dicts,
            "blocked_guardrail": blocked_guardrail.model_dump() if blocked_guardrail else None,
            "explanation": explanation,
        },
    )

    return explanation


async def _generate_explanation(
    route: RouteQuote,
    compliance: ComplianceResult,
    decision: PolicyDecision,
    blocked_guardrail,
    settings,
) -> str:
    if not settings.openai_api_key:
        return _template(route, compliance, decision, blocked_guardrail)

    guardrail_note = ""
    if blocked_guardrail:
        guardrail_note = f" Guardrail {blocked_guardrail.name} blocked: {blocked_guardrail.reason}."

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    facts = (
        f"Route: {route.path_summary}, settling {route.dest_amount}. "
        f"Compliance: {compliance.explanation}. "
        f"Sanctions matches: {len(compliance.sanctions_matches)}. "
        f"Policy: requires_approval={decision.requires_approval}, "
        f"rule_fired={decision.rule_fired}.{guardrail_note}"
    )
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": facts},
        ],
    )
    return response.choices[0].message.content or _template(
        route, compliance, decision, blocked_guardrail
    )


def _template(
    route: RouteQuote,
    compliance: ComplianceResult,
    decision: PolicyDecision,
    blocked_guardrail=None,
) -> str:
    if blocked_guardrail:
        outcome = f"refused — guardrail {blocked_guardrail.name} blocked: {blocked_guardrail.reason}"
    elif decision.blocked:
        outcome = f"refused — {decision.block_reason}"
    elif decision.requires_approval:
        outcome = "escalated for hardware approval"
    else:
        outcome = "auto-settled"
    return (
        f"Routed {route.path_summary}, settling {route.dest_amount}. "
        f"{compliance.explanation} Payment {outcome}."
    )
