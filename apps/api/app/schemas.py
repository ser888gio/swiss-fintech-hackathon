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
    # ARS Insurance (Pillar 3) cover-requirement gate (spec §3). Optional and
    # default-off so existing payloads are unaffected: a counterparty may mandate
    # agent-default cover, conditionally above a USD amount. When required and
    # unbound, the orchestrator auto-binds a premium before settling.
    cover_required: bool = False
    cover_required_above_usd: float | None = None


class QuoteRequest(CamelModel):
    amount: float
    currency: str


class RouteQuote(CamelModel):
    source_amount: float
    dest_amount: float
    rate: float
    path_summary: str
    estimated_fee: float
    # XRPL pathfinding output. Populated from ripple_path_find in real mode; the
    # execution tool attaches these to the Payment. None falls back to the
    # ledger's default path.
    paths: list[list[dict]] | None = None
    # Cap on what the treasury will spend in the source asset (Payment.SendMax).
    send_max: float | None = None
    # Floor the receiver must be delivered when partial payments are allowed
    # (Payment.DeliverMin + tfPartialPayment). None means deliver the exact amount.
    deliver_min: float | None = None


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


class CredentialStatus(CamelModel):
    """Result of an XRPL Credentials (XLS-70) KYC lookup for the receiver.

    `checked` is False when the credential layer is disabled. `verified` is True
    only when the subject holds an *accepted*, non-expired credential of the
    configured type issued by the trusted issuer.
    """

    checked: bool
    verified: bool
    subject: str | None = None
    issuer: str | None = None
    credential_type: str | None = None
    expiration: datetime | None = None
    uri: str | None = None
    reason: str


class CredentialRecordStatus(str, Enum):
    """Lifecycle of a credential issued by the credential-issuing agent.

    issued    -> CredentialCreate submitted; subject has not accepted yet.
    accepted  -> subject ran CredentialAccept; credential is now usable.
    verified  -> a fresh on-ledger lookup confirmed an accepted, valid credential.
    refused   -> deterministic screen blocked issuance (e.g. sanctioned subject).
    failed    -> submission error.
    """

    issued = "issued"
    accepted = "accepted"
    verified = "verified"
    refused = "refused"
    failed = "failed"


class CredentialIssueRequest(CamelModel):
    """Input to the credential-issuing agent.

    `credential_type`/`expiration`/`uri` fall back to configured defaults when
    omitted. `uri` must point to off-chain verifiable-credential data — never PII
    on-ledger. The decision to issue is deterministic (a sanctions screen), never
    the LLM's; the agent only narrates.
    """

    subject: str
    subject_name: str | None = None
    credential_type: str | None = None
    uri: str | None = None
    expiration: datetime | None = None
    note: str | None = None
    # When true, the agent also runs the subject-side CredentialAccept so the
    # credential is immediately usable. Used by the inline KYC gate (mock, or
    # Testnet when CREDENTIAL_SUBJECT_SEED is configured).
    auto_accept: bool = False


class CredentialLogEntry(CamelModel):
    record_id: str
    timestamp: datetime
    message: str


class CredentialRecord(CamelModel):
    """Audit trail for one issued credential, mirroring the payment record shape."""

    id: str
    subject: str
    subject_name: str | None = None
    issuer: str | None = None
    credential_type: str | None = None
    uri: str | None = None
    expiration: datetime | None = None
    status: CredentialRecordStatus
    accepted: bool = False
    verified: bool = False
    refused_reason: str | None = None
    tx_hash: str | None = None
    explorer_url: str | None = None
    accept_tx_hash: str | None = None
    accept_explorer_url: str | None = None
    audit_explanation: str | None = None
    created_at: datetime
    updated_at: datetime


class ComplianceResult(CamelModel):
    aml_score: int  # 0–100
    sanctioned: bool
    flags: list[str]
    explanation: str
    sanctions_matches: list[SanctionsMatch] = Field(default_factory=list)
    public_intel: PublicIntelResult | None = None
    credential: CredentialStatus | None = None


class PolicyDecision(CamelModel):
    requires_approval: bool
    rule_fired: str | None
    reasons: list[str]
    blocked: bool = False
    block_reason: str | None = None


class ApprovalChallenge(CamelModel):
    payment_id: str
    digest: str
    network: str
    owner: str


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
    escrow_create_tx_hash: str | None
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
    escrow_create_tx_hash: str | None = None
    approval_signature: str | None = None
    tx_hash: str | None = None
    explorer_url: str | None = None
    # Second explorer (bithomp) link for cross-checking the same tx hash.
    explorer_url_secondary: str | None = None
    audit_explanation: str | None = None
    receipt_hash: str | None = None
    created_at: datetime
    updated_at: datetime


