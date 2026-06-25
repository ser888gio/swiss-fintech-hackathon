"""MPToken tool for XLS-33 Multi-Purpose Tokens.

Creates a non-transferable "COMPLY" compliance-attestation issuance. After
each auto-settled payment the treasury agent mints one token to the recipient
as an on-chain proof of compliance clearance.

  MPTokenIssuanceCreate -> real tx, real explorer link.
  MPTokenAuthorize      -> real tx (issuer-side slot grant for the recipient).
  mint_attestation      -> real tx when MPT_RECIPIENT_ADDRESS/SEED are configured.

Network: XLS-33 is available on Testnet (wss://s.altnet.rippletest.net:51233)
and Devnet. Set MPT_XRPL_ENDPOINT to override; defaults to the main
XRPL_ENDPOINT setting.
"""

from __future__ import annotations

import binascii
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config import get_settings
from ..ledger import Ledger

COMPLY_METADATA = binascii.hexlify(b"COMPLY").decode().upper()


_state: dict = {
    "issuance_id": None,
    "authorized": [],
    "total_minted": 0,
    "attestations": [],
}


@dataclass
class MPTIssuanceResult:
    issuance_id: str
    tx_hash: str
    explorer_url: str | None
    metadata_hex: str


@dataclass
class MPTOpResult:
    operation: str
    issuance_id: str
    recipient: str
    amount: int
    tx_hash: str
    explorer_url: str | None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def get_mpt_state() -> dict:
    """Return a snapshot of the in-memory MPT state."""
    return {
        **_state,
        "authorized": list(_state["authorized"]),
        "attestations": list(_state["attestations"]),
    }


async def create_issuance() -> MPTIssuanceResult:
    """MPTokenIssuanceCreate: provision the COMPLY attestation issuance.

    Flags: no tfMPTCanTransfer, no tfMPTCanTrade -> soulbound compliance badge.
    The tx lands on the configured MPT network (Testnet by default).
    """
    settings = get_settings()
    from xrpl.models.transactions import MPTokenIssuanceCreate

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet
    tx = MPTokenIssuanceCreate(
        account=wallet.address,
        asset_scale=0,
        mptoken_metadata=COMPLY_METADATA,
    )
    endpoint = _mpt_endpoint(settings)
    result = await ledger.submit(tx, wallet, endpoint=endpoint)
    tx_hash = result["hash"]
    issuance_id = _parse_issuance_id(result)
    if not issuance_id:
        raise RuntimeError("MPTokenIssuanceCreate did not return an issuance id")
    _state["issuance_id"] = issuance_id
    url = ledger.explorer_url(tx_hash, endpoint)
    return MPTIssuanceResult(
        issuance_id=issuance_id,
        tx_hash=tx_hash,
        explorer_url=url,
        metadata_hex=COMPLY_METADATA,
    )


async def authorize_holder(issuance_id: str, holder: str) -> MPTOpResult:
    """MPTokenAuthorize: create the recipient's MPToken slot for COMPLY badges."""
    settings = get_settings()
    from xrpl.models.transactions import MPTokenAuthorize

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet
    tx = MPTokenAuthorize(
        account=wallet.address,
        mptoken_issuance_id=issuance_id,
        holder=holder,
    )
    endpoint = _mpt_endpoint(settings)
    result = await ledger.submit(tx, wallet, endpoint=endpoint)
    tx_hash = result["hash"]
    _remember_authorized(holder)
    return _op_result(
        operation="authorize",
        issuance_id=issuance_id,
        recipient=holder,
        amount=0,
        tx_hash=tx_hash,
        explorer_url=ledger.explorer_url(tx_hash, endpoint),
    )


async def mint_attestation(
    issuance_id: str,
    recipient: str,
    payment_id: str,
    amount_settled: float,
) -> MPTOpResult:
    """Mint 1 COMPLY token to the recipient as an on-chain compliance record.

    Submits a Payment with MPTAmount when MPT_RECIPIENT_ADDRESS and
    MPT_RECIPIENT_SEED are configured (the recipient must have called
    MPTokenAuthorize first). The attestation is appended to the audit trail.
    """
    settings = get_settings()
    if not (settings.mpt_recipient_address and settings.mpt_recipient_seed):
        raise RuntimeError("MPT_RECIPIENT_ADDRESS/MPT_RECIPIENT_SEED not configured")
    return await _real_mint(
        issuance_id, recipient, payment_id, amount_settled, settings
    )


async def _real_mint(
    issuance_id: str,
    recipient: str,
    payment_id: str,
    amount_settled: float,
    settings,
) -> MPTOpResult:
    from xrpl.models.amounts import MPTAmount
    from xrpl.models.transactions import Payment

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet
    tx = Payment(
        account=wallet.address,
        destination=recipient,
        amount=MPTAmount(mpt_issuance_id=issuance_id, value="1"),
    )
    endpoint = _mpt_endpoint(settings)
    result = await ledger.submit(tx, wallet, endpoint=endpoint)
    tx_hash = result["hash"]
    url = ledger.explorer_url(tx_hash, endpoint)
    return _record_attestation(
        issuance_id=issuance_id,
        recipient=recipient,
        payment_id=payment_id,
        amount_settled=amount_settled,
        tx_hash=tx_hash,
        explorer_url=url,
    )


def _record_attestation(
    *,
    issuance_id: str,
    recipient: str,
    payment_id: str,
    amount_settled: float,
    tx_hash: str,
    explorer_url: str | None,
) -> MPTOpResult:
    _state["total_minted"] += 1
    now = _now()
    _state["attestations"].append(
        {
            "id": str(uuid.uuid4()),
            "operation": "mint",
            "issuance_id": issuance_id,
            "recipient": recipient,
            "payment_id": payment_id,
            "amount_settled": amount_settled,
            "tx_hash": tx_hash,
            "explorer_url": explorer_url,
            "timestamp": now.isoformat(),
        }
    )
    return _op_result(
        operation="mint",
        issuance_id=issuance_id,
        recipient=recipient,
        amount=1,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        timestamp=now,
    )


def _mpt_endpoint(settings) -> str:
    return settings.mpt_xrpl_endpoint or settings.xrpl_endpoint


def _remember_authorized(holder: str) -> None:
    if holder not in _state["authorized"]:
        _state["authorized"].append(holder)


def _op_result(
    *,
    operation: str,
    issuance_id: str,
    recipient: str,
    amount: int,
    tx_hash: str,
    explorer_url: str | None,
    timestamp: datetime | None = None,
) -> MPTOpResult:
    return MPTOpResult(
        operation=operation,
        issuance_id=issuance_id,
        recipient=recipient,
        amount=amount,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        timestamp=timestamp or _now(),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_issuance_id(result: dict) -> str | None:
    for node in result.get("meta", {}).get("AffectedNodes", []):
        created = node.get("CreatedNode", {})
        if created.get("LedgerEntryType") == "MPTokenIssuance":
            return created.get("LedgerIndex")
    return None
