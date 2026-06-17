"""Tests for the durable Postgres store layer.

Uses an in-memory SQLite engine (aiosqlite) so no real database is needed.
Proves that:
  - `save` / `load_from_db` round-trips a full Payment correctly.
  - `append_log` / `load_from_db` round-trips AgentLogEntries.
  - `save_credential` / `load_from_db` round-trips CredentialRecords.
  - `append_credential_log` / `load_from_db` round-trips CredentialLogEntries.
  - All load functions are idempotent (calling load_from_db twice doesn't duplicate).
  - Graceful no-op when session_factory is None (in-memory-only mode).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import db, store
from app.models import Base
from app.schemas import (
    AgentLogEntry,
    ComplianceResult,
    CredentialIssueRequest,
    CredentialLogEntry,
    CredentialRecord,
    CredentialRecordStatus,
    Payment,
    PaymentIntent,
    PaymentStatus,
    PolicyDecision,
    PublicIntelResult,
    RouteQuote,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def sqlite_store(monkeypatch):
    """Wire an in-memory SQLite session into db.session_factory and reset in-memory dicts."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "session_factory", factory)

    # Reset in-memory state so tests are isolated.
    store._payments.clear()
    store._logs.clear()
    store._credentials.clear()
    store._credential_logs.clear()

    yield factory

    store._payments.clear()
    store._logs.clear()
    store._credentials.clear()
    store._credential_logs.clear()
    await engine.dispose()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payment(payment_id: str = "pay-001", status: PaymentStatus = PaymentStatus.settled) -> Payment:
    now = _now()
    return Payment(
        id=payment_id,
        intent=PaymentIntent(**{
            "from": "rSender",
            "to": "rReceiver",
            "senderName": "Alice AG",
            "senderCountry": "CH",
            "receiverName": "Bob LLC",
            "receiverCountry": "US",
            "receiverEntityType": "company",
            "purpose": "supplier_payment",
            "amount": 1000.0,
            "currency": "EUR",
            "reference": "INV-001",
        }),
        route_quote=RouteQuote(
            source_amount=1000.0,
            dest_amount=1090.0,
            rate=1.09,
            path_summary="EUR->USD @ 1.09 (direct)",
            estimated_fee=1.09,
            send_max=1095.45,
        ),
        compliance=ComplianceResult(
            aml_score=25,
            sanctioned=False,
            flags=["receiver country is high risk (RU)"],
            explanation="AML score 25/100.",
            sanctions_matches=[],
            public_intel=PublicIntelResult(
                score=0, confidence="not_run", flags=[], sources=[], summary=""
            ),
        ),
        policy_decision=PolicyDecision(
            requires_approval=False,
            rule_fired=None,
            reasons=[],
        ),
        status=status,
        tx_hash="A" * 64,
        explorer_url="https://testnet.xrpl.org/transactions/" + "A" * 64,
        explorer_url_secondary="https://test.bithomp.com/explorer/" + "A" * 64,
        receipt_hash="deadbeef",
        audit_explanation="Auto-settled at EUR→USD 1.09.",
        created_at=now,
        updated_at=now,
    )


def _credential(record_id: str = "cred-001") -> CredentialRecord:
    now = _now()
    return CredentialRecord(
        id=record_id,
        subject="rReceiver",
        subject_name="Bob LLC",
        issuer="rISSUER",
        credential_type="KYC",
        status=CredentialRecordStatus.accepted,
        accepted=True,
        verified=False,
        tx_hash="B" * 64,
        created_at=now,
        updated_at=now,
    )


# ── Payment round-trip ────────────────────────────────────────────────────────

async def test_payment_persist_and_load(sqlite_store):
    payment = _payment()
    store.save(payment)
    # Wait for the background task to complete.
    await _drain()

    store._payments.clear()
    await store.load_from_db()

    loaded = store.get(payment.id)
    assert loaded is not None
    assert loaded.id == payment.id
    assert loaded.status is PaymentStatus.settled
    assert loaded.tx_hash == "A" * 64
    assert loaded.explorer_url_secondary == "https://test.bithomp.com/explorer/" + "A" * 64
    assert loaded.receipt_hash == "deadbeef"
    assert loaded.route_quote is not None
    assert loaded.route_quote.dest_amount == 1090.0
    assert loaded.compliance is not None
    assert loaded.compliance.aml_score == 25
    assert loaded.policy_decision is not None
    assert loaded.policy_decision.requires_approval is False


async def test_payment_update_overwrites_row(sqlite_store):
    payment = _payment()
    store.save(payment)
    await _drain()

    updated = payment.model_copy(update={"status": PaymentStatus.released, "approval_signature": "sig123"})
    store.save(updated)
    await _drain()

    store._payments.clear()
    await store.load_from_db()

    loaded = store.get(payment.id)
    assert loaded.status is PaymentStatus.released
    assert loaded.approval_signature == "sig123"


async def test_load_is_idempotent(sqlite_store):
    store.save(_payment())
    await _drain()
    store._payments.clear()
    await store.load_from_db()
    await store.load_from_db()  # second call must not duplicate
    assert len(store._payments) == 1


# ── Log round-trip ────────────────────────────────────────────────────────────

async def test_log_persist_and_load(sqlite_store):
    entry = AgentLogEntry(payment_id="pay-002", timestamp=_now(), message="Test log message.")
    store.append_log(entry)
    await _drain()

    store._logs.clear()
    await store.load_from_db()

    logs = store.logs_for("pay-002")
    assert len(logs) == 1
    assert logs[0].message == "Test log message."


async def test_log_load_is_idempotent(sqlite_store):
    store.append_log(AgentLogEntry(payment_id="p", timestamp=_now(), message="x"))
    await _drain()
    store._logs.clear()
    await store.load_from_db()
    await store.load_from_db()
    assert len(store.logs_for("p")) == 1


# ── Credential round-trip ─────────────────────────────────────────────────────

async def test_credential_persist_and_load(sqlite_store):
    record = _credential()
    store.save_credential(record)
    await _drain()

    store._credentials.clear()
    await store.load_from_db()

    loaded = store.get_credential(record.id)
    assert loaded is not None
    assert loaded.subject == "rReceiver"
    assert loaded.status is CredentialRecordStatus.accepted
    assert loaded.accepted is True
    assert loaded.tx_hash == "B" * 64


async def test_credential_log_persist_and_load(sqlite_store):
    entry = CredentialLogEntry(record_id="cred-002", timestamp=_now(), message="Cred log.")
    store.append_credential_log(entry)
    await _drain()

    store._credential_logs.clear()
    await store.load_from_db()

    logs = store.credential_logs_for("cred-002")
    assert len(logs) == 1
    assert logs[0].message == "Cred log."


# ── Graceful no-op when DB is not configured ──────────────────────────────────

async def test_no_db_noop(monkeypatch):
    monkeypatch.setattr(db, "session_factory", None)
    payment = _payment("no-db-pay")
    store.save(payment)  # should not raise
    assert store.get("no-db-pay") is not None  # in-memory still works


# ── Helper: drain asyncio task queue ─────────────────────────────────────────

async def _drain():
    """Wait for all pending asyncio tasks (background DB persists) to complete."""
    import asyncio
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
