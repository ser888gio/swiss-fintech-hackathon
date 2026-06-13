"""Firefly approval tool.

Builds the approval challenge the Firefly hardware device signs, and verifies the
returned secp256k1 signature against the pre-registered public key. Release of a
locked payment is refused unless verification succeeds — this is the hardware
veto. The Firefly displays the request and signs only on a physical button press
(github.com/firefly).
"""

from __future__ import annotations

import hashlib

from eth_keys import keys
from eth_keys.exceptions import BadSignature, ValidationError

from ..config import get_settings
from ..schemas import ApprovalChallenge


def build_approval_challenge(payment_id: str, amount: float, dest: str) -> ApprovalChallenge:
    """Derive the digest the device signs. Binding payment id + amount + dest
    means a captured signature cannot be replayed against a different payment."""
    payload = f"{payment_id}|{amount}|{dest}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    return ApprovalChallenge(payment_id=payment_id, digest=digest)


def verify_signature(digest_hex: str, signature_hex: str) -> bool:
    """Return True only if the signature over `digest_hex` was produced by the
    registered Firefly key. Returns False (never raises) on any bad input."""
    public_key_hex = get_settings().firefly_public_key
    if not public_key_hex:
        return False
    try:
        digest = bytes.fromhex(_strip0x(digest_hex))
        signature = keys.Signature(bytes.fromhex(_strip0x(signature_hex)))
        public_key = keys.PublicKey(bytes.fromhex(_strip0x(public_key_hex)))
        return signature.verify_msg_hash(digest, public_key)
    except (BadSignature, ValidationError, ValueError):
        return False


def _strip0x(value: str) -> str:
    return value[2:] if value.startswith("0x") else value
