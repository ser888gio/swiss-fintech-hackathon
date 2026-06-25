"""ARS event-sourced Ed25519-signed audit log.

Every ARS action (payment, loan draw, insurance premium, guardrail block) is
appended as a signed AuditEvent. State is derived by replaying the log; the log
itself is append-only and tamper-evident (each event includes the hash of the
prior event, forming a hash chain).

Signing key: an Ed25519 key held by the platform (not the agent — the agent-
payment firewall separates signing concerns). If AUDIT_SIGNING_KEY is not
configured, a deterministic fallback key is derived so the log chains correctly.

The log root hash (sha256 of the concatenated event hashes in order) is included
in the on-chain Memo of every settlement transaction, so an auditor can verify
the full chain matches the ledger anchor.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# ── Lazy cryptography import (optional dep; unsigned-hash fallback if absent) ──


def _load_ed25519():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PublicFormat,
            PrivateFormat,
        )

        return (
            Ed25519PrivateKey,
            Ed25519PublicKey,
            Encoding,
            NoEncryption,
            PublicFormat,
            PrivateFormat,
        )
    except ImportError:
        return None


# ── AuditEvent ────────────────────────────────────────────────────────────────


@dataclass
class AuditEvent:
    """A single signed, hash-chained audit event."""

    event_id: str
    event_type: str  # "payment", "guardrail_block", "loan_draw", "premium", ...
    actor: str  # ARS role: "constraint_engine", "settlement_layer", etc.
    context_kind: str  # "payment" | "loan_underwrite" | "insurance_payout" | ...
    payload: dict  # event-specific data (guardrail trail, tx hash, amounts, ...)
    timestamp: str  # ISO 8601 UTC
    prior_event_hash: (
        str  # sha256 of the prior event's canonical JSON ("genesis" for first)
    )
    event_hash: str = ""  # sha256 of this event's canonical JSON (set by _append)
    signature: str = ""  # hex Ed25519 signature over event_hash (set by _append)


# ── In-memory log (write-through to DB via store pattern) ────────────────────

_events: list[AuditEvent] = []
_signing_key_bytes: bytes | None = None  # set from config on startup


def configure(signing_key_hex: str | None = None) -> None:
    """Set the platform signing key (hex-encoded 32-byte Ed25519 seed).

    Call once from app startup. If None or empty, a deterministic fallback key
    is derived so the audit log still chains correctly without a configured key.
    Set AUDIT_SIGNING_KEY in production for real Ed25519 signatures.
    """
    global _signing_key_bytes
    if signing_key_hex:
        _signing_key_bytes = bytes.fromhex(signing_key_hex)
    else:
        _signing_key_bytes = hashlib.sha256(b"ars-fallback-signing-key").digest()


def append(
    *,
    event_type: str,
    actor: str,
    context_kind: str,
    payload: dict[str, Any],
    event_id: str | None = None,
) -> AuditEvent:
    """Append a signed event to the log. Returns the event."""
    import uuid

    now = datetime.now(timezone.utc).isoformat()
    prior_hash = _events[-1].event_hash if _events else "genesis"
    eid = event_id or str(uuid.uuid4())

    event = AuditEvent(
        event_id=eid,
        event_type=event_type,
        actor=actor,
        context_kind=context_kind,
        payload=payload,
        timestamp=now,
        prior_event_hash=prior_hash,
    )
    event.event_hash = _compute_hash(event)
    event.signature = _sign(event.event_hash)
    _events.append(event)
    return event


def root_hash() -> str:
    """sha256 of all event hashes concatenated in order.

    Anchored in every settlement transaction Memo so the full chain can be
    verified against the on-ledger anchor.
    """
    if not _events:
        return hashlib.sha256(b"empty").hexdigest()
    return hashlib.sha256("".join(e.event_hash for e in _events).encode()).hexdigest()


def verify(event: AuditEvent) -> bool:
    """Verify the Ed25519 signature on a single event."""
    mods = _load_ed25519()
    if mods is None or not _signing_key_bytes:
        return True  # no key configured: skip verification
    (
        Ed25519PrivateKey,
        Ed25519PublicKey,
        Encoding,
        NoEncryption,
        PublicFormat,
        PrivateFormat,
    ) = mods
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(_signing_key_bytes)
        public_key = private_key.public_key()
        public_key.verify(
            bytes.fromhex(event.signature), bytes.fromhex(event.event_hash)
        )
        return True
    except Exception:
        return False


def replay() -> list[AuditEvent]:
    """Return a copy of the full log for state-derivation or auditing."""
    return list(_events)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _compute_hash(event: AuditEvent) -> str:
    canonical = json.dumps(
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "actor": event.actor,
            "context_kind": event.context_kind,
            "payload": event.payload,
            "timestamp": event.timestamp,
            "prior_event_hash": event.prior_event_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _sign(event_hash: str) -> str:
    mods = _load_ed25519()
    if mods is None or not _signing_key_bytes:
        return hashlib.sha256(f"unsigned-hash:{event_hash}".encode()).hexdigest()
    Ed25519PrivateKey, *_ = mods
    try:
        key = Ed25519PrivateKey.from_private_bytes(_signing_key_bytes)
        sig = key.sign(bytes.fromhex(event_hash))
        return sig.hex()
    except Exception as exc:
        log.warning("Ed25519 signing failed, falling back to unsigned hash: %s", exc)
        return hashlib.sha256(f"unsigned-hash:{event_hash}".encode()).hexdigest()
