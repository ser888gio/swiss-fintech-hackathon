"""Credential Issuing Agent.

A second agent alongside the treasury payment orchestrator. It runs the
issue → accept → verify lifecycle for XRPL Credentials (XLS-70) and narrates
each step into a per-record log — the same "the AI explains, code decides"
shape as the payment workflow.

The one rule still holds: the agent NEVER decides whether a subject is allowed a
credential. That gate is a deterministic sanctions screen
(`compliance.is_sanctioned`). A misbehaving model can, at worst, produce bad
narration — never issue a credential to a sanctioned party.

The lifecycle submits CredentialCreate / CredentialAccept to the configured
network so the flow can be proven on Testnet.
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
from ..tools import compliance
from .kyc import tool as credentials


async def issue(request: CredentialIssueRequest) -> CredentialRecord:
    """Run the issuing workflow: screen the subject, then CredentialCreate."""
    settings = get_settings()
    record_id = str(uuid.uuid4())
    now = _now()
    credential_type = request.credential_type or settings.credential_type
    issuer = settings.credential_issuer_address or settings.token_issuer_address

    record = CredentialRecord(
        id=record_id,
        user_id=request.user_id,
        subject=request.subject,
        subject_name=request.subject_name,
        subject_country=request.subject_country,
        subject_entity_type=request.subject_entity_type,
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
        return _refuse_sanctioned(record)

    _log(record_id, "Sanctions screen clear. Submitting CredentialCreate.")
    try:
        result = await credentials.issue_credential(
            request.subject,
            uri=request.uri,
            expiration=request.expiration,
            credential_type=credential_type,
        )
    except Exception as exc:  # network/config errors must not crash the agent
        return await _handle_issue_error(record, request, credential_type, exc)

    record.tx_hash = result.get("txHash")
    record.explorer_url = result.get("explorerUrl")
    record.issuer = result.get("issuer") or record.issuer
    record.audit_explanation = (
        f"Issued credential '{credential_type}' to {request.subject}. "
        "Awaiting subject CredentialAccept before it is usable."
    )
    short = (record.tx_hash or "")[:12]
    _log(
        record_id,
        f"CredentialCreate submitted. Tx {short}… Awaiting subject acceptance.",
    )
    _touch(record)

    if request.auto_accept:
        try:
            return await accept(record_id)
        except (NotImplementedError, InvalidCredentialState, ValueError) as exc:
            # Issuance succeeded; auto-accept is best-effort (e.g. no subject seed
            # on a real network, or the configured seed controls a different
            # subject). Leave the record 'issued' for subject-side acceptance.
            _log(record_id, f"Auto-accept skipped: {exc}.")
            return _touch(record)

    return record


async def accept(record_id: str, subject_seed: str | None = None) -> CredentialRecord:
    """Subject-side CredentialAccept for a record the agent issued."""
    record = store.get_credential(record_id)
    if record is None:
        raise CredentialNotFound(record_id)
    if record.status not in {
        CredentialRecordStatus.issued,
        CredentialRecordStatus.accepted,
    }:
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
    _log(
        record_id,
        f"Subject accepted the credential. Tx {short}… Credential is now usable.",
    )
    return _touch(record)


def _refuse_sanctioned(record: CredentialRecord) -> CredentialRecord:
    record.status = CredentialRecordStatus.refused
    record.refused_reason = "subject matches sanctions screen"
    record.audit_explanation = (
        "Issuance refused by deterministic sanctions screen; no credential created."
    )
    _log(record.id, "Refused: subject matches sanctions screen. No credential issued.")
    return _touch(record)


async def _handle_issue_error(
    record: CredentialRecord,
    request: CredentialIssueRequest,
    credential_type: str,
    exc: Exception,
) -> CredentialRecord:
    message = str(exc)
    if "tecNO_TARGET" in message:
        return _fail_missing_subject(record, request.subject)
    if "tecDUPLICATE" in message:
        return await _reuse_duplicate_credential(record, request, credential_type)
    return _fail_issue(record, exc)


def _fail_missing_subject(record: CredentialRecord, subject: str) -> CredentialRecord:
    record.status = CredentialRecordStatus.failed
    record.refused_reason = (
        f"Subject account {subject} does not exist on the ledger; "
        "fund the account first (minimum base reserve: 10 XRP on Testnet)."
    )
    _log(record.id, "Failed: subject account not funded on-ledger (tecNO_TARGET).")
    return _touch(record)


async def _reuse_duplicate_credential(
    record: CredentialRecord,
    request: CredentialIssueRequest,
    credential_type: str,
) -> CredentialRecord:
    _log(
        record.id,
        "Credential already exists on-ledger (tecDUPLICATE); checking its status.",
    )
    status = await credentials.verify_kyc(request.subject)
    record.verified = status.verified
    record.accepted = status.verified
    record.status = (
        CredentialRecordStatus.verified
        if status.verified
        else CredentialRecordStatus.issued
    )
    record.audit_explanation = _duplicate_audit_text(
        credential_type, request.subject, status.verified
    )
    _log(record.id, f"Reused existing credential: {status.reason}.")
    if not status.verified and request.auto_accept:
        return await _try_auto_accept(record)
    return _touch(record)


def _duplicate_audit_text(
    credential_type: str, subject: str, verified: bool
) -> str:
    state = "verified on-ledger." if verified else "awaiting subject acceptance."
    return f"Credential '{credential_type}' already present for {subject}; {state}"


async def _try_auto_accept(record: CredentialRecord) -> CredentialRecord:
    try:
        return await accept(record.id)
    except (NotImplementedError, InvalidCredentialState, ValueError) as exc:
        _log(record.id, f"Auto-accept skipped: {exc}.")
        return _touch(record)


def _fail_issue(record: CredentialRecord, exc: Exception) -> CredentialRecord:
    record.status = CredentialRecordStatus.failed
    record.refused_reason = f"CredentialCreate failed: {exc}"
    _log(record.id, f"Failed to submit CredentialCreate: {exc}.")
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
