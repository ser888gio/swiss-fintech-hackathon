from types import SimpleNamespace

from app.schemas import CredentialStatus, PaymentIntent
from app.tools import compliance, credentials


def _settings(**overrides):
    data = {
        "credential_kyc_enabled": True,
        "credential_type": "KYC",
        "credential_issuer_address": "rISSUER",
        "credential_issuer_seed": "",
        "token_issuer_address": "rISSUER",
        "use_mock_xrpl": True,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _intent(**overrides) -> PaymentIntent:
    data = {
        "from": "rSender",
        "to": "rReceiver",
        "senderName": "Alice AG",
        "senderCountry": "CH",
        "receiverName": "Bob LLC",
        "receiverCountry": "US",
        "receiverEntityType": "company",
        "purpose": "supplier_payment",
        "amount": 500.0,
        "currency": "USD",
        "reference": "INV-001",
    }
    data.update(overrides)
    return PaymentIntent(**data)


async def test_disabled_layer_reports_not_checked(monkeypatch):
    monkeypatch.setattr(credentials, "get_settings", lambda: _settings(credential_kyc_enabled=False))

    status = await credentials.verify_kyc("rReceiver")

    assert status.checked is False
    assert status.verified is False


async def test_mock_verifies_known_subject(monkeypatch):
    monkeypatch.setattr(credentials, "get_settings", lambda: _settings())

    status = await credentials.verify_kyc("rReceiver")

    assert status.checked is True
    assert status.verified is True
    assert status.credential_type == "KYC"
    assert status.issuer == "rISSUER"


async def test_mock_flags_unverified_subject(monkeypatch):
    monkeypatch.setattr(credentials, "get_settings", lambda: _settings())
    subject = next(iter(credentials.MOCK_UNVERIFIED_SUBJECTS))

    status = await credentials.verify_kyc(subject)

    assert status.checked is True
    assert status.verified is False


async def test_mock_issue_credential_returns_hash(monkeypatch):
    monkeypatch.setattr(credentials, "get_settings", lambda: _settings())

    result = await credentials.issue_credential("rReceiver", uri="https://kyc.example/vc/123")

    assert len(result["txHash"]) == 64
    assert result["accepted"] is False
    assert result["explorerUrl"] is None


def _compliance_settings(**overrides):
    data = {
        "opensanctions_api_key": "",
        "opensanctions_base_url": "https://api.opensanctions.org",
        "opensanctions_dataset": "sanctions",
        "opensanctions_match_threshold": 0.85,
        "public_intel_enabled": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _unverified() -> CredentialStatus:
    return CredentialStatus(
        checked=True, verified=False, subject="rReceiver", issuer="rISSUER",
        credential_type="KYC", reason="mock: no KYC credential on file",
    )


def _verified() -> CredentialStatus:
    return CredentialStatus(
        checked=True, verified=True, subject="rReceiver", issuer="rISSUER",
        credential_type="KYC", reason="mock: accepted KYC credential present",
    )


def test_missing_credential_raises_risk_to_escalation_floor(monkeypatch):
    monkeypatch.setattr(compliance, "get_settings", lambda: _compliance_settings())
    monkeypatch.setattr(compliance.public_intel, "assess_public_intel", lambda intent: _public())

    result = compliance.check_compliance(_intent(), credential=_unverified())

    assert result.sanctioned is False
    # Floored above the default policy flag score (60) so the payment escalates.
    assert result.aml_score == compliance.KYC_MISSING_SCORE
    assert any("KYC credential" in flag for flag in result.flags)
    assert result.credential is not None and result.credential.verified is False


def test_valid_credential_keeps_clean_screen(monkeypatch):
    monkeypatch.setattr(compliance, "get_settings", lambda: _compliance_settings())
    monkeypatch.setattr(compliance.public_intel, "assess_public_intel", lambda intent: _public())

    result = compliance.check_compliance(_intent(), credential=_verified())

    assert result.aml_score == 10
    assert not any("KYC credential" in flag for flag in result.flags)
    assert result.credential is not None and result.credential.verified is True


def _public(score=0, flags=None):
    from app.schemas import PublicIntelResult

    return PublicIntelResult(
        score=score, confidence="test", flags=flags or [], sources=[],
        summary="Public intelligence test scaffold.",
    )
