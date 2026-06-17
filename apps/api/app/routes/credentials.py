"""Credential-issuing agent endpoints.

Parallel to /payments: a second agent that issues, accepts, and verifies XRPL
Credentials (XLS-70). The issuance decision is a deterministic sanctions screen
inside the agent, never the LLM.
"""

from fastapi import APIRouter, HTTPException

from .. import store
from ..agents import credential_agent
from ..schemas import (
    CredentialIssueRequest,
    CredentialLogEntry,
    CredentialRecord,
    CredentialStatus,
)
from ..tools import credentials as credentials_tool

router = APIRouter(prefix="/credentials")


@router.post("", response_model=CredentialRecord)
async def issue_credential(request: CredentialIssueRequest) -> CredentialRecord:
    try:
        return await credential_agent.issue(request)
    except Exception as exc:  # surface agent/config errors as a clean 502
        raise HTTPException(status_code=502, detail=f"credential issuance failed: {exc}") from exc


@router.get("", response_model=list[CredentialRecord])
async def list_credentials() -> list[CredentialRecord]:
    return store.list_credentials()


@router.get("/{record_id}", response_model=CredentialRecord)
async def get_credential(record_id: str) -> CredentialRecord:
    record = store.get_credential(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="credential not found")
    return record


@router.get("/{record_id}/logs", response_model=list[CredentialLogEntry])
async def get_credential_logs(record_id: str) -> list[CredentialLogEntry]:
    return store.credential_logs_for(record_id)


@router.post("/{record_id}/accept", response_model=CredentialRecord)
async def accept_credential(record_id: str) -> CredentialRecord:
    try:
        return await credential_agent.accept(record_id)
    except credential_agent.CredentialNotFound as exc:
        raise HTTPException(status_code=404, detail="credential not found") from exc
    except credential_agent.InvalidCredentialState as exc:
        raise HTTPException(status_code=409, detail="credential is not awaiting acceptance") from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{record_id}/verify", response_model=CredentialRecord)
async def verify_credential(record_id: str) -> CredentialRecord:
    try:
        return await credential_agent.verify(record_id)
    except credential_agent.CredentialNotFound as exc:
        raise HTTPException(status_code=404, detail="credential not found") from exc


@router.get("/verify/{subject}", response_model=CredentialStatus)
async def verify_subject(subject: str) -> CredentialStatus:
    """Ad-hoc on-ledger KYC lookup for any subject address (no stored record)."""
    return await credentials_tool.verify_kyc(subject)
