"""SQLAlchemy models for the durable Postgres audit store.

Covers the full decision trail documented in docs/architecture.md:
intent → route → compliance → policy → execution. Every field that
exists on the corresponding Pydantic schema has a DB column here,
so auditors can reconstruct any payment without touching app memory.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
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
    cover: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
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


# ── ARS: Atomic spend reservation (invariant 2) ───────────────────────────────

class SpendReservationRecord(Base):
    """Per-agent spend reservation for atomic velocity enforcement.

    Before settling any payment the orchestrator inserts a row here under a
    unique constraint on (agent_address, idempotency_key). The velocity sum used
    by evaluate_scope includes committed + reserved rows. On success the status
    is set to 'committed'; on failure/timeout it is set to 'released' so the
    reserved amount falls out of the velocity window.

    Amounts stored as strings to preserve Decimal precision.
    """

    __tablename__ = "spend_reservations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_address: Mapped[str] = mapped_column(String, index=True)
    idempotency_key: Mapped[str] = mapped_column(String)    # InvoiceID or payment_id
    amount: Mapped[str] = mapped_column(String)             # Decimal string
    currency: Mapped[str] = mapped_column(String)
    context_kind: Mapped[str] = mapped_column(String)       # "payment" | "loan" | ...
    status: Mapped[str] = mapped_column(String, index=True) # "reserved" | "committed" | "released"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_address", "idempotency_key", name="uq_spend_reservation"),
        Index("ix_spend_reservations_agent_status", "agent_address", "status"),
    )


# ── ARS: Ed25519 audit event log (Pillar 5) ───────────────────────────────────

class AuditEventRecord(Base):
    """Persisted ARS audit event (append-only; never updated after insert)."""

    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String)
    context_kind: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    timestamp: Mapped[str] = mapped_column(String)          # ISO 8601 UTC
    prior_event_hash: Mapped[str] = mapped_column(String)
    event_hash: Mapped[str] = mapped_column(String, unique=True)
    signature: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ── ARS: x402 service payment (Pillar 3 / ARS regulated settlement) ──────────

class ServicePaymentRecord(Base):
    """Audit record for one x402 service payment."""

    __tablename__ = "service_payments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    service_host: Mapped[str] = mapped_column(String, index=True)
    invoice_id: Mapped[str] = mapped_column(String, unique=True)    # anti-replay
    asset_currency: Mapped[str] = mapped_column(String)
    asset_issuer: Mapped[str] = mapped_column(String)
    amount: Mapped[str] = mapped_column(String)                     # Decimal string
    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    explorer_url: Mapped[str | None] = mapped_column(String, nullable=True)
    guardrail_trail: Mapped[list | None] = mapped_column(JSON, nullable=True)
    audit_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── ARS: Delegation grants (Pillar 1 / G5) ───────────────────────────────────

class DelegationGrantRecord(Base):
    """A parent agent's budget grant to a sub-agent wallet."""

    __tablename__ = "delegation_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_address: Mapped[str] = mapped_column(String, index=True)
    child_address: Mapped[str] = mapped_column(String, index=True)
    max_total: Mapped[str] = mapped_column(String)          # Decimal string
    max_per_tx: Mapped[str] = mapped_column(String)
    max_per_day: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String)
    allowed_service_hosts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    allowed_service_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fund_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    fund_explorer_url: Mapped[str | None] = mapped_column(String, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── ARS: Trade-finance receivable state machine (Pillar 2) ───────────────────

class ReceivableRecord(Base):
    """A trade-finance receivable progressing through the early-payment lifecycle."""

    __tablename__ = "receivables"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    buyer: Mapped[str] = mapped_column(String, index=True)
    supplier: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[str] = mapped_column(String)             # Decimal string — face value
    discount_rate: Mapped[str] = mapped_column(String)      # Decimal string
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String, index=True) # ReceivableStatus enum value
    # Credit draw (LoanCreate or VaultWithdraw)
    draw_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    draw_explorer_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Supplier payment
    payment_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    payment_explorer_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Buyer repayment
    repayment_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    # Credit settlement (LoanRepay or VaultDeposit)
    settle_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    loan_id: Mapped[str | None] = mapped_column(String, nullable=True)  # XLS-66 loan seq
    guardrail_trail: Mapped[list | None] = mapped_column(JSON, nullable=True)
    audit_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── ARS: Insurance records (Pillar 3) ─────────────────────────────────────────

class InsurancePremiumRecord(Base):
    """One per-transaction premium payment into the Insurance Vault."""

    __tablename__ = "insurance_premiums"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    agent_address: Mapped[str] = mapped_column(String, index=True)
    premium_amount: Mapped[str] = mapped_column(String)     # Decimal string
    currency: Mapped[str] = mapped_column(String)
    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    explorer_url: Mapped[str | None] = mapped_column(String, nullable=True)
    score_band: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class InsurancePayoutRecord(Base):
    """One insurance payout (slash + pool draw) on agent default."""

    __tablename__ = "insurance_payouts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    merchant: Mapped[str] = mapped_column(String, index=True)
    collateral_slashed: Mapped[str] = mapped_column(String)     # Decimal string
    pool_drawn: Mapped[str] = mapped_column(String)
    total_paid: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String)
    slash_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    pool_draw_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    reputation_mpt_protected: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentRiskRecord(Base):
    __tablename__ = "agent_risks"

    agent_address: Mapped[str] = mapped_column(String, primary_key=True)
    score_band: Mapped[str] = mapped_column(String, index=True)
    alpha: Mapped[float] = mapped_column(Float)
    beta: Mapped[float] = mapped_column(Float)
    pd: Mapped[float] = mapped_column(Float)
    credibility: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── Business-defined payment agents ──────────────────────────────────────────

class AgentRecord(Base):
    """Business-defined payment agent with per-agent policy guardrails."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True)   # slug e.g. "supplier-bot"
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, index=True, default="active")
    currency: Mapped[str] = mapped_column(String, default="RLUSD")
    max_single_payment: Mapped[str] = mapped_column(String)      # Decimal string
    max_daily_spend: Mapped[str] = mapped_column(String)         # Decimal string
    requires_approval_above: Mapped[str] = mapped_column(String) # Decimal string
    allowed_categories: Mapped[list | None] = mapped_column(JSON, nullable=True)
    allowed_assets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    allowed_network: Mapped[str] = mapped_column(String, default="XRPL")
    allowed_addresses: Mapped[list | None] = mapped_column(JSON, nullable=True)
    blocked_addresses: Mapped[list | None] = mapped_column(JSON, nullable=True)
    allowed_hosts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    blocked_hosts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    require_known_merchant: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
