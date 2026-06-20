"""KYA (Know Your Agent) — credential issuance and verification for AI agents.

Parallels credentials/kyc/tool.py (KYC for humans/entities) but targets AI agent
wallets. An agent must hold an accepted KYA credential before the ARS constraint
engine allows it to initiate payments, delegate, or call privileged tools.

The credential's URI field carries a compact AgentIdentity (see kya/uri.py):
  - agent_type : orchestrator | sub_agent | monitor | api_gateway
  - principal  : controlling XRPL address (the org that owns this agent)
  - scopes     : authorized action domains (payment, x402, delegation, ...)
  - issued_on  : ISO date
  - ref        : optional session / deployment reference

Policy boundary: this tool only *reports* KYA status. Whether a missing or
out-of-scope KYA credential blocks an action is decided by deterministic code
in ars/constraint_engine.py, never by the LLM.

In mock mode (settings.use_mock_xrpl) all lookups are offline and deterministic.
The treasury wallet address is automatically pre-credentialed as an orchestrator
so the payment flow works without a separate /kyc/kya/issue call in demos.
"""

from __future__ import annotations

from ... import xrpl_client
from ...config import get_settings
from ...schemas import AgentIdentityStatus, KYAIssueResponse
from . import uri as kya_uri
from .uri import AgentIdentity, AgentScope, AgentType


# ── Mock state ─────────────────────────────────────────────────────────────────

# (agent_address, issuer, credential_type) → AgentIdentity
_MOCK_KYA: dict[tuple[str, str, str], AgentIdentity] = {}


def reset_kya_mock_state() -> None:
    """Clear all mock KYA credentials (used by tests for isolation)."""
    _MOCK_KYA.clear()


def _auto_seed_mock(settings, issuer: str) -> None:
    """Pre-credential the treasury wallet as a full-scope orchestrator in mock mode.

    This ensures the payment workflow doesn't require a separate KYA issuance
    step in local dev and hackathon demos. The treasury wallet address (or a
    hard-coded mock address when not configured) is treated as already verified.
    """
    treasury = settings.treasury_wallet_address or "r_TREASURY_MOCK"
    key = (treasury, issuer, "KYA")
    if key not in _MOCK_KYA:
        _MOCK_KYA[key] = kya_uri.orchestrator_identity(
            principal=treasury,
            ref="auto-seeded-mock",
        )


# ── Issue ─────────────────────────────────────────────────────────────────────

async def issue_kya_credential(
    *,
    agent_address: str,
    identity: AgentIdentity,
    credential_type: str = "KYA",
) -> KYAIssueResponse:
    """Issue a KYA credential to an AI agent wallet.

    Mock mode: stores the identity in memory and returns a synthetic record.
    Real mode: submits CredentialCreate via the ledger helper (mirrors KYC issuance).
    """
    settings = get_settings()
    issuer = settings.credential_issuer_address or settings.token_issuer_address
    uri_str = kya_uri.build_kya_uri(identity)

    if settings.use_mock_xrpl:
        key = (agent_address, issuer, credential_type)
        _MOCK_KYA[key] = identity
        return KYAIssueResponse(
            agent_address=agent_address,
            issuer=issuer,
            credential_type=credential_type,
            uri=uri_str,
            identity={
                "agent_type": identity.agent_type.value,
                "principal": identity.principal,
                "scopes": [s.value for s in identity.scopes],
                "ref": identity.ref,
                "issued_on": identity.issued_on,
            },
            mock=True,
            status="accepted",
        )

    from ...ledger import Ledger
    from xrpl.models.transactions import CredentialAccept, CredentialCreate
    from xrpl.utils import str_to_hex

    endpoint = settings.credential_xrpl_endpoint or settings.xrpl_endpoint
    ledger = Ledger(settings)
    issuer_wallet = ledger.wallet(settings.credential_issuer_seed)
    subject_seed = (
        settings.treasury_wallet_seed
        if agent_address == settings.treasury_wallet_address
        else settings.credential_subject_seed
    )
    subject_wallet = ledger.wallet(subject_seed)
    try:
        await ledger.submit(CredentialCreate(
            account=issuer_wallet.address,
            subject=agent_address,
            credential_type=xrpl_client.credential_type_hex(credential_type),
            uri=str_to_hex(uri_str).upper(),
        ), issuer_wallet, endpoint=endpoint)
    except Exception as exc:
        if "tecDUPLICATE" not in str(exc):
            raise
    try:
        accepted = await ledger.submit(CredentialAccept(
            account=subject_wallet.address,
            issuer=issuer,
            credential_type=xrpl_client.credential_type_hex(credential_type),
        ), subject_wallet, endpoint=endpoint)
    except Exception as exc:
        if "tecDUPLICATE" not in str(exc):
            raise
        accepted = {"already_accepted": True}
    return KYAIssueResponse(
        agent_address=agent_address,
        issuer=issuer,
        credential_type=credential_type,
        uri=uri_str,
        identity={
            "agent_type": identity.agent_type.value,
            "principal": identity.principal,
            "scopes": [s.value for s in identity.scopes],
            "ref": identity.ref,
            "issued_on": identity.issued_on,
        },
        mock=False,
        status="accepted" if accepted else "issued",
    )


