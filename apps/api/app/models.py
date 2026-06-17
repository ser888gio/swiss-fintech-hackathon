"""SQLAlchemy models for the durable Postgres audit store.

Covers the full decision trail documented in docs/architecture.md:
intent → route → compliance → policy → execution. Every field that
exists on the corresponding Pydantic schema has a DB column here,
so auditors can reconstruct any payment without touching app memory.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PaymentRecord(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    intent: Mapped[dict] = mapped_column(JSON)
    route_quote: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    compliance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    policy_decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, index=True)
    escrow_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # XRPL escrow binding — pins the Firefly approval to one on-chain escrow.
    escrow_create_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    approval_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    explorer_url: Mapped[str | None] = mapped_column(String, nullable=True)
    explorer_url_secondary: Mapped[str | None] = mapped_column(String, nullable=True)
    audit_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class AgentLogRecord(Base):
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("ix_agent_logs_payment_ts", "payment_id", "timestamp"),)


class CredentialRecord(Base):
    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject: Mapped[str] = mapped_column(String, index=True)
    subject_name: Mapped[str | None] = mapped_column(String, nullable=True)
    issuer: Mapped[str | None] = mapped_column(String, nullable=True)
    credential_type: Mapped[str | None] = mapped_column(String, nullable=True)
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, index=True)
    accepted: Mapped[bool] = mapped_column(default=False)
    verified: Mapped[bool] = mapped_column(default=False)
    refused_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    explorer_url: Mapped[str | None] = mapped_column(String, nullable=True)
    accept_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    accept_explorer_url: Mapped[str | None] = mapped_column(String, nullable=True)
    audit_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class CredentialLogRecord(Base):
    __tablename__ = "credential_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("ix_credential_logs_record_ts", "record_id", "timestamp"),)
