from types import SimpleNamespace

from app.schemas import PaymentIntent
from app.tools import country_risk


def _intent(receiver_country: str) -> PaymentIntent:
    return PaymentIntent(**{
        "from": "rSender",
        "to": "rReceiver",
        "senderName": "Alice AG",
        "senderCountry": "CH",
        "receiverName": "Bob Corp",
        "receiverCountry": receiver_country,
        "receiverEntityType": "company",
        "purpose": "supplier_payment",
        "amount": 1000.0,
        "currency": "USD",
        "reference": "INV-001",
    })


def _settings(**overrides):
    data = {
        "sanctions_blocked_countries": "",
        "geopolitical_review_countries": "",
        "geopolitical_review_score": 65,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_iran_is_hard_blocked():
    result = country_risk.assess_country_risk(_intent("IR"), _settings())
    assert result.blocked is True
    assert result.score == 100
    assert result.risk_level == "blocked"
    assert "FATF call for action" in result.sources
    assert "FATF" in result.summary or "Iran" in result.summary
    assert result.summary != ""


def test_north_korea_is_hard_blocked():
    result = country_risk.assess_country_risk(_intent("KP"), _settings())
    assert result.blocked is True
    assert result.score == 100


def test_myanmar_is_hard_blocked():
    result = country_risk.assess_country_risk(_intent("MM"), _settings())
    assert result.blocked is True
    assert result.score == 100


def test_greylist_country_requires_review():
    result = country_risk.assess_country_risk(_intent("PK"), _settings())
    assert result.blocked is False
    assert result.requires_review is True
    assert result.score == 65
    assert result.risk_level == "high"
    assert "FATF" in result.sources[0]
    assert result.summary != ""


def test_eu_high_risk_country_requires_review():
    result = country_risk.assess_country_risk(_intent("AF"), _settings())
    assert result.blocked is False
    assert result.requires_review is True
    assert result.score == 65


def test_russia_requires_review():
    result = country_risk.assess_country_risk(_intent("RU"), _settings())
    assert result.blocked is False
    assert result.requires_review is True


def test_clean_country_is_standard():
    result = country_risk.assess_country_risk(_intent("GB"), _settings())
    assert result.blocked is False
    assert result.requires_review is False
    assert result.risk_level == "standard"
    assert result.score == 0
    assert result.summary == ""


def test_switzerland_is_standard():
    result = country_risk.assess_country_risk(_intent("CH"), _settings())
    assert result.risk_level == "standard"
    assert result.score == 0


def test_env_blocked_country_unions_with_curated():
    result = country_risk.assess_country_risk(_intent("XZ"), _settings(sanctions_blocked_countries="XZ"))
    assert result.blocked is True
    assert result.score == 100


def test_env_review_country_unions_with_curated():
    result = country_risk.assess_country_risk(_intent("XZ"), _settings(geopolitical_review_countries="XZ"))
    assert result.requires_review is True
    assert result.score == 65


def test_env_blocked_does_not_override_curated_blocked():
    # IR is already blocked; env block list on a different code still works
    result = country_risk.assess_country_risk(_intent("IR"), _settings(sanctions_blocked_countries="DE"))
    assert result.blocked is True


def test_geopolitical_review_score_from_settings():
    result = country_risk.assess_country_risk(_intent("PK"), _settings(geopolitical_review_score=80))
    assert result.score == 80


def test_review_supersedes_env_review_for_curated_blocked():
    # A curated blocked country cannot be downgraded to review via env
    result = country_risk.assess_country_risk(_intent("IR"), _settings(geopolitical_review_countries="IR"))
    assert result.blocked is True
    assert result.requires_review is False