# ── Verify ────────────────────────────────────────────────────────────────────

async def verify_agent_kya(
    agent_address: str,
    required_scope: AgentScope | None = None,
) -> AgentIdentityStatus:
    """Check whether the agent holds a valid KYA credential.

    If `required_scope` is supplied, also verifies the credential's scope list
    includes that scope.  Returns `verified=False` when the credential is absent
    or the scope is unauthorized.
    """
    settings = get_settings()
    issuer = settings.credential_issuer_address or settings.token_issuer_address
    credential_type = "KYA"

    if settings.use_mock_xrpl:
        _auto_seed_mock(settings, issuer)
        return _mock_verify_kya(agent_address, issuer, credential_type, required_scope)

    # Real mode: use the same xrpl-py AccountObjects lookup as KYC. Keeping KYA
    # on this shared boundary avoids a second, incompatible Ledger API.
    try:
        from ... import xrpl_client
        from xrpl.utils import hex_to_str

        obj = await xrpl_client.lookup_accepted_credential(
            agent_address,
            issuer,
            xrpl_client.credential_type_hex(credential_type),
            settings.credential_xrpl_endpoint or settings.xrpl_endpoint,
        )
        if obj is None:
            return AgentIdentityStatus(
                checked=True,
                verified=False,
                agent_address=agent_address,
                issuer=issuer,
                credential_type=credential_type,
                reason="No accepted KYA credential from the trusted issuer",
            )
        uri_value = obj.get("URI")
        uri_str = hex_to_str(uri_value) if uri_value else None
        identity = kya_uri.parse_kya_uri(uri_str)
        return _build_status(
            agent_address=agent_address,
            issuer=issuer,
            credential_type=credential_type,
            identity=identity,
            required_scope=required_scope,
            verified=identity is not None,
            reason="KYA credential verified on ledger" if identity else "KYA credential URI could not be decoded",
        )
    except Exception as exc:
        return AgentIdentityStatus(
            checked=True,
            verified=False,
            agent_address=agent_address,
            issuer=issuer,
            credential_type=credential_type,
            reason=f"KYA ledger lookup failed: {exc}",
        )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _mock_verify_kya(
    agent_address: str,
    issuer: str,
    credential_type: str,
    required_scope: AgentScope | None,
) -> AgentIdentityStatus:
    key = (agent_address, issuer, credential_type)
    identity = _MOCK_KYA.get(key)

    if identity is None:
        return AgentIdentityStatus(
            checked=True,
            verified=False,
            agent_address=agent_address,
            issuer=issuer,
            credential_type=credential_type,
            reason="No KYA credential found (mock mode)",
        )

    return _build_status(
        agent_address=agent_address,
        issuer=issuer,
        credential_type=credential_type,
        identity=identity,
        required_scope=required_scope,
        verified=True,
        reason="KYA credential verified (mock mode)",
    )


def _build_status(
    *,
    agent_address: str,
    issuer: str,
    credential_type: str,
    identity: AgentIdentity | None,
    required_scope: AgentScope | None,
    verified: bool,
    reason: str,
) -> AgentIdentityStatus:
    scope_ok = True
    scope_reason = ""

    if verified and identity and required_scope:
        if not identity.has_scope(required_scope):
            scope_ok = False
            scope_reason = (
                f"scope '{required_scope.value}' not authorized "
                f"(credential grants: {identity.scope_summary})"
            )

    return AgentIdentityStatus(
        checked=True,
        verified=verified and scope_ok,
        agent_address=agent_address,
        issuer=issuer,
        credential_type=credential_type,
        agent_type=identity.agent_type.value if identity else None,
        principal=identity.principal if identity else None,
        scopes=[s.value for s in identity.scopes] if identity else [],
        issued_on=identity.issued_on if identity else None,
        ref=identity.ref if identity else None,
        scope_ok=scope_ok,
        scope_reason=scope_reason,
        reason=reason if scope_ok else scope_reason,
    )
