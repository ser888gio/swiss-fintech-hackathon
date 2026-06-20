"""Credentials tool: XRPL Credentials (XLS-70) KYC.

Issues and verifies on-ledger KYC credentials for counterparties. The treasury
(or a trusted KYC provider) issues a `CredentialCreate` to a subject; the subject
must `CredentialAccept` it before it is valid. Before auto-settling, the workflow
verifies the receiver holds an *accepted*, non-expired credential of the
configured type from the trusted issuer.

Determinism boundary: this tool only *reports* credential status. Whether a
missing credential escalates a payment to hardware approval is decided by
deterministic policy code, never by the LLM.

In mock mode (settings.use_mock_xrpl) the lookups are deterministic and offline so
the full workflow runs without a ledger. Real submission/lookup is gated behind
the mock flag and a configured issuer.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ... import xrpl_client
from ...config import get_settings
from ...ledger import Ledger
from ...schemas import CredentialStatus, VerificationSteps, VerificationStepStatus
from . import uri as credential_uri

# Demo subjects treated as un-KYC'd in mock mode, so the credential gate can be
# demonstrated offline. Everyone else is considered verified in the mock.
MOCK_UNVERIFIED_SUBJECTS = {"rUNVERIFIED00000000000000000000000"}

# Credentials accepted during this mock session, keyed by (subject, issuer, type).
# Lets the inline KYC gate work offline: after the agent issues + accepts a
# credential for an un-KYC'd subject, verify_kyc flips it to verified.
_MOCK_ACCEPTED: set[tuple[str, str, str]] = set()

# URI strings stored at issue time so mock verify can decode steps.
# Key: (subject, issuer, credential_type) → (uri_str, VerificationSteps | None)
_MOCK_URIS: dict[tuple[str, str, str], tuple[str | None, credential_uri.VerificationSteps | None]] = {}


def reset_mock_state() -> None:
    """Clear mock-accepted credentials (used by tests for isolation)."""
    _MOCK_ACCEPTED.clear()
    _MOCK_URIS.clear()


async def verify_kyc(subject: str) -> CredentialStatus:
    """Verify the subject holds a valid KYC credential from the trusted issuer."""
    settings = get_settings()
    if not settings.credential_kyc_enabled:
        return _status(subject, checked=False, reason="KYC credential layer disabled")

    issuer = settings.credential_issuer_address or settings.token_issuer_address
    credential_type = settings.credential_type

    if settings.use_mock_xrpl:
        return _mock_verify(subject, issuer, credential_type)

    try:
        obj = await xrpl_client.lookup_accepted_credential(
            subject, issuer, xrpl_client.credential_type_hex(credential_type)
        )
    except Exception as exc:  # network/ledger errors must not crash the workflow
        return _status(
            subject,
            issuer=issuer,
            credential_type=credential_type,
            reason=f"credential lookup failed: {exc}",
        )

    if obj is None:
        return _status(
            subject,
            issuer=issuer,
            credential_type=credential_type,
            reason="no accepted KYC credential from trusted issuer",
        )

    expiration = _from_ripple_time(obj.get("Expiration"))
    if expiration is not None and expiration < datetime.now(timezone.utc):
        return _status(
            subject,
            issuer=issuer,
            credential_type=credential_type,
            expiration=expiration,
            reason="KYC credential expired",
        )

    uri_str = _hex_to_str(obj.get("URI"))
    steps = _decode_steps(uri_str)

    return _status(
        subject,
        verified=True,
        issuer=issuer,
        credential_type=credential_type,
        expiration=expiration,
        uri=uri_str,
        steps=steps,
        reason="accepted KYC credential verified on-ledger",
    )


async def issue_credential(
    subject: str,
    uri: str | None = None,
    expiration: datetime | None = None,
    credential_type: str | None = None,
    steps: credential_uri.VerificationSteps | None = None,
) -> dict:
    """Issue a KYC credential to `subject` (CredentialCreate).

    Pass `steps` to encode per-step verification outcomes (documentary, selfie,
    sanctions, PEP) into the URI field — modelled on Plaid IDV's step schema.
    The subject must accept the credential before it verifies.
    """
    settings = get_settings()
    credential_type = credential_type or settings.credential_type

    # Encode steps into URI if provided and no explicit URI given
    if steps is not None and uri is None:
        uri = credential_uri.build_uri(steps)

    if settings.use_mock_xrpl:
        key = (subject, settings.credential_issuer_address, credential_type)
        decoded = credential_uri.parse_uri(uri) if uri else None
        _MOCK_URIS[key] = (uri, decoded)
        return _credential_response(
            subject=subject,
            issuer=settings.credential_issuer_address,
            credential_type=credential_type,
            tx_hash=xrpl_client.mock_tx_hash("credential", subject),
            uri=uri,
            accepted=False,
        )

    if not settings.credential_issuer_seed:
        raise NotImplementedError("CREDENTIAL_ISSUER_SEED required to issue credentials")

    from xrpl.models.transactions import CredentialCreate
    from xrpl.utils import str_to_hex

    ledger = Ledger(settings)
    wallet = ledger.wallet(settings.credential_issuer_seed)
    tx = CredentialCreate(
        account=wallet.address,
        subject=subject,
        credential_type=xrpl_client.credential_type_hex(credential_type),
        uri=str_to_hex(uri).upper() if uri else None,
        expiration=_to_ripple_time(expiration),
    )
    result = await ledger.submit(tx, wallet)
    tx_hash = result["hash"]
    return _credential_response(
        subject=subject,
        issuer=wallet.address,
        credential_type=credential_type,
        tx_hash=tx_hash,
        uri=uri,
        explorer_url=xrpl_client.explorer_tx_url(tx_hash),
        accepted=False,
    )


async def accept_credential(
    subject: str,
    issuer: str | None = None,
    credential_type: str | None = None,
    subject_seed: str | None = None,
) -> dict:
    """Subject-side CredentialAccept: the subject accepts a credential issued to it.

    A credential only becomes usable once accepted (lsfAccepted). On a real
    network the subject must sign this themselves; for Testnet demos the subject
    seed is read from config (`CREDENTIAL_SUBJECT_SEED`) or passed explicitly.
    """
    settings = get_settings()
    issuer = issuer or settings.credential_issuer_address or settings.token_issuer_address
    credential_type = credential_type or settings.credential_type

    if settings.use_mock_xrpl:
        key = (subject, issuer, credential_type)
        _MOCK_ACCEPTED.add(key)
        # Preserve any URI that was stored at issue time
        if key not in _MOCK_URIS:
            _MOCK_URIS[key] = (None, None)
        return _credential_response(
            subject=subject,
            issuer=issuer,
            credential_type=credential_type,
            tx_hash=xrpl_client.mock_tx_hash("accept", subject),
            accepted=True,
        )

    seed = subject_seed or settings.credential_subject_seed
    if not seed:
        raise NotImplementedError(
            "CREDENTIAL_SUBJECT_SEED (or an explicit subject_seed) is required to accept"
        )

    from xrpl.models.transactions import CredentialAccept

    ledger = Ledger(settings)
    wallet = ledger.wallet(seed)
    tx = CredentialAccept(
        account=wallet.address,
        issuer=issuer,
        credential_type=xrpl_client.credential_type_hex(credential_type),
    )
    try:
        result = await ledger.submit(tx, wallet)
        tx_hash = result["hash"]
        explorer_url = xrpl_client.explorer_tx_url(tx_hash)
    except Exception as exc:
        # tecDUPLICATE means the credential is already accepted — still valid.
        if "tecDUPLICATE" not in str(exc):
            raise
        tx_hash = xrpl_client.mock_tx_hash("accept-dup", subject)
        explorer_url = None
    return _credential_response(
        subject=wallet.address,
        issuer=issuer,
        credential_type=credential_type,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        accepted=True,
    )


def _mock_verify(subject: str, issuer: str, credential_type: str) -> CredentialStatus:
    accepted = (subject, issuer, credential_type) in _MOCK_ACCEPTED
    verified = accepted or subject not in MOCK_UNVERIFIED_SUBJECTS
    # Decode steps from the mock-accepted URI if one was stored
    uri, steps = _MOCK_URIS.get((subject, issuer, credential_type), (None, None))
    return _status(
        subject,
        verified=verified,
        issuer=issuer,
        credential_type=credential_type,
        uri=uri,
        steps=steps,
        reason=(
            "mock: accepted KYC credential present"
            if verified
            else "mock: no KYC credential on file"
        ),
    )


def _decode_steps(uri: str | None) -> VerificationSteps | None:
    """Parse verification steps from a credential URI string."""
    parsed = credential_uri.parse_uri(uri)
    if parsed is None:
        return None
    # Convert credential_uri.VerificationSteps → schemas.VerificationSteps
    def _s(st: credential_uri.StepStatus) -> VerificationStepStatus:
        return VerificationStepStatus(st.value)
    return VerificationSteps(
        documentary=_s(parsed.documentary),
        selfie=_s(parsed.selfie),
        kyc=_s(parsed.kyc),
        sanctions=_s(parsed.sanctions),
        pep=_s(parsed.pep),
        ref=parsed.ref,
        issued_on=parsed.issued_on,
    )


def _status(
    subject: str,
    *,
    checked: bool = True,
    verified: bool = False,
    issuer: str | None = None,
    credential_type: str | None = None,
    expiration: datetime | None = None,
    uri: str | None = None,
    steps: VerificationSteps | None = None,
    reason: str,
) -> CredentialStatus:
    return CredentialStatus(
        checked=checked,
        verified=verified,
        subject=subject,
        issuer=issuer,
        credential_type=credential_type,
        expiration=expiration,
        uri=uri,
        verification_steps=steps,
        reason=reason,
    )


def _credential_response(
    *,
    subject: str,
    issuer: str | None,
    credential_type: str,
    tx_hash: str,
    accepted: bool,
    uri: str | None = None,
    explorer_url: str | None = None,
) -> dict:
    return {
        "txHash": tx_hash,
        "subject": subject,
        "issuer": issuer,
        "credentialType": credential_type,
        "uri": uri,
        "explorerUrl": explorer_url,
        "accepted": accepted,
    }


# XRPL stores time as seconds since the Ripple epoch; xrpl-py owns the offset.
def _to_ripple_time(value: datetime | None) -> int | None:
    if value is None:
        return None
    from xrpl.utils import datetime_to_ripple_time

    return datetime_to_ripple_time(value)


def _from_ripple_time(value) -> datetime | None:
    if value is None:
        return None
    from xrpl.utils import ripple_time_to_datetime

    return ripple_time_to_datetime(int(value))


def _hex_to_str(value) -> str | None:
    if not value:
        return None
    from xrpl.utils import hex_to_str

    try:
        return hex_to_str(value)
    except (ValueError, UnicodeDecodeError):
        return str(value)
