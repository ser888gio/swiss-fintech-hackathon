"""Credential Issuing Agent.

A second agent alongside the treasury payment orchestrator. It runs the
issue → accept → verify lifecycle for XRPL Credentials (XLS-70) and narrates
each step into a per-record log — the same "the AI explains, code decides"
shape as the payment workflow.

The one rule still holds: the agent NEVER decides whether a subject is allowed a
credential. That gate is a deterministic sanctions screen
(`compliance.is_sanctioned`). A misbehaving model can, at worst, produce bad
narration — never issue a credential to a sanctioned party.

Mock mode (settings.use_mock_xrpl) runs the whole lifecycle offline with
deterministic fake tx hashes. Real mode submits CredentialCreate / CredentialAccept
to the configured network so the flow can be proven on Testnet.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .. import store
from ..config import get_settings
from ..schemas import (
    CredentialIssueRequest,
    CredentialLogEntry,
    CredentialRecord,
    CredentialRecordStatus,
)
from ..tools import compliance, credentials


async def issue(request: CredentialIssueRequest) -> CredentialRecord:
    """Run the issuing workflow: screen the subject, then CredentialCreate."""
    settings = get_settings()
    record_id = str(uuid.uuid4())
    now = _now()
    credential_type = request.credential_type or settings.credential_type
    issuer = settings.credential_issuer_address or settings.token_issuer_address

    record = CredentialRecord(
        id=record_id,
        subject=request.subject,
        subject_name=request.subject_name,
        issuer=issuer,
        credential_type=credential_type,
        uri=request.uri,
        expiration=request.expiration,
        status=CredentialRecordStatus.issued,
        created_at=now,
        updated_at=now,
    )
    store.save_credential(record)
    _log(
        record_id,
        f"Credential request received: type '{credential_type}' for subject "
        f"{request.subject_name or request.subject}.",
    )

    # Deterministic gate — code decides, never the LLM.
    if compliance.is_sanctioned(request.subject, request.subject_name):
        record.status = CredentialRecordStatus.refused
        record.refused_reason = "subject matches sanctions screen"
        record.audit_explanation = (
            "Issuance refused by deterministic sanctions screen; no credential created."
        )
        _log(record_id, "Refused: subject matches sanctions screen. No credential issued.")
        return _touch(record)

    _log(record_id, "Sanctions screen clear. Submitting CredentialCreate.")
    try:
        result = await credentials.issue_credential(
            request.subject,
            uri=request.uri,
            expiration=request.expiration,
            credential_type=credential_type,
        )
    except Exception as exc:  # network/config errors must not crash the agent
        # tecDUPLICATE means the credential already exists on-ledger — re-issuing
        # is a no-op, not a failure. Reflect its real state so the flow is
        # idempotent (a subject can be "issued KYC" again without an error).
        if "tecDUPLICATE" in str(exc):
            _log(record_id, "Credential already exists on-ledger (tecDUPLICATE); checking its status.")
            status = await credentials.verify_kyc(request.subject)
            record.verified = status.verified
            record.accepted = status.verified
            record.status = (
                CredentialRecordStatus.verified if status.verified else CredentialRecordStatus.issued
            )
            record.audit_explanation = (
                f"Credential '{credential_type}' already present for {request.subject}; "
                + ("verified on-ledger." if status.verified else "awaiting subject acceptance.")
            )
            _log(record_id, f"Reused existing credential: {status.reason}.")
            if not status.verified and request.auto_accept:
                try:
                    return await accept(record_id)
                except (NotImplementedError, InvalidCredentialState) as accept_exc:
                    _log(record_id, f"Auto-accept skipped: {accept_exc}.")
            return _touch(record)
        record.status = CredentialRecordStatus.failed
        record.refused_reason = f"CredentialCreate failed: {exc}"
        _log(record_id, f"Failed to submit CredentialCreate: {exc}.")
        return _touch(record)

    record.tx_hash = result.get("txHash")
    record.explorer_url = result.get("explorerUrl")
    record.issuer = result.get("issuer") or record.issuer
    record.audit_explanation = (
        f"Issued credential '{credential_type}' to {request.subject}. "
        "Awaiting subject CredentialAccept before it is usable."
    )
    short = (record.tx_hash or "")[:12]
    _log(record_id, f"CredentialCreate submitted. Tx {short}… Awaiting subject acceptance.")
    _touch(record)

    if request.auto_accept:
        try:
            return await accept(record_id)
        except (NotImplementedError, InvalidCredentialState) as exc:
            # Issuance succeeded; auto-accept is best-effort (e.g. no subject seed
            # on a real network). Leave the record 'issued' for a manual accept.
            _log(record_id, f"Auto-accept skipped: {exc}.")
            return _touch(record)

    return record


async def accept(record_id: str, subject_seed: str | None = None) -> CredentialRecord:
    """Subject-side CredentialAccept for a record the agent issued."""
    record = store.get_credential(record_id)
    if record is None:
        raise CredentialNotFound(record_id)
    if record.status not in {CredentialRecordStatus.issued, CredentialRecordStatus.accepted}:
        raise InvalidCredentialState(record.status)

    result = await credentials.accept_credential(
        record.subject,
        issuer=record.issuer,
        credential_type=record.credential_type,
        subject_seed=subject_seed,
    )
    record.accepted = True
    record.status = CredentialRecordStatus.accepted
    record.accept_tx_hash = result.get("txHash")
    record.accept_explorer_url = result.get("explorerUrl")
    short = (record.accept_tx_hash or "")[:12]
    _log(record_id, f"Subject accepted the credential. Tx {short}… Credential is now usable.")
    return _touch(record)


async def verify(record_id: str) -> CredentialRecord:
    """Re-check the credential on-ledger and record whether it is valid."""
    record = store.get_credential(record_id)
    if record is None:
        raise CredentialNotFound(record_id)

    status = await credentials.verify_kyc(record.subject)
    record.verified = status.verified
    if status.verified:
        record.status = CredentialRecordStatus.verified
        record.accepted = True
    _log(record_id, f"Verification: {status.reason}.")
    return _touch(record)


class CredentialNotFound(Exception):
    pass


class InvalidCredentialState(Exception):
    pass


def _log(record_id: str, message: str) -> None:
    store.append_credential_log(
        CredentialLogEntry(record_id=record_id, timestamp=_now(), message=message)
    )


def _touch(record: CredentialRecord) -> CredentialRecord:
    record.updated_at = _now()
    return store.save_credential(record)


def _now() -> datetime:
    return datetime.now(timezone.utc)
