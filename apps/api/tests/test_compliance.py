from types import SimpleNamespace

from app.schemas import PaymentIntent, PublicIntelResult
from app.tools import compliance


def _intent(**overrides) -> PaymentIntent:
    data = {
        "from": "rSender",
        "to": "rReceiver",
        "senderName": "Alice AG",
        "senderCountry": "CH",
        "receiverName": "Bob Smith",
        "receiverCountry": "GB",
        "receiverEntityType": "individual",
        "purpose": "supplier_payment",
        "amount": 500.0,
        "currency": "USD",
        "reference": "INV-001",
    }
    data.update(overrides)
    return PaymentIntent(**data)


def _settings(**overrides):
    data = {
        "opensanctions_api_key": "",
        "opensanctions_base_url": "https://api.opensanctions.org",
        "opensanctions_dataset": "sanctions",
        "opensanctions_match_threshold": 0.85,
        "sanctions_blocked_countries": "",
        "geopolitical_review_countries": "",
        "geopolitical_review_score": 65,
        "sanctions_unavailable_review_score": 65,
        "public_intel_enabled": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _public(score=0, flags=None):
    return PublicIntelResult(
        score=score,
        confidence="test",
        flags=flags or [],
        sources=[],
        summary="Public intelligence test scaffold.",
    )


def test_opensanctions_request_uses_person_schema():
    request = compliance.build_opensanctions_request(_intent())

    query = request["queries"]["receiver"]
    assert query["schema"] == "Person"
    assert query["properties"] == {"name": ["Bob Smith"], "country": ["GB"]}


def test_opensanctions_request_uses_company_schema():
    request = compliance.build_opensanctions_request(
        _intent(receiverName="Acme AG", receiverEntityType="company")
    )

    query = request["queries"]["receiver"]
    assert query["schema"] == "Company"
    assert query["properties"] == {"name": ["Acme AG"], "country": ["GB"]}


def test_high_confidence_opensanctions_match_blocks(monkeypatch):
    monkeypatch.setattr(
        compliance,
        "get_settings",
        lambda: _settings(opensanctions_api_key="test-key"),
    )
    monkeypatch.setattr(compliance.public_intel, "assess_public_intel", lambda intent: _public())
    monkeypatch.setattr(
        compliance.httpx,
        "Client",
        _client_for(
            {
                "responses": {
                    "receiver": {
                        "results": [
                            {
                                "id": "NK-123",
                                "caption": "Blocked Person",
                                "schema": "Person",
                                "score": 0.91,
                                "datasets": ["us_ofac_sdn"],
                            }
                        ]
                    }
                }
            }
        ),
    )

    result = compliance.check_compliance(_intent())

    assert result.sanctioned is True
    assert result.aml_score == 100
    assert result.sanctions_matches[0].id == "NK-123"


def test_low_confidence_opensanctions_match_does_not_block(monkeypatch):
    monkeypatch.setattr(
        compliance,
        "get_settings",
        lambda: _settings(opensanctions_api_key="test-key"),
    )
    monkeypatch.setattr(compliance.public_intel, "assess_public_intel", lambda intent: _public())
    monkeypatch.setattr(
        compliance.httpx,
        "Client",
        _client_for(
            {
                "responses": {
                    "receiver": {
                        "results": [
                            {
                                "id": "NK-456",
                                "caption": "Weak Candidate",
                                "schema": "Person",
                                "score": 0.42,
                                "datasets": ["us_ofac_sdn"],
                            }
                        ]
                    }
                }
            }
        ),
    )

    result = compliance.check_compliance(_intent())

    assert result.sanctioned is False
    assert result.aml_score == 10
    assert result.sanctions_matches[0].id == "NK-456"


def test_missing_api_key_uses_demo_sanctions_fallback(monkeypatch):
    monkeypatch.setattr(compliance, "get_settings", lambda: _settings())
    monkeypatch.setattr(compliance.public_intel, "assess_public_intel", lambda intent: _public())

    result = compliance.check_compliance(_intent(receiverName="ACME Shell Co"))

    assert result.sanctioned is True
    assert result.aml_score == 100
    assert "counterparty on sanctions list" in result.flags


def test_osint_scaffold_does_not_alter_clean_payment(monkeypatch):
    monkeypatch.setattr(compliance, "get_settings", lambda: _settings())
    monkeypatch.setattr(compliance.public_intel, "assess_public_intel", lambda intent: _public())

    result = compliance.check_compliance(_intent())

    assert result.sanctioned is False
    assert result.aml_score == 10
    assert result.public_intel is not None
    assert result.public_intel.score == 0


def test_public_intel_score_can_raise_aml_but_not_sanction(monkeypatch):
    monkeypatch.setattr(compliance, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        compliance.public_intel,
        "assess_public_intel",
        lambda intent: _public(score=72, flags=["adverse public intelligence signal"]),
    )

    result = compliance.check_compliance(_intent())

    assert result.sanctioned is False
    assert result.aml_score == 72
    assert "adverse public intelligence signal" in result.flags


def test_configured_country_sanctions_policy_hard_blocks(monkeypatch):
    monkeypatch.setattr(
        compliance,
        "get_settings",
        lambda: _settings(sanctions_blocked_countries="XZ,YY"),
    )
    monkeypatch.setattr(compliance.public_intel, "assess_public_intel", lambda intent: _public())

    result = compliance.check_compliance(_intent(receiverCountry="xz"))

    assert result.sanctioned is True
    assert result.aml_score == 100
    assert result.sanctions_basis == ["country sanctions / geopolitical policy"]
    assert result.geopolitical_risk is not None
    assert result.geopolitical_risk.blocked is True


def test_geopolitical_review_country_forces_hardware_review_score(monkeypatch):
    monkeypatch.setattr(
        compliance,
        "get_settings",
        lambda: _settings(geopolitical_review_countries="XZ"),
    )
    monkeypatch.setattr(compliance.public_intel, "assess_public_intel", lambda intent: _public())

    result = compliance.check_compliance(_intent(receiverCountry="XZ"))

    assert result.sanctioned is False
    assert result.aml_score == 65
    assert result.geopolitical_risk is not None
    assert result.geopolitical_risk.requires_review is True


def test_opensanctions_outage_forces_review_not_false_clean(monkeypatch):
    monkeypatch.setattr(
        compliance,
        "get_settings",
        lambda: _settings(opensanctions_api_key="test-key"),
    )
    monkeypatch.setattr(compliance.public_intel, "assess_public_intel", lambda intent: _public())

    class BrokenClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            raise compliance.httpx.ConnectError("offline")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(compliance.httpx, "Client", BrokenClient)

    result = compliance.check_compliance(_intent())

    assert result.sanctioned is False
    assert result.aml_score == 65
    assert "OpenSanctions unavailable; used local demo sanctions fallback" in result.flags


def test_curated_blocked_country_hard_blocks_via_check_compliance(monkeypatch):
    monkeypatch.setattr(compliance, "get_settings", lambda: _settings())
    monkeypatch.setattr(compliance.public_intel, "assess_public_intel", lambda intent: _public())

    result = compliance.check_compliance(_intent(receiverCountry="IR"))

    assert result.sanctioned is True
    assert result.aml_score == 100
    assert "country sanctions / geopolitical policy" in result.sanctions_basis
    assert result.geopolitical_risk is not None
    assert result.geopolitical_risk.blocked is True
    assert "FATF" in result.explanation or "Iran" in result.explanation or "Geopolitical" in result.explanation


def test_curated_review_country_raises_aml_score(monkeypatch):
    monkeypatch.setattr(compliance, "get_settings", lambda: _settings())
    monkeypatch.setattr(compliance.public_intel, "assess_public_intel", lambda intent: _public())

    result = compliance.check_compliance(_intent(receiverCountry="PK"))

    assert result.sanctioned is False
    assert result.aml_score == 65
    assert result.geopolitical_risk is not None
    assert result.geopolitical_risk.requires_review is True
    assert result.geopolitical_risk.summary != ""
    assert "Geopolitical" in result.explanation


def _client_for(payload):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json):
            assert url == "https://api.opensanctions.org/match/sanctions"
            assert "queries" in json
            return FakeResponse()

    return FakeClient
