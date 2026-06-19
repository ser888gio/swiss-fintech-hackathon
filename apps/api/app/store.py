"""Payment and credential store — write-through cache.

Public interface is synchronous (unchanged from the in-memory skeleton) so no
call site needs to change. Each write updates the in-memory dict immediately and
schedules an async DB persist via `asyncio.create_task`; reads always hit the
in-memory dict, which is always current.

On startup, `load_from_db()` (called from `main.py lifespan`) hydrates the
in-memory dicts from Postgres so the app recovers its full state after a restart.
If Postgres is unavailable the in-memory dicts start empty and all writes are
lost on restart — the same behaviour as the original skeleton.

The DB layer (db.py) is optional: all DB calls are guarded by
`if db.session_factory is not None`. Unit tests and demo mode work without any
database configured.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from . import db
from .models import (
    AgentLogRecord,
    CredentialLogRecord,
    CredentialRecord as CredentialRecordDB,
    PaymentRecord,
    SpendReservationRecord,
)
from .schemas import (
    AgentLogEntry,
    ComplianceResult,
    CredentialLogEntry,
    CredentialRecord,
    CredentialRecordStatus,
    Payment,
    PaymentIntent,
    PaymentStatus,
    PolicyDecision,
    ReceiverEntityType,
    RouteQuote,
)

log = logging.getLogger(__name__)

# ── In-memory primary store ────────────────────────────────────────────────────
_payments: dict[str, Payment] = {}
_logs: list[AgentLogEntry] = []
_credentials: dict[str, CredentialRecord] = {}
_credential_logs: list[CredentialLogEntry] = []


# ── Public sync interface (unchanged from original) ────────────────────────────

def save(payment: Payment) -> Payment:
    _payments[payment.id] = payment
    _schedule(_persist_payment(payment))
    return payment


def get(payment_id: str) -> Payment | None:
    return _payments.get(payment_id)


def list_payments() -> list[Payment]:
    return sorted(_payments.values(), key=lambda p: p.created_at, reverse=True)


def append_log(entry: AgentLogEntry) -> None:
    _logs.append(entry)
    _schedule(_persist_log(entry))


def logs_for(payment_id: str) -> list[AgentLogEntry]:
    return [e for e in _logs if e.payment_id == payment_id]


def save_credential(record: CredentialRecord) -> CredentialRecord:
    _credentials[record.id] = record
    _schedule(_persist_credential(record))
    return record


def get_credential(record_id: str) -> CredentialRecord | None:
    return _credentials.get(record_id)


def list_credentials() -> list[CredentialRecord]:
    return sorted(_credentials.values(), key=lambda r: r.created_at, reverse=True)


def append_credential_log(entry: CredentialLogEntry) -> None:
    _credential_logs.append(entry)
    _schedule(_persist_credential_log(entry))


def credential_logs_for(record_id: str) -> list[CredentialLogEntry]:
    return [e for e in _credential_logs if e.record_id == record_id]


# ── Startup hydration ──────────────────────────────────────────────────────────

async def load_from_db() -> None:
    """Hydrate in-memory dicts from Postgres after a restart.

    Called once from `main.py lifespan` after `db.init_db`. Silently no-ops if
    Postgres is unavailable. Existing in-memory entries win on collision (there
    shouldn't be any at startup, but guard anyway).
    """
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            await _load_payments(session)
            await _load_logs(session)
            await _load_credentials(session)
            await _load_credential_logs(session)
        log.info(
            "Loaded %d payments, %d credentials from Postgres.",
            len(_payments),
            len(_credentials),
        )
    except Exception as exc:
        log.warning("Failed to load from DB: %s", exc)


# ── Async persist helpers (private) ───────────────────────────────────────────

async def _persist_payment(payment: Payment) -> None:
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            row = _payment_to_row(payment)
            await session.merge(row)
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist payment %s: %s", payment.id, exc)


async def _persist_log(entry: AgentLogEntry) -> None:
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            row = AgentLogRecord(
                payment_id=entry.payment_id,
                timestamp=entry.timestamp,
                message=entry.message,
            )
            session.add(row)
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist log for %s: %s", entry.payment_id, exc)


async def _persist_credential(record: CredentialRecord) -> None:
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            row = _credential_to_row(record)
            await session.merge(row)
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist credential %s: %s", record.id, exc)


async def _persist_credential_log(entry: CredentialLogEntry) -> None:
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            row = CredentialLogRecord(
                record_id=entry.record_id,
                timestamp=entry.timestamp,
                message=entry.message,
            )
            session.add(row)
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist credential log for %s: %s", entry.record_id, exc)


# ── Load helpers ───────────────────────────────────────────────────────────────

async def _load_payments(session) -> None:
    rows = (await session.execute(select(PaymentRecord))).scalars().all()
    for row in rows:
        if row.id not in _payments:
            try:
                _payments[row.id] = _row_to_payment(row)
            except Exception as exc:
                log.warning("Skipping malformed payment row %s: %s", row.id, exc)


async def _load_logs(session) -> None:
    rows = (await session.execute(select(AgentLogRecord))).scalars().all()
    existing_keys = {(e.payment_id, e.timestamp, e.message) for e in _logs}
    for row in rows:
        key = (row.payment_id, row.timestamp, row.message)
        if key not in existing_keys:
            _logs.append(AgentLogEntry(
                payment_id=row.payment_id,
                timestamp=row.timestamp,
                message=row.message,
            ))


async def _load_credentials(session) -> None:
    rows = (await session.execute(select(CredentialRecordDB))).scalars().all()
    for row in rows:
        if row.id not in _credentials:
            try:
                _credentials[row.id] = _row_to_credential(row)
            except Exception as exc:
                log.warning("Skipping malformed credential row %s: %s", row.id, exc)


async def _load_credential_logs(session) -> None:
    rows = (await session.execute(select(CredentialLogRecord))).scalars().all()
    existing_keys = {(e.record_id, e.timestamp, e.message) for e in _credential_logs}
    for row in rows:
        key = (row.record_id, row.timestamp, row.message)
        if key not in existing_keys:
            _credential_logs.append(CredentialLogEntry(
                record_id=row.record_id,
                timestamp=row.timestamp,
                message=row.message,
            ))


# ── Row ↔ Pydantic converters ─────────────────────────────────────────────────

def _payment_to_row(payment: Payment) -> PaymentRecord:
    row = PaymentRecord(
        id=payment.id,
        intent=payment.intent.model_dump(by_alias=True),
        route_quote=payment.route_quote.model_dump(by_alias=True) if payment.route_quote else None,
        compliance=payment.compliance.model_dump(by_alias=True) if payment.compliance else None,
        policy_decision=payment.policy_decision.model_dump(by_alias=True) if payment.policy_decision else None,
        status=payment.status.value,
        escrow_sequence=payment.escrow_sequence,
        escrow_create_tx_hash=payment.escrow_create_tx_hash,
        approval_signature=payment.approval_signature,
        tx_hash=payment.tx_hash,
        explorer_url=payment.explorer_url,
        explorer_url_secondary=payment.explorer_url_secondary,
        audit_explanation=payment.audit_explanation,
        receipt_hash=payment.receipt_hash,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )
    return row


def _row_to_payment(row: PaymentRecord) -> Payment:
    intent_data = dict(row.intent)
    route_data = row.route_quote
    compliance_data = row.compliance
    policy_data = row.policy_decision

    return Payment(
        id=row.id,
        intent=PaymentIntent(**intent_data),
        route_quote=RouteQuote(**route_data) if route_data else None,
        compliance=ComplianceResult(**compliance_data) if compliance_data else None,
        policy_decision=PolicyDecision(**policy_data) if policy_data else None,
        status=PaymentStatus(row.status),
        escrow_sequence=row.escrow_sequence,
        escrow_create_tx_hash=row.escrow_create_tx_hash,
        approval_signature=row.approval_signature,
        tx_hash=row.tx_hash,
        explorer_url=row.explorer_url,
        explorer_url_secondary=row.explorer_url_secondary,
        audit_explanation=row.audit_explanation,
        receipt_hash=row.receipt_hash,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _credential_to_row(record: CredentialRecord) -> CredentialRecordDB:
    return CredentialRecordDB(
        id=record.id,
        subject=record.subject,
        subject_name=record.subject_name,
        issuer=record.issuer,
        credential_type=record.credential_type,
        uri=record.uri,
        expiration=record.expiration,
        status=record.status.value,
        accepted=record.accepted,
        verified=record.verified,
        refused_reason=record.refused_reason,
        tx_hash=record.tx_hash,
        explorer_url=record.explorer_url,
        accept_tx_hash=record.accept_tx_hash,
        accept_explorer_url=record.accept_explorer_url,
        audit_explanation=record.audit_explanation,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _row_to_credential(row: CredentialRecordDB) -> CredentialRecord:
    return CredentialRecord(
        id=row.id,
        subject=row.subject,
        subject_name=row.subject_name,
        issuer=row.issuer,
        credential_type=row.credential_type,
        uri=row.uri,
        expiration=row.expiration,
        status=CredentialRecordStatus(row.status),
        accepted=row.accepted,
        verified=row.verified,
        refused_reason=row.refused_reason,
        tx_hash=row.tx_hash,
        explorer_url=row.explorer_url,
        accept_tx_hash=row.accept_tx_hash,
        accept_explorer_url=row.accept_explorer_url,
        audit_explanation=row.audit_explanation,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ── ARS spend velocity (G4 / G5) ─────────────────────────────────────────────

# In-memory spend reservations: {agent_address: [(amount: Decimal, idempotency_key: str, status: str, created_at: datetime)]}
_reservations: dict[str, list[dict]] = {}


def reserve_spend(
    agent_address: str,
    idempotency_key: str,
    amount: Decimal,
    currency: str,
    context_kind: str,
) -> bool:
    """Atomically reserve a spend slot under idempotency_key.

    Returns True if the reservation was created, False if the key already exists
    (idempotent replay). The caller must call commit_spend or release_spend after
    the transaction attempt completes.
    """
    import uuid
    bucket = _reservations.setdefault(agent_address, [])
    if any(r["idempotency_key"] == idempotency_key for r in bucket):
        return False
    bucket.append({
        "id": str(uuid.uuid4()),
        "idempotency_key": idempotency_key,
        "amount": amount,
        "currency": currency,
        "context_kind": context_kind,
        "status": "reserved",
        "created_at": datetime.now(timezone.utc),
    })
    _schedule(_persist_reservation(agent_address, idempotency_key, amount, currency, context_kind))
    return True


def commit_spend(agent_address: str, idempotency_key: str) -> None:
    """Mark a reserved spend as committed (transaction landed)."""
    for r in _reservations.get(agent_address, []):
        if r["idempotency_key"] == idempotency_key:
            r["status"] = "committed"
            break


def release_spend(agent_address: str, idempotency_key: str) -> None:
    """Release a reservation on failure so it exits the velocity window."""
    for r in _reservations.get(agent_address, []):
        if r["idempotency_key"] == idempotency_key:
            r["status"] = "released"
            break


def recent_payments_sum(
    agent_address: str,
    since: datetime,
    currency: str,
) -> Decimal:
    """Return the sum of committed + reserved spend amounts for an agent in [since, now).

    Includes both committed (settled) and outstanding reserved amounts so the
    velocity cap is enforced atomically. Released slots are excluded.
    Pure in-memory — the DB is write-behind only. Returns Decimal("0") when no
    spend exists.
    """
    total = Decimal("0")
    for r in _reservations.get(agent_address, []):
        if r["status"] == "released":
            continue
        if r["currency"] != currency:
            continue
        if r["created_at"] < since:
            continue
        total += r["amount"]
    return total


# ── Async persist for spend reservations ──────────────────────────────────────

async def _persist_reservation(
    agent_address: str,
    idempotency_key: str,
    amount: Decimal,
    currency: str,
    context_kind: str,
) -> None:
    if db.session_factory is None:
        return
    import uuid
    try:
        async with db.session_factory() as session:
            row = SpendReservationRecord(
                id=str(uuid.uuid4()),
                agent_address=agent_address,
                idempotency_key=idempotency_key,
                amount=str(amount),
                currency=currency,
                context_kind=context_kind,
                status="reserved",
            )
            session.add(row)
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist spend reservation %s: %s", idempotency_key, exc)


# ── Utility ───────────────────────────────────────────────────────────────────

def _schedule(coro) -> None:
    """Fire-and-forget: schedule a DB persist coroutine if a loop is running.

    In-memory is already updated; this only adds durability. If no loop is
    running (sync test context, or import-time call) we close the coroutine
    cleanly to avoid a ResourceWarning.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(coro)
            return
    except RuntimeError:
        pass
    try:
        coro.close()
    except Exception:
        pass
