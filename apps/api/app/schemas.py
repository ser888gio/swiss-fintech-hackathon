"""Pydantic schemas. Mirror packages/shared/src/types.ts — keep in sync by hand."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PaymentStatus(str, Enum):
    routing = "routing"
    settled = "settled"
    pending_approval = "pending_approval"
    released = "released"
    failed = "failed"


class PaymentIntent(BaseModel):
    from_account: str = Field(alias="from")
    to: str
    amount: float
    currency: str
    reference: str

    model_config = {"populate_by_name": True}


class RouteQuote(BaseModel):
    source_amount: float
    dest_amount: float
    rate: float
    path_summary: str
    estimated_fee: float


class ComplianceResult(BaseModel):
    aml_score: int  # 0–100
    sanctioned: bool
    flags: list[str]
    explanation: str


class PolicyDecision(BaseModel):
    requires_approval: bool
    rule_fired: str | None
    reasons: list[str]


class ApprovalChallenge(BaseModel):
    payment_id: str
    digest: str


class ReleaseRequest(BaseModel):
    signature: str  # hex secp256k1 signature from the Firefly


class ExecutionResult(BaseModel):
    tx_hash: str
    explorer_url: str
    status: PaymentStatus


class AgentLogEntry(BaseModel):
    payment_id: str
    timestamp: datetime
    message: str


class Payment(BaseModel):
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
    created_at: datetime
    updated_at: datetime
