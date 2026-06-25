"""KYC / KYA routes.

KYC endpoints (Plaid IDV — sender identity verification):
  POST /kyc/idv/start          Create an IDV session; returns shareable_url.
  GET  /kyc/idv/{session_id}   Poll session status; returns verified + steps.

KYA endpoints (Know Your Agent — AI agent wallet credentialing):
  POST /kyc/kya/issue          Issue a KYA credential to an agent wallet.
  GET  /kyc/kya/{address}      Verify whether an agent holds a valid KYA credential.

KYA uses the same XRPL Credentials (XLS-70) infrastructure as KYC, but targets
AI agent wallets instead of human/entity counterparties. The credential URI field
carries an AgentIdentity (type, principal, scopes) encoded by tools/kya_uri.py.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..config import get_settings
from ..schemas import KYAIssueRequest, KYAIssueResponse, KYAVerifyResponse
from ..credentials.kya import tool as agent_credentials
from ..credentials.kya.uri import AgentScope, AgentType, AgentIdentity
from ..credentials.plaid import idv as plaid_idv

router = APIRouter(prefix="/kyc")


class IDVStartRequest(BaseModel):
    client_user_id: str  # unique sender ID (e.g. wallet address or user ID)
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
        raise HTTPException(
            status_code=502, detail=f"Plaid IDV session creation failed: {exc}"
        ) from exc

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
        raise HTTPException(
            status_code=502, detail=f"Plaid IDV lookup failed: {exc}"
        ) from exc

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


# ── KYA endpoints ─────────────────────────────────────────────────────────────


@router.post("/kya/issue", response_model=KYAIssueResponse)
async def issue_kya(body: KYAIssueRequest) -> KYAIssueResponse:
    """Issue a KYA (Know Your Agent) credential to an AI agent wallet.

    The credential encodes the agent's type, principal (controlling XRPL address),
    and authorized scopes into the XRPL Credential URI field using the compact
    JSON format defined in tools/kya_uri.py.

    Submits a CredentialCreate to the ledger and stores the credential in
    memory for the session.

    This endpoint is called once per agent deployment to bind the agent wallet
    to a declared identity before it can initiate payments or delegate actions.
    """
    try:
        agent_type = AgentType(body.agent_type)
    except ValueError:
        agent_type = AgentType.unknown

    scopes: list[AgentScope] = []
    for s in body.scopes:
        try:
            scopes.append(AgentScope(s))
        except ValueError:
            pass  # unknown scope values are silently dropped

    identity = AgentIdentity(
        agent_type=agent_type,
        principal=body.principal,
        scopes=scopes,
        ref=body.ref,
    )

    try:
        return await agent_credentials.issue_kya_credential(
            agent_address=body.agent_address,
            identity=identity,
            credential_type=body.credential_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"KYA issuance failed: {exc}"
        ) from exc


@router.get("/kya/{agent_address}", response_model=KYAVerifyResponse)
async def verify_kya(
    agent_address: str,
    scope: str | None = Query(
        default=None, description="Required scope to check (e.g. 'payment')"
    ),
) -> KYAVerifyResponse:
    """Verify whether an AI agent wallet holds a valid KYA credential.

    Returns verified=True when the agent has an accepted, non-expired KYA
    credential from the configured issuer. If `scope` is provided, also checks
    that the credential's scope list includes the requested scope.

    The compliance engine calls this before allowing any agent-initiated payment.
    The ARS constraint engine's G1 guardrail uses this result to block uncredentialed
    agents at the policy boundary — no payment flows without a passing G1 check.
    """
    required_scope: AgentScope | None = None
    if scope:
        try:
            required_scope = AgentScope(scope)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown scope '{scope}'. Valid scopes: {[s.value for s in AgentScope]}",
            )

    try:
        status = await agent_credentials.verify_agent_kya(agent_address, required_scope)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"KYA verification failed: {exc}"
        ) from exc

    return KYAVerifyResponse(
        agent_address=agent_address,
        verified=status.verified,
        agent_type=status.agent_type,
        principal=status.principal,
        scopes=status.scopes,
        scope_ok=status.scope_ok,
        scope_reason=status.scope_reason,
        reason=status.reason,
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
