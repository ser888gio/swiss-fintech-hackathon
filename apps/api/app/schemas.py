"""Pydantic schemas. Mirror packages/shared/src/types.ts — keep in sync by hand."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PaymentStatus(str, Enum):
    routing = "routing"
    settled = "settled"
    pending_approval = "pending_approval"
    released = "released"
    blocked = "blocked"
    failed = "failed"


class ReceiverEntityType(str, Enum):
    company = "company"
    individual = "individual"


class PaymentIntent(CamelModel):
    from_account: str = Field(alias="from")
    to: str
    sender_name: str
    sender_country: str
    receiver_name: str
    receiver_country: str
    receiver_entity_type: ReceiverEntityType
    purpose: str
    amount: float
    currency: str
    reference: str


class QuoteRequest(CamelModel):
    amount: float
    currency: str


class RouteQuote(CamelModel):
    source_amount: float
    dest_amount: float
    rate: float
    path_summary: str
    estimated_fee: float


class SanctionsMatch(CamelModel):
    id: str
    caption: str
    schema_: str = Field(alias="schema")
    score: float
    datasets: list[str]
    url: str | None = None


class PublicIntelResult(CamelModel):
    score: int
    confidence: str
    flags: list[str]
    sources: list[str]
    summary: str


class ComplianceResult(CamelModel):
    aml_score: int  # 0–100
    sanctioned: bool
    flags: list[str]
    explanation: str
    sanctions_matches: list[SanctionsMatch] = Field(default_factory=list)
    public_intel: PublicIntelResult | None = None


class PolicyDecision(CamelModel):
    requires_approval: bool
    rule_fired: str | None
    reasons: list[str]
    blocked: bool = False
    block_reason: str | None = None


class ApprovalChallenge(CamelModel):
    payment_id: str
    digest: str


class ReleaseRequest(BaseModel):
    signature: str  # hex secp256k1 signature from the Firefly


class ExecutionResult(CamelModel):
    tx_hash: str
    explorer_url: str | None
    status: PaymentStatus


class AgentLogEntry(CamelModel):
    payment_id: str
    timestamp: datetime
    message: str


class Receipt(CamelModel):
    payment_id: str
    intent: PaymentIntent
    route_quote: RouteQuote | None
    compliance: ComplianceResult | None
    policy_decision: PolicyDecision | None
    status: PaymentStatus
    escrow_sequence: int | None
    approval_signature: str | None
    tx_hash: str | None
    explorer_url: str | None
    audit_explanation: str | None
    created_at: datetime
    updated_at: datetime


class Payment(CamelModel):
    id: str
    intent: PaymentIntent
    route_quote: RouteQuote | None = None
    compliance: ComplianceResult | None = None
    policy_decision: PolicyDecision | None = None
    status: PaymentStatus
    escrow_sequence: int | None = None
    approval_signature: str | None = None
    tx_hash: str | None = None
    explorer_url: str | None = None
    audit_explanation: str | None = None
    receipt_hash: str | None = None
    created_at: datetime
    updated_at: datetime
