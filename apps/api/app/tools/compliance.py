"""Compliance tool: check_compliance.

Deterministic mock screen. Production swaps this for a real provider
(Chainalysis/Elliptic-style API); the contract — an AML score, a sanctions flag,
flags, and a plain-language explanation — stays the same.
"""

from __future__ import annotations

from ..schemas import ComplianceResult, PaymentIntent

# Demo sanctions list. Replace with a real screening provider for production.
SANCTIONED_ACCOUNTS = {"rSANCTIONED000000000000000000000000", "ACME-SHELL-CO"}
SANCTIONED_NAMES = {"acme shell co", "blocked industries ltd"}
HIGH_RISK_COUNTRIES = {"IR", "KP", "RU", "SY"}
HIGH_RISK_KEYWORDS = ("crypto-mixer", "shell", "unverified")


def check_compliance(intent: PaymentIntent) -> ComplianceResult:
    flags: list[str] = []

    sanctioned = (
        intent.to in SANCTIONED_ACCOUNTS
        or intent.receiver_name.strip().lower() in SANCTIONED_NAMES
    )
    if sanctioned:
        flags.append("counterparty on sanctions list")

    if intent.receiver_country.upper() in HIGH_RISK_COUNTRIES:
        flags.append(f"receiver country is high risk ({intent.receiver_country.upper()})")

    reference = f"{intent.reference} {intent.purpose}".lower()
    for keyword in HIGH_RISK_KEYWORDS:
        if keyword in reference:
            flags.append(f"reference mentions '{keyword}'")

    score = _score(sanctioned, len(flags), intent.amount)
    explanation = _explain(score, flags)
    return ComplianceResult(
        aml_score=score,
        sanctioned=sanctioned,
        flags=flags,
        explanation=explanation,
    )


def _score(sanctioned: bool, flag_count: int, amount: float) -> int:
    if sanctioned:
        return 100
    score = 10 + flag_count * 25
    if amount >= 25_000:
        score += 10
    return min(score, 95)


def _explain(score: int, flags: list[str]) -> str:
    if not flags:
        return f"Clean screen. AML score {score}/100, no flags raised."
    joined = "; ".join(flags)
    return f"AML score {score}/100. Flags: {joined}."
