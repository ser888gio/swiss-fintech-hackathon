from app.policy import engine


def test_small_clean_payment_auto_settles():
    decision = engine.evaluate(amount_usd=500, aml_score=12)
    assert decision.requires_approval is False
    assert decision.rule_fired is None
    assert decision.reasons == []


def test_large_payment_requires_approval():
    decision = engine.evaluate(amount_usd=50_000, aml_score=12)
    assert decision.requires_approval is True
    assert decision.rule_fired == "amount_threshold"


def test_flagged_payment_requires_approval():
    decision = engine.evaluate(amount_usd=500, aml_score=85)
    assert decision.requires_approval is True
    assert decision.rule_fired == "compliance_score"


def test_threshold_is_exclusive():
    at_threshold = engine.evaluate(amount_usd=engine.THRESHOLD_USD, aml_score=0)
    over_threshold = engine.evaluate(amount_usd=engine.THRESHOLD_USD + 1, aml_score=0)
    assert at_threshold.requires_approval is False
    assert over_threshold.requires_approval is True


def test_both_rules_collect_both_reasons():
    decision = engine.evaluate(amount_usd=50_000, aml_score=85)
    assert decision.requires_approval is True
    assert len(decision.reasons) == 2
