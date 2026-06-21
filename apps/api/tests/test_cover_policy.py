from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.insurance.cover_policy import CoverRule, evaluate_cover, resolve_cover_rule
from app.schemas import AutoInsureConfig


@pytest.mark.parametrize(
    ("rule", "amount", "mandate", "mandate_threshold", "is_new", "verified", "required", "required_by", "rule_fired"),
    [
        (CoverRule("off", Decimal("10"), True, True, "Essential"), "99999", True, None, True, False, False, None, "agent_opt_out"),
        (CoverRule("on", Decimal("1000"), False, False, "Essential"), "50", True, None, False, True, True, "counterparty", "counterparty_mandate"),
        (CoverRule("on", Decimal("1000"), True, False, "Essential"), "50", False, None, True, True, True, "risk", "counterparty_risk"),
        (CoverRule("on", Decimal("1000"), False, True, "Essential"), "50", False, None, False, False, True, "risk", "counterparty_risk"),
        (CoverRule("on", Decimal("1000"), False, False, "Essential"), "1000", False, None, False, True, True, "policy", "amount_threshold"),
        (CoverRule("on", Decimal("1000"), False, False, "Essential"), "50", False, None, False, True, False, None, None),
        (CoverRule("on", Decimal("1000"), False, False, "Essential"), "50", False, None, True, True, False, None, None),
    ],
)
def test_evaluate_cover_resolution_ladder(
    rule, amount, mandate, mandate_threshold, is_new, verified, required, required_by, rule_fired
):
    decision = evaluate_cover(
        rule=rule,
        amount_usd=Decimal(amount),
        counterparty_cover_required=mandate,
        counterparty_threshold_usd=mandate_threshold,
        counterparty_is_new=is_new,
        counterparty_verified=verified,
    )
    assert decision.required is required
    assert decision.required_by == required_by
    assert decision.rule_fired == rule_fired


def _settings():
    return SimpleNamespace(
        insurance_cover_required_above_usd=10_000,
        insurance_auto_new_cpty=True,
        insurance_auto_unverified_cpty=True,
        insurance_default_package="Essential",
    )


def test_resolve_inherit_uses_global_rule():
    rule = resolve_cover_rule(_settings(), AutoInsureConfig(mode="inherit"))
    assert rule.amount_threshold_usd == Decimal("10000")
    assert rule.insure_new_counterparty is True
    assert rule.package == "Essential"


def test_resolve_off_forces_opt_out():
    assert resolve_cover_rule(_settings(), AutoInsureConfig(mode="off")).mode == "off"


def test_resolve_on_overrides_only_explicit_fields():
    rule = resolve_cover_rule(_settings(), AutoInsureConfig(
        mode="on", amount_threshold_usd=500, insure_new_counterparty=False, package="Standard"
    ))
    assert rule.amount_threshold_usd == Decimal("500")
    assert rule.insure_new_counterparty is False
    assert rule.insure_unverified_counterparty is True
    assert rule.package == "Standard"