# ── XLS-65 Single Asset Vault ─────────────────────────────────────────────────

class VaultOpRecord(CamelModel):
    """One vault operation (create / deposit / withdraw) from the audit trail."""

    id: str
    operation: str  # "create" | "deposit" | "withdraw"
    amount: float
    tx_hash: str
    explorer_url: str | None = None
    timestamp: datetime


class VaultStatus(CamelModel):
    """Snapshot of the treasury's vault position and configuration."""

    vault_id: str | None = None
    enabled: bool
    network: str  # "mock" | "devnet" | "testnet"
    deposited: float
    shares: float
    wallet_balance: float
    asset_currency: str
    asset_issuer: str | None = None
    sweep_threshold_usd: float
    recall_threshold_usd: float
    recent_operations: list[VaultOpRecord] = Field(default_factory=list)


class VaultDepositRequest(CamelModel):
    amount: float


class VaultWithdrawRequest(CamelModel):
    amount: float


# ── XLS-33 MPTokens ───────────────────────────────────────────────────────────

class MPTAttestationRecord(CamelModel):
    """One compliance attestation minted as a COMPLY MPToken."""

    id: str
    issuance_id: str
    recipient: str
    payment_id: str
    amount_settled: float
    tx_hash: str
    explorer_url: str | None = None
    timestamp: datetime


class MPTStatus(CamelModel):
    """Snapshot of the COMPLY MPT issuance and attestation audit trail."""

    issuance_id: str | None = None
    enabled: bool
    network: str             # "mock" | "testnet" | "devnet"
    metadata_hex: str        # hex-encoded "COMPLY" metadata
    total_minted: int
    authorized_count: int
    recent_attestations: list[MPTAttestationRecord] = Field(default_factory=list)


class MPTAuthorizeRequest(CamelModel):
    holder: str              # XRPL address to authorize


# ── Autonomous Treasury Agent ──────────────────────────────────────────────────

class TreasuryGoal(CamelModel):
    """A recurring/conditional payment goal for the autonomous treasury agent.

    Trigger: the agent fires this goal every `trigger_interval_hours`. The
    decision is deterministic (time + amount cap); the LLM only narrates.
    The ONLY actuator after trigger is `orchestrator.process_payment`, which
    still runs the full policy gate and Firefly veto for large amounts.
    """

    id: str
    name: str
    enabled: bool = True
    # Payment target
    beneficiary_name: str
    beneficiary_address: str
    beneficiary_country: str
    receiver_entity_type: ReceiverEntityType = ReceiverEntityType.company
    amount: float
    currency: str
    reference: str
    purpose: str
    # Trigger: fire at most once per interval
    trigger_interval_hours: float = 24.0
    last_triggered_at: datetime | None = None


class TreasuryGoalCreate(CamelModel):
    """Request body for creating a treasury goal (id is assigned server-side)."""

    name: str
    enabled: bool = True
    beneficiary_name: str
    beneficiary_address: str
    beneficiary_country: str
    receiver_entity_type: ReceiverEntityType = ReceiverEntityType.company
    amount: float
    currency: str
    reference: str
    purpose: str
    trigger_interval_hours: float = 24.0


class TreasuryAgentRun(CamelModel):
    """Record of one autonomous agent evaluation cycle."""

    id: str
    started_at: datetime
    completed_at: datetime | None = None
    goals_evaluated: int
    goals_triggered: int
    payments_initiated: list[str]  # payment IDs produced by orchestrator
    payments_skipped: list[str]    # goal IDs whose trigger condition was not met
    # Per-goal human-readable decision trail (deterministic; never LLM).
    trigger_log: list[str]
    # LLM narration of the run — explains outcomes, never decides anything.
    narration: str | None = None
    status: str  # "completed" | "error"


# ── ARS Guardrails & Audit (Pillar 5) ─────────────────────────────────────────

class GuardrailResult(CamelModel):
    """Outcome of one guardrail check in the constraint engine evaluation.

    Included in the guardrail_trail on every Payment/ServicePayment/etc. so
    the audit log records exactly which rules passed and which one blocked.
    Money values are str to preserve Decimal precision across JSON.
    """

    name: str               # e.g. "G1_kya", "G4_scope", "G7_hardware_veto"
    passed: bool
    rule_fired: str | None = None
    reason: str | None = None


class ConstraintResult(CamelModel):
    """Full output of the ARS constraint engine for one evaluation."""

    allowed: bool
    action: str             # "allow" | "review" | "block"
    rule_fired: str | None = None
    reasons: list[str] = Field(default_factory=list)
    guardrail_trail: list[GuardrailResult] = Field(default_factory=list)


# ── ARS Scope Policy (G4) ─────────────────────────────────────────────────────

