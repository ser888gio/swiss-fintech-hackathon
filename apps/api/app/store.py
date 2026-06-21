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
    AgentSpendReservationRecord,
    AgentLogRecord,
    CredentialLogRecord,
    CredentialRecord as CredentialRecordDB,
    PaymentRecord,
    ServicePaymentRecord as ServicePaymentRecordDB,
    SpendReservationRecord,
)
from .schemas import (
    AgentLogEntry,
    ComplianceResult,
    CredentialLogEntry,
    CredentialRecord,
    CredentialRecordStatus,
    Payment,
    PaymentCoverage,
    PaymentIntent,
    PaymentStatus,
    PolicyDecision,
    PremiumQuote,
    ReceiverEntityType,
    RouteQuote,
    ServicePaymentRecord,
)

log = logging.getLogger(__name__)

# ── In-memory primary store ────────────────────────────────────────────────────
_payments: dict[str, Payment] = {}
_logs: list[AgentLogEntry] = []
_credentials: dict[str, CredentialRecord] = {}
_credential_logs: list[CredentialLogEntry] = []
_service_payments: dict[str, ServicePaymentRecord] = {}


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


def save_service_payment(record: ServicePaymentRecord) -> ServicePaymentRecord:
    _service_payments[record.id] = record
    _schedule(_persist_service_payment(record))
    return record


def update_service_payment(record: ServicePaymentRecord) -> ServicePaymentRecord:
    return save_service_payment(record)


def list_service_payments(agent_id: str | None = None) -> list[ServicePaymentRecord]:
    records = _service_payments.values()
    if agent_id is not None:
        records = (r for r in records if r.agent_id == agent_id)
    return sorted(records, key=lambda r: r.created_at, reverse=True)


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
            await _load_service_payments(session)
            await _load_agent_reservations(session)
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


