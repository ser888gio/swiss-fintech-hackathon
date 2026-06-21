"""Pure deterministic policy for risk-triggered transaction insurance."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal


@dataclass(frozen=True)
class CoverRule:
    mode: str
    amount_threshold_usd: Decimal | None
    insure_new_counterparty: bool
    insure_unverified_counterparty: bool
    package: str | None


@dataclass(frozen=True)
class CoverDecision:
    required: bool
    required_by: str | None
    rule_fired: str | None
    package: str | None


def evaluate_cover(
    *,
    rule: CoverRule,
    amount_usd: Decimal,
    counterparty_cover_required: bool,
    counterparty_threshold_usd: Decimal | None,
    counterparty_is_new: bool,
    counterparty_verified: bool,
) -> CoverDecision:
    """Apply the operator-owned cover rule in a fixed, first-match order."""
    if rule.mode == "off":
        return CoverDecision(False, None, "agent_opt_out", None)
    if counterparty_cover_required and (
        counterparty_threshold_usd is None or amount_usd >= counterparty_threshold_usd
    ):
        return CoverDecision(True, "counterparty", "counterparty_mandate", rule.package)
    if (counterparty_is_new and rule.insure_new_counterparty) or (
        not counterparty_verified and rule.insure_unverified_counterparty
    ):
        return CoverDecision(True, "risk", "counterparty_risk", rule.package)
    if rule.amount_threshold_usd is not None and amount_usd >= rule.amount_threshold_usd:
        return CoverDecision(True, "policy", "amount_threshold", rule.package)
    return CoverDecision(False, None, None, None)


def resolve_cover_rule(settings, agent_override) -> CoverRule:
    """Merge global settings with an optional per-agent override."""
    threshold = getattr(settings, "insurance_cover_required_above_usd", None)
    base = CoverRule(
        mode="on",
        amount_threshold_usd=Decimal(str(threshold)) if threshold is not None else None,
        insure_new_counterparty=getattr(settings, "insurance_auto_new_cpty", True),
        insure_unverified_counterparty=getattr(settings, "insurance_auto_unverified_cpty", True),
        package=getattr(settings, "insurance_default_package", "Essential"),
    )
    if agent_override is None or agent_override.mode == "inherit":
        return base
    if agent_override.mode == "off":
        return replace(base, mode="off")
    overrides = {}
    if agent_override.amount_threshold_usd is not None:
        overrides["amount_threshold_usd"] = Decimal(str(agent_override.amount_threshold_usd))
    if agent_override.insure_new_counterparty is not None:
        overrides["insure_new_counterparty"] = agent_override.insure_new_counterparty
    if agent_override.insure_unverified_counterparty is not None:
        overrides["insure_unverified_counterparty"] = agent_override.insure_unverified_counterparty
    if agent_override.package is not None:
        overrides["package"] = agent_override.package
    return replace(base, **overrides)
