from types import SimpleNamespace

from app import store
from app.agents import credential_agent
from app.schemas import CredentialIssueRequest, CredentialRecordStatus
from app.tools import credentials


def _settings(**overrides):
    data = {
        "credential_kyc_enabled": True,
        "credential_type": "KYC",
        "credential_issuer_address": "rISSUER",
        "credential_issuer_seed": "",
        "credential_subject_seed": "",
        "token_issuer_address": "rISSUER",
        "use_mock_xrpl": True,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _patch(monkeypatch, **overrides):
    settings = _settings(**overrides)
    monkeypatch.setattr(credential_agent, "get_settings", lambda: settings)
    monkeypatch.setattr(credentials, "get_settings", lambda: settings)


def _request(**overrides) -> CredentialIssueRequest:
    data = {"subject": "rReceiver", "subjectName": "Bob LLC"}
    data.update(overrides)
    return CredentialIssueRequest(**data)


async def test_issue_creates_record_with_tx_and_log(monkeypatch):
    _patch(monkeypatch)

    record = await credential_agent.issue(_request())

    assert record.status is CredentialRecordStatus.issued
    assert record.accepted is False
    assert len(record.tx_hash) == 64
    assert record.issuer == "rISSUER"
    assert record.credential_type == "KYC"
    logs = store.credential_logs_for(record.id)
    assert any("CredentialCreate submitted" in entry.message for entry in logs)


async def test_custom_credential_type_is_used(monkeypatch):
    _patch(monkeypatch)

    record = await credential_agent.issue(_request(credentialType="ACCREDITED_INVESTOR"))

    assert record.credential_type == "ACCREDITED_INVESTOR"


async def test_sanctioned_subject_is_refused_without_issuing(monkeypatch):
    _patch(monkeypatch)

    record = await credential_agent.issue(_request(subjectName="ACME Shell Co"))

    assert record.status is CredentialRecordStatus.refused
    assert record.tx_hash is None
    assert "sanctions" in (record.refused_reason or "")
    logs = store.credential_logs_for(record.id)
    assert any("Refused" in entry.message for entry in logs)


async def test_accept_transitions_to_accepted(monkeypatch):
    _patch(monkeypatch)
    record = await credential_agent.issue(_request())

    accepted = await credential_agent.accept(record.id)

    assert accepted.status is CredentialRecordStatus.accepted
    assert accepted.accepted is True
    assert len(accepted.accept_tx_hash) == 64


async def test_verify_marks_record_verified(monkeypatch):
    _patch(monkeypatch)
    record = await credential_agent.issue(_request())

    verified = await credential_agent.verify(record.id)

    assert verified.verified is True
    assert verified.status is CredentialRecordStatus.verified


async def test_auto_accept_flips_unverified_subject_to_verified(monkeypatch):
    _patch(monkeypatch)
    credentials.reset_mock_state()
    subject = next(iter(credentials.MOCK_UNVERIFIED_SUBJECTS))

    before = await credentials.verify_kyc(subject)
    assert before.verified is False

    record = await credential_agent.issue(_request(subject=subject, autoAccept=True))
    assert record.status is CredentialRecordStatus.accepted
    assert record.accepted is True

    after = await credentials.verify_kyc(subject)
    assert after.verified is True
    credentials.reset_mock_state()


async def test_accept_unknown_record_raises(monkeypatch):
    _patch(monkeypatch)

    try:
        await credential_agent.accept("does-not-exist")
    except credential_agent.CredentialNotFound:
        return
    raise AssertionError("expected CredentialNotFound")
