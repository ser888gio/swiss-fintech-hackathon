from app.policy import engine


def test_small_clean_payment_auto_settles():
    decision = engine.evaluate(amount_usd=500, aml_score=12)
    assert decision.requires_approval is False
    assert decision.rule_fired is None
    assert decision.reasons == []
    assert decision.blocked is False


def test_large_payment_requires_approval():
    decision = engine.evaluate(amount_usd=50_000, aml_score=12)
    assert decision.requires_approval is True
    assert decision.rule_fired == "amount_threshold"
    assert decision.blocked is False


def test_flagged_payment_requires_approval():
    decision = engine.evaluate(amount_usd=500, aml_score=85)
    assert decision.requires_approval is True
    assert decision.rule_fired == "compliance_score"
    assert decision.blocked is False


def test_threshold_is_exclusive():
    at_threshold = engine.evaluate(amount_usd=engine.THRESHOLD_USD, aml_score=0)
    over_threshold = engine.evaluate(amount_usd=engine.THRESHOLD_USD + 1, aml_score=0)
    assert at_threshold.requires_approval is False
    assert over_threshold.requires_approval is True


def test_both_rules_collect_both_reasons():
    decision = engine.evaluate(amount_usd=50_000, aml_score=85)
    assert decision.requires_approval is True
    assert len(decision.reasons) == 2


def test_sanctioned_counterparty_is_blocked_not_escalated():
    decision = engine.evaluate(amount_usd=500, aml_score=100, sanctioned=True)
    assert decision.blocked is True
    assert decision.requires_approval is False
    assert decision.rule_fired == "sanctions_block"
    assert decision.block_reason == "counterparty on sanctions list"


def test_sanctioned_large_payment_is_still_blocked_not_escalated():
    # Hardware approval cannot override a sanctions block.
    decision = engine.evaluate(amount_usd=500_000, aml_score=100, sanctioned=True)
    assert decision.blocked is True
    assert decision.requires_approval is False


def test_configurable_threshold_is_honored():
    # A lower configured threshold escalates an amount the default would settle.
    decision = engine.evaluate(amount_usd=5_000, aml_score=0, threshold_usd=1_000)
    assert decision.requires_approval is True
    assert decision.rule_fired == "amount_threshold"


def test_configurable_flag_score_is_honored():
    # A lower configured flag score escalates an AML score the default would settle.
    decision = engine.evaluate(amount_usd=500, aml_score=40, flag_score=30)
    assert decision.requires_approval is True
    assert decision.rule_fired == "compliance_score"
