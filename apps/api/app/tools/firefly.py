"""Firefly approval tool.

Builds the approval challenge the Firefly hardware device signs, and verifies the
returned secp256k1 signature against the pre-registered public key. Release of a
locked payment is refused unless verification succeeds — this is the hardware
veto. The Firefly displays the request and signs only on a physical button press
(github.com/firefly).

Canonical payload format (v1):
    XRPL_TREASURY_APPROVAL_V1|{network}|{payment_id}|{owner}|{destination}|
    {asset_code}|{amount:.2f}|{escrow_sequence}|{escrow_create_tx_hash}

The network prefix prevents testnet-signed approvals from being replayed on
mainnet. The escrow_sequence + escrow_create_tx_hash bind the approval to exactly
one EscrowCreate — a compromised backend cannot redirect funds to a different
escrow and still get a valid signature. Any change to this format MUST be
mirrored in apps/firefly-bridge/src/device.ts (deriveDigest).
"""

from __future__ import annotations

import hashlib

from eth_keys import keys
from eth_keys.exceptions import BadSignature, ValidationError

from ..config import get_settings
from ..schemas import ApprovalChallenge, Payment

PAYLOAD_VERSION = "XRPL_TREASURY_APPROVAL_V1"


def canonical_payload(
    payment_id: str,
    amount: float,
    currency: str,
    dest: str,
    network: str,
    owner: str,
    escrow_sequence: int,
    escrow_create_tx_hash: str,
) -> str:
    """Canonical string the device signs. Format is pinned; amount always 2dp.

    The TS bridge replicates this exactly in apps/firefly-bridge/src/device.ts.
    Any change here MUST be mirrored there.
    """
    return (
        f"{PAYLOAD_VERSION}|{network}|{payment_id}|{owner}|{dest}"
        f"|{currency}|{amount:.2f}|{escrow_sequence}|{escrow_create_tx_hash}"
    )


def challenge_digest(
    payment_id: str,
    amount: float,
    currency: str,
    dest: str,
    network: str,
    owner: str,
    escrow_sequence: int,
    escrow_create_tx_hash: str,
) -> str:
    """sha256 of the canonical payload, hex-encoded."""
    return hashlib.sha256(
        canonical_payload(
            payment_id,
            amount,
            currency,
            dest,
            network,
            owner,
            escrow_sequence,
            escrow_create_tx_hash,
        ).encode()
    ).hexdigest()


def challenge_for_payment(payment: Payment) -> ApprovalChallenge:
    """Derive the approval challenge for a payment awaiting hardware approval.

    Raises ValueError if the payment has not been locked on-chain yet (escrow
    fields are absent).
    """
    if payment.escrow_sequence is None or not payment.escrow_create_tx_hash:
        raise ValueError(
            f"Payment {payment.id} has no escrow fields — "
            "challenge can only be built for pending_approval payments"
        )
    settings = get_settings()
    network = settings.xrpl_network
    owner = settings.treasury_wallet_address
    if not owner:
        raise ValueError(
            "treasury_wallet_address must be configured to build a Firefly approval challenge"
        )
    return _build_approval_challenge(
        payment_id=payment.id,
        amount=payment.intent.amount,
        currency=payment.intent.currency,
        dest=payment.intent.to,
        network=network,
        owner=owner,
        escrow_sequence=payment.escrow_sequence,
        escrow_create_tx_hash=payment.escrow_create_tx_hash,
    )


def _build_approval_challenge(
    payment_id: str,
    amount: float,
    currency: str,
    dest: str,
    network: str,
    owner: str,
    escrow_sequence: int,
    escrow_create_tx_hash: str,
) -> ApprovalChallenge:
    digest = challenge_digest(
        payment_id,
        amount,
        currency,
        dest,
        network,
        owner,
        escrow_sequence,
        escrow_create_tx_hash,
    )
    return ApprovalChallenge(
        payment_id=payment_id,
        digest=digest,
        network=network,
        owner=owner,
    )


def verify_signature(digest_hex: str, signature_hex: str) -> bool:
    """Return True only if the signature over `digest_hex` was produced by the
    registered Firefly key. Returns False (never raises) on any bad input."""
    public_key_hex = get_settings().firefly_public_key
    if not public_key_hex:
        return False
    try:
        digest = bytes.fromhex(_strip0x(digest_hex))
        sig_bytes = bytes.fromhex(_strip0x(signature_hex))
        # Normalize Ethereum-style recovery IDs (27/28) to 0/1.
        if len(sig_bytes) == 65 and sig_bytes[64] in (27, 28):
            sig_bytes = sig_bytes[:64] + bytes([sig_bytes[64] - 27])
        signature = keys.Signature(sig_bytes)
        public_key = keys.PublicKey(bytes.fromhex(_strip0x(public_key_hex)))
        return signature.verify_msg_hash(digest, public_key)
    except (BadSignature, ValidationError, ValueError):
        return False


def _strip0x(value: str) -> str:
    return value[2:] if value.startswith("0x") else value
