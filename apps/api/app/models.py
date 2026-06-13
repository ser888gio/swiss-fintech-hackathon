"""SQLAlchemy model for the Postgres audit store.

Not wired into the routes yet — the demo skeleton uses the in-memory app/store.py.
This is the target schema for persistence; it carries the full decision trail
described in docs/architecture.md. Swap store.py to use this with an async
session when moving off in-memory state.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
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
    approval_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    explorer_url: Mapped[str | None] = mapped_column(String, nullable=True)
    audit_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
