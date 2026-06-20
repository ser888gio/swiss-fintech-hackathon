"""KYC routes — Plaid Identity Verification (IDV) for sender verification.

Endpoints:
  POST /kyc/idv/start          Create an IDV session; returns shareable_url.
  GET  /kyc/idv/{session_id}   Poll session status; returns verified + steps.

The frontend calls /kyc/idv/start before the payment form is submitted,
opens the shareable_url in a modal, then polls /kyc/idv/{session_id} until
status is "success" or "failed". The session_id is passed to the payment
intent so compliance can factor in sender verification.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..tools import plaid_idv

router = APIRouter(prefix="/kyc")


class IDVStartRequest(BaseModel):
    client_user_id: str          # unique sender ID (e.g. wallet address or user ID)
    given_name: str | None = None
    family_name: str | None = None
    email: str | None = None


class IDVStartResponse(BaseModel):
    session_id: str
    shareable_url: str | None
    status: str


class IDVStatusResponse(BaseModel):
    session_id: str
    status: str
    verified: bool
    documentary_verified: bool
    selfie_verified: bool
    given_name: str | None
    family_name: str | None
    date_of_birth: str | None
    country: str | None
    failure_reasons: list[str]


@router.post("/idv/start", response_model=IDVStartResponse)
def start_idv(body: IDVStartRequest) -> IDVStartResponse:
    """Create a Plaid IDV session for the sender.

    Returns a shareable_url — open this in the frontend (modal or redirect)
    so the user can scan their government-issued ID and complete a selfie check.
    """
    settings = get_settings()
    _require_plaid(settings)

    try:
        session = plaid_idv.create_session(
            client_id=settings.plaid_client_id,
            secret=settings.plaid_secret,
            plaid_env=settings.plaid_env,
            template_id=settings.plaid_idv_template_id,
            client_user_id=body.client_user_id,
            email=body.email,
            given_name=body.given_name,
            family_name=body.family_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Plaid IDV session creation failed: {exc}") from exc

    return IDVStartResponse(
        session_id=session.session_id,
        shareable_url=session.shareable_url,
        status=session.status.value,
    )


@router.get("/idv/{session_id}", response_model=IDVStatusResponse)
def get_idv_status(session_id: str) -> IDVStatusResponse:
    """Poll the status of a Plaid IDV session.

    Returns verified=True when the sender has passed all steps.
    Call this until status is "success", "failed", or "expired".
    """
    settings = get_settings()
    _require_plaid(settings)

    try:
        session = plaid_idv.get_session(
            client_id=settings.plaid_client_id,
            secret=settings.plaid_secret,
            plaid_env=settings.plaid_env,
            session_id=session_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Plaid IDV lookup failed: {exc}") from exc

    return IDVStatusResponse(
        session_id=session.session_id,
        status=session.status.value,
        verified=session.verified,
        documentary_verified=session.documentary_verified,
        selfie_verified=session.selfie_verified,
        given_name=session.given_name,
        family_name=session.family_name,
        date_of_birth=session.date_of_birth,
        country=session.country,
        failure_reasons=session.failure_reasons,
    )


def _require_plaid(settings) -> None:
    if not (settings.plaid_client_id and settings.plaid_secret):
        raise HTTPException(status_code=503, detail="Plaid credentials not configured")
    if not settings.plaid_idv_template_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "Plaid IDV template not configured. "
                "Create a template in the Plaid Dashboard under Identity Verification → Templates "
                "and set PLAID_IDV_TEMPLATE_ID in .env"
            ),
        )
