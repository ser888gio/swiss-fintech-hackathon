"""Audit tool.

LLM-assisted: turns a payment's decision trail into a plain-language explanation
stored alongside the record. If no OpenAI key is configured it falls back to a
deterministic template so the audit trail is never empty.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from ..config import get_settings
from ..schemas import ComplianceResult, PolicyDecision, RouteQuote

_SYSTEM_PROMPT = (
    "You write one short, plain-language paragraph explaining a corporate payment "
    "decision for an audit log. State the route, the compliance result, and the "
    "policy outcome. Do not invent facts beyond the data given."
)


async def write_audit(
    route: RouteQuote,
    compliance: ComplianceResult,
    decision: PolicyDecision,
) -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        return _template(route, compliance, decision)

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    facts = (
        f"Route: {route.path_summary}, settling {route.dest_amount}. "
        f"Compliance: {compliance.explanation}. "
        f"Sanctions matches: {len(compliance.sanctions_matches)}. "
        f"Policy: requires_approval={decision.requires_approval}, "
        f"rule_fired={decision.rule_fired}."
    )
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": facts},
        ],
    )
    return response.choices[0].message.content or _template(route, compliance, decision)


def _template(route: RouteQuote, compliance: ComplianceResult, decision: PolicyDecision) -> str:
    if decision.blocked:
        outcome = f"refused — {decision.block_reason}"
    elif decision.requires_approval:
        outcome = "escalated for hardware approval"
    else:
        outcome = "auto-settled"
    return (
        f"Routed {route.path_summary}, settling {route.dest_amount}. "
        f"{compliance.explanation} Payment {outcome}."
    )