class AgentScopeSchema(CamelModel):
    """Agent spending policy configuration (mirrors policy/scope.AgentScope).

    String fields for monetary values preserve Decimal precision in JSON.
    """

    max_per_transaction: str    # Decimal string, e.g. "500.000000"
    max_per_day: str            # Decimal string
    allowed_service_hosts: list[str] | None = None
    allowed_service_types: list[str] | None = None


class ScopeDecisionSchema(CamelModel):
    """Result of a G4 scope evaluation (mirrors policy/scope.ScopeDecision)."""

    allowed: bool
    rule_fired: str | None = None
    reasons: list[str] = Field(default_factory=list)


# ── ARS Delegation (G5) ───────────────────────────────────────────────────────

class DelegationGrant(CamelModel):
    """A parent agent's grant of a scoped budget to a sub-agent."""

    id: str
    parent_address: str
    child_address: str
    max_total: str              # Decimal string
    max_per_tx: str             # Decimal string
    max_per_day: str            # Decimal string
    currency: str
    allowed_service_hosts: list[str] | None = None
    allowed_service_types: list[str] | None = None
    expires_at: datetime | None = None
    fund_tx_hash: str | None = None
    fund_explorer_url: str | None = None
    revoked: bool = False
    created_at: datetime
    updated_at: datetime


class DelegationGrantCreate(CamelModel):
    parent_address: str
    child_address: str
    max_total: str
    max_per_tx: str
    max_per_day: str
    currency: str = "RLUSD"
    allowed_service_hosts: list[str] | None = None
    allowed_service_types: list[str] | None = None
    expires_at: datetime | None = None


# ── ARS x402 Service Payment ──────────────────────────────────────────────────

class X402PaymentRequirement(CamelModel):
    """Fields extracted from an HTTP 402 challenge response.

    All fields are verified against config allowlists before a Payment is built.
    """

    service_url: str
    facilitator_url: str        # must be in x402_allowed_facilitators
    pay_to: str                 # destination XRPL address
    asset_currency: str         # must match x402_allowed_assets
    asset_issuer: str
    network: str                # must match configured network
    amount: str                 # Decimal string from the challenge
    invoice_id: str             # anti-replay nonce
    expires_at: datetime | None = None


class X402Settlement(CamelModel):
    """Result of a successful x402 payment+proof cycle."""

    invoice_id: str
    tx_hash: str
    explorer_url: str | None = None
    proof_header: str           # X-PAYMENT or equivalent sent on retry
    amount: str                 # Decimal string
    currency: str
    guardrail_trail: list[GuardrailResult] = Field(default_factory=list)
    audit_event_id: str | None = None


class ServicePaymentRecord(CamelModel):
    """Audit record for one x402 service payment."""

    id: str
    service_host: str
    invoice_id: str
    asset_currency: str
    asset_issuer: str
    amount: str                 # Decimal string
    tx_hash: str | None = None
    explorer_url: str | None = None
    guardrail_trail: list[GuardrailResult] = Field(default_factory=list)
    audit_event_id: str | None = None
    created_at: datetime
    updated_at: datetime


# ── ARS Trade Finance / Credit (Pillar 2) ─────────────────────────────────────

class ReceivableStatus(str, Enum):
    registered = "registered"
    funds_reserved = "funds_reserved"
    credit_drawn = "credit_drawn"
    supplier_paid = "supplier_paid"
    awaiting_maturity = "awaiting_maturity"
    repayment_received = "repayment_received"
    credit_settled = "credit_settled"
    closed = "closed"
    needs_recovery = "needs_recovery"


class Receivable(CamelModel):
    """A trade-finance receivable (supplier early-payment)."""

    id: str
    invoice_id: str
    buyer: str
    supplier: str
    amount: str                 # Decimal string — face value
    discount_rate: str          # Decimal string — e.g. "0.020000" = 2%
    due_date: datetime
    status: ReceivableStatus
    draw_tx_hash: str | None = None
    draw_explorer_url: str | None = None
    payment_tx_hash: str | None = None
    payment_explorer_url: str | None = None
    repayment_tx_hash: str | None = None
    settle_tx_hash: str | None = None
    loan_id: str | None = None  # XLS-66 loan sequence if lending_enabled
    guardrail_trail: list[GuardrailResult] = Field(default_factory=list)
    audit_event_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ReceivableCreate(CamelModel):
    invoice_id: str
    buyer: str
    supplier: str
    amount: str         # Decimal string
    discount_rate: str  # Decimal string
    due_date: datetime


# ── ARS Insurance (Pillar 3) ──────────────────────────────────────────────────

class InsurancePremiumRecord(CamelModel):
    """One per-transaction premium payment into the Insurance Vault."""

    id: str
    job_id: str
    agent_address: str
    premium_amount: str         # Decimal string
    currency: str
    tx_hash: str | None = None
    explorer_url: str | None = None
    score_band: str | None = None   # score band that determined the rate
    created_at: datetime


