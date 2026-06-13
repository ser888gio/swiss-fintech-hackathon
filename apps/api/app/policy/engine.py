"""The policy boundary. Deterministic, code-enforced, unit-tested.

This is the one place that decides auto-settle vs. escalate. The LLM never
reaches past it. A change here changes when human approval is required, so it is
covered by tests in apps/api/tests/test_policy.py.
"""

from __future__ import annotations

from ..schemas import PolicyDecision

THRESHOLD_USD = 10_000.0
COMPLIANCE_FLAG_SCORE = 60


def evaluate(
    amount_usd: float,
    aml_score: int,
    threshold_usd: float = THRESHOLD_USD,
    flag_score: int = COMPLIANCE_FLAG_SCORE,
) -> PolicyDecision:
    """Decide whether a payment needs a human hardware approval.

    Pure function, no I/O. Approval is required if the amount exceeds the
    working threshold or the AML score exceeds the compliance flag score.
    """
    reasons: list[str] = []
    if amount_usd > threshold_usd:
        reasons.append(f"amount ${amount_usd:,.0f} exceeds threshold ${threshold_usd:,.0f}")
    if aml_score > flag_score:
        reasons.append(f"AML score {aml_score} exceeds flag score {flag_score}")

    if not reasons:
        return PolicyDecision(requires_approval=False, rule_fired=None, reasons=[])

    rule_fired = "amount_threshold" if amount_usd > threshold_usd else "compliance_score"
    return PolicyDecision(requires_approval=True, rule_fired=rule_fired, reasons=reasons)