async def _persist_service_payment(record: ServicePaymentRecord) -> None:
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            row = ServicePaymentRecordDB(
                id=record.id,
                agent_id=record.agent_id,
                status=record.status,
                service_host=record.service_host,
                invoice_id=record.invoice_id,
                asset_currency=record.asset_currency,
                asset_issuer=record.asset_issuer,
                amount=record.amount,
                tx_hash=record.tx_hash,
                explorer_url=record.explorer_url,
                guardrail_trail=[g.model_dump(mode="json", by_alias=True) for g in record.guardrail_trail],
                audit_event_id=record.audit_event_id,
                cover=record.cover.model_dump(mode="json", by_alias=True) if record.cover else None,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            await session.merge(row)
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist service payment %s: %s", record.id, exc)


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


async def _load_service_payments(session) -> None:
    rows = (await session.execute(select(ServicePaymentRecordDB))).scalars().all()
    from .schemas import GuardrailResult
    for row in rows:
        if row.id in _service_payments:
            continue
        _service_payments[row.id] = ServicePaymentRecord(
            id=row.id,
            agent_id=getattr(row, "agent_id", None),
            status=getattr(row, "status", "settled"),
            service_host=row.service_host,
            invoice_id=row.invoice_id,
            asset_currency=row.asset_currency,
            asset_issuer=row.asset_issuer,
            amount=row.amount,
            tx_hash=row.tx_hash,
            explorer_url=row.explorer_url,
            guardrail_trail=[GuardrailResult(**g) for g in (row.guardrail_trail or [])],
            audit_event_id=row.audit_event_id,
            cover=PremiumQuote(**row.cover) if getattr(row, "cover", None) else None,
            created_at=_ensure_utc(row.created_at),
            updated_at=_ensure_utc(row.updated_at),
        )


async def _load_agent_reservations(session) -> None:
    rows = (await session.execute(select(AgentSpendReservationRecord))).scalars().all()
    for row in rows:
        bucket = _agent_reservations.setdefault(row.agent_id, [])
        if any(r["idempotency_key"] == row.idempotency_key for r in bucket):
            continue
        bucket.append({
            "id": row.id,
            "idempotency_key": row.idempotency_key,
            "amount": Decimal(row.amount),
            "currency": row.currency,
            "status": row.status,
            "created_at": _ensure_utc(row.created_at),
        })


# ── Row ↔ Pydantic converters ─────────────────────────────────────────────────

def _payment_to_row(payment: Payment) -> PaymentRecord:
    row = PaymentRecord(
        id=payment.id,
        intent=payment.intent.model_dump(by_alias=True),
        route_quote=payment.route_quote.model_dump(by_alias=True) if payment.route_quote else None,
        compliance=payment.compliance.model_dump(by_alias=True) if payment.compliance else None,
        policy_decision=payment.policy_decision.model_dump(by_alias=True) if payment.policy_decision else None,
        cover=payment.coverage.model_dump(mode="json", by_alias=True),
        status=payment.status.value,
        escrow_sequence=payment.escrow_sequence,
        escrow_create_tx_hash=payment.escrow_create_tx_hash,
        approval_signature=payment.approval_signature,
        tx_hash=payment.tx_hash,
        explorer_url=payment.explorer_url,
        explorer_url_secondary=payment.explorer_url_secondary,
        audit_explanation=payment.audit_explanation,
        receipt_hash=payment.receipt_hash,
        agent_id=payment.agent_id,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )
    return row


def _row_to_payment(row: PaymentRecord) -> Payment:
    intent_data = dict(row.intent)
    route_data = row.route_quote
    compliance_data = row.compliance
    policy_data = row.policy_decision
    coverage_data = row.cover
    # Backward compatibility for rows written before coverage status and the
    # bound premium were persisted together in the existing JSON column.
    if coverage_data and "status" not in coverage_data:
        coverage_data = {
            "status": "bound",
            "requiredBy": "legacy",
            "quote": coverage_data,
            "premium": None,
            "reason": "Legacy quote record; premium evidence was not persisted.",
        }

    return Payment(
        id=row.id,
        intent=PaymentIntent(**intent_data),
        route_quote=RouteQuote(**route_data) if route_data else None,
        compliance=ComplianceResult(**compliance_data) if compliance_data else None,
        policy_decision=PolicyDecision(**policy_data) if policy_data else None,
        coverage=PaymentCoverage(**coverage_data) if coverage_data else PaymentCoverage(),
        status=PaymentStatus(row.status),
        escrow_sequence=row.escrow_sequence,
        escrow_create_tx_hash=row.escrow_create_tx_hash,
        approval_signature=row.approval_signature,
        tx_hash=row.tx_hash,
        explorer_url=row.explorer_url,
        explorer_url_secondary=row.explorer_url_secondary,
        audit_explanation=row.audit_explanation,
        receipt_hash=row.receipt_hash,
        agent_id=getattr(row, "agent_id", None),
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
    )


def _credential_to_row(record: CredentialRecord) -> CredentialRecordDB:
    return CredentialRecordDB(
        id=record.id,
        user_id=record.user_id,
        subject=record.subject,
        subject_name=record.subject_name,
        subject_country=record.subject_country,
        subject_entity_type=(record.subject_entity_type.value if record.subject_entity_type else None),
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
        user_id=getattr(row, "user_id", None),
        subject=row.subject,
        subject_name=row.subject_name,
        subject_country=getattr(row, "subject_country", None),
        subject_entity_type=getattr(row, "subject_entity_type", None),
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


# ── Agent-id–keyed spend tracking (business-defined agents) ──────────────────
# Separate from the wallet-address–keyed reservations above so per-agent
# daily caps are isolated even when agents share the treasury wallet.

_agent_reservations: dict[str, list[dict]] = {}


def reserve_agent_spend(
    agent_id: str,
    idempotency_key: str,
    amount: Decimal,
    currency: str,
) -> bool:
    """Reserve a spend slot for a business agent (idempotent).

    Returns True if a new slot was created, False if the key already exists.
    Caller calls commit_agent_spend or release_agent_spend after the attempt.
    """
    import uuid
    bucket = _agent_reservations.setdefault(agent_id, [])
    if any(r["idempotency_key"] == idempotency_key for r in bucket):
        return False
    reservation_id = str(uuid.uuid4())
    bucket.append({
        "id": reservation_id,
        "idempotency_key": idempotency_key,
        "amount": amount,
        "currency": currency,
        "status": "reserved",
        "created_at": datetime.now(timezone.utc),
    })
    _schedule(_persist_agent_reservation(
        reservation_id, agent_id, idempotency_key, amount, currency, "reserved"
    ))
    return True


def commit_agent_spend(agent_id: str, idempotency_key: str) -> None:
    for r in _agent_reservations.get(agent_id, []):
        if r["idempotency_key"] == idempotency_key:
            r["status"] = "committed"
            _schedule(_update_agent_reservation_status(agent_id, idempotency_key, "committed"))
            break


def release_agent_spend(agent_id: str, idempotency_key: str) -> None:
    for r in _agent_reservations.get(agent_id, []):
        if r["idempotency_key"] == idempotency_key:
            r["status"] = "released"
            _schedule(_update_agent_reservation_status(agent_id, idempotency_key, "released"))
            break


def agent_payments_sum(
    agent_id: str,
    since: datetime,
    currency: str,
) -> Decimal:
    """Committed + reserved spend for an agent in [since, now). Excludes released."""
    total = Decimal("0")
    for r in _agent_reservations.get(agent_id, []):
        if r["status"] == "released":
            continue
        if r["currency"] != currency:
            continue
        if r["created_at"] < since:
            continue
        total += r["amount"]
    return total


async def _persist_agent_reservation(
    reservation_id: str,
    agent_id: str,
    idempotency_key: str,
    amount: Decimal,
    currency: str,
    status: str,
) -> None:
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            await session.merge(AgentSpendReservationRecord(
                id=reservation_id,
                agent_id=agent_id,
                idempotency_key=idempotency_key,
                amount=str(amount),
                currency=currency,
                status=status,
            ))
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist agent reservation %s: %s", idempotency_key, exc)


async def _update_agent_reservation_status(
    agent_id: str, idempotency_key: str, status: str
) -> None:
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            row = (await session.execute(
                select(AgentSpendReservationRecord).where(
                    AgentSpendReservationRecord.agent_id == agent_id,
                    AgentSpendReservationRecord.idempotency_key == idempotency_key,
                )
            )).scalar_one_or_none()
            if row:
                row.status = status
                await session.commit()
    except Exception as exc:
        log.warning("Failed to update agent reservation %s: %s", idempotency_key, exc)


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


def _ensure_utc(value: datetime) -> datetime:
    """Normalize timestamps from SQLite (naive) and Postgres (aware)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