class InsurancePayoutRecord(CamelModel):
    """One insurance payout (slash + pool draw) on agent default."""

    id: str
    job_id: str
    merchant: str
    collateral_slashed: str     # Decimal string — from agent collateral
    pool_drawn: str             # Decimal string — from Insurance Vault first-loss
    total_paid: str             # Decimal string — to merchant
    currency: str
    slash_tx_hash: str | None = None
    pool_draw_tx_hash: str | None = None
    explorer_url: str | None = None         # explorer link for the pool-draw tx
    reputation_mpt_protected: bool = True   # principal score NOT burned on insured default
    created_at: datetime


# ── ARS Insurance — pricing & risk engine (Pillar 3) ──────────────────────────

class CoverLine(str, Enum):
    """The four covered lines (spec §2). Premium is additive across active lines."""

    merchant_default = "merchant_default"
    lender_credit = "lender_credit"
    principal_score = "principal_score"
    mandate_breach = "mandate_breach"


class QuoteDecision(str, Enum):
    OFFER = "OFFER"       # bind via pay_premium
    REVIEW = "REVIEW"     # capacity/risk — escalate
    DECLINE = "DECLINE"   # ineligible


class TxnContext(CamelModel):
    """Transaction-shape inputs to the relative-risk multiplier (spec §5)."""

    category: str = "merchant_payment"
    tenor_band: str = "lt_30d"
    cpty_band: str = "known"
    first_seen: bool = False
    amount_z: float = 0.0
    velocity_z: float = 0.0
    concentration_z: float = 0.0


class InsuranceQuoteRequest(CamelModel):
    """Request a premium quote for one agent transaction."""

    agent_address: str
    amount: str                                  # Decimal string — transaction EAD
    currency: str = "RLUSD"
    score_band: str | None = None
    active_lines: list[CoverLine] = Field(default_factory=lambda: [CoverLine.merchant_default])
    collateral: str = "0"                        # Decimal string — agent collateral
    txn: TxnContext = Field(default_factory=TxnContext)
    job_id: str | None = None


class PremiumQuote(CamelModel):
    """Deterministic, signed quote — reproducible from its inputs (spec §7)."""

    decision: QuoteDecision
    premium: str                                 # Decimal string — total premium
    currency: str = "RLUSD"
    lines: dict[str, str] = Field(default_factory=dict)   # per-line premium, Decimal strings
    pd: float = 0.0                              # probability of default used
    credibility: float = 0.0                     # Z ∈ [0, 1]
    score_band: str | None = None
    reason: str | None = None                    # why REVIEW / DECLINE
    receipt_hash: str                            # canonical hash anchored in the bind Memo


class BindRequest(CamelModel):
    """Bind (pay) a premium for a transaction. Re-quotes server-side first."""

    agent_address: str
    job_id: str
    amount: str                                  # Decimal string
    currency: str = "RLUSD"
    score_band: str | None = None
    active_lines: list[CoverLine] = Field(default_factory=lambda: [CoverLine.merchant_default])
    collateral: str = "0"
    txn: TxnContext = Field(default_factory=TxnContext)


class ClaimRequest(CamelModel):
    """File a claim on a covered default — triggers the payout waterfall (spec §8)."""

    job_id: str
    agent_address: str
    merchant: str                                # beneficiary
    line: CoverLine = CoverLine.merchant_default
    loss: str                                    # Decimal string — gross loss
    currency: str = "RLUSD"
    collateral: str = "0"                        # Decimal string — recoverable agent collateral


class AgentRiskState(CamelModel):
    """Read-model of an agent's default-propensity posterior (spec §6)."""

    agent_address: str
    score_band: str | None = None
    alpha: float
    beta: float
    pd: float                                    # current posterior-mean default rate
    credibility: float                           # Z ∈ [0, 1]
    updated_at: datetime


class PoolStatus(CamelModel):
    """Insurance Vault capacity summary (first-loss capital + flows)."""

    first_loss: str                              # Decimal string — available capital
    currency: str = "RLUSD"
    premiums_collected: str = "0"                # Decimal string
    payouts_made: str = "0"                      # Decimal string
    capacity_ratio: float = 0.0                  # first_loss / base capital
    vault_balance: str = "0"                     # Decimal string — on-ledger XLS-65 vault balance


# ── ARS Audit Log Event ───────────────────────────────────────────────────────

class AuditEventSchema(CamelModel):
    """Read-model of one Ed25519-signed audit event for API responses."""

    event_id: str
    event_type: str
    actor: str
    context_kind: str
    payload: dict
    timestamp: str
    prior_event_hash: str
    event_hash: str
    signature: str
