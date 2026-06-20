"""Pydantic schemas. Mirror packages/shared/src/types.ts — keep in sync by hand."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WalletBalance(CamelModel):
    currency: str
    value: str
    issuer: str | None = None


class WalletTransaction(CamelModel):
    hash: str
    transaction_type: str
    direction: str
    counterparty: str | None = None
    amount: WalletBalance | None = None
    fee_xrp: str | None = None
    result: str | None = None
    ledger_index: int | None = None
    timestamp: datetime | None = None
    explorer_url: str


class WalletNetworkSnapshot(CamelModel):
    network: str
    active: bool
    xrp_balance: str
    token_balances: list[WalletBalance]
    owner_count: int | None = None
    sequence: int | None = None
    ledger_index: int | None = None
    transactions: list[WalletTransaction]
    account_explorer_url: str
    error: str | None = None


class WalletOverview(CamelModel):
    address: str
    fetched_at: datetime
    networks: list[WalletNetworkSnapshot]


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
    cover_required: bool = False
    cover_required_above_usd: float | None = None
    # Ground truth for deterministic hallucination reconciliation (Cover module).
    expected_amount: float | None = None
    expected_recipient: str | None = None


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


class GeopoliticalRiskResult(CamelModel):
    """Deterministic country-policy evidence; never an LLM judgement."""

    country: str
    risk_level: str
    score: int
    blocked: bool
    requires_review: bool
    reasons: list[str]
    sources: list[str]
    summary: str = ""


class VerificationStepStatus(str, Enum):
    """Outcome of a single KYC verification step — mirrors Plaid IDV step statuses."""
    pass_   = "pass"
    fail    = "fail"
    flagged = "flagged"   # issue found (e.g. PEP match, adverse media)
    skip    = "skip"      # step not performed
    pending = "pending"


class VerificationSteps(CamelModel):
    """Per-step KYC outcomes encoded in the XRPL Credential URI field.

    Models the same verification steps as Plaid IDV + Plaid Monitor:
      documentary  →  government ID scanned and authenticated
      selfie       →  liveness confirmed, face matches ID
      kyc          →  name / DOB cross-referenced against records
      sanctions    →  screened against OFAC / EU / UN lists
      pep          →  politically exposed person check
    """
    documentary: VerificationStepStatus = VerificationStepStatus.skip
    selfie: VerificationStepStatus      = VerificationStepStatus.skip
    kyc: VerificationStepStatus         = VerificationStepStatus.skip
    sanctions: VerificationStepStatus   = VerificationStepStatus.skip
    pep: VerificationStepStatus         = VerificationStepStatus.skip
    ref: str = ""
    issued_on: str = ""


class CredentialStatus(CamelModel):
    """Result of an XRPL Credentials (XLS-70) KYC lookup for the receiver.

    `checked` is False when the credential layer is disabled. `verified` is True
    only when the subject holds an *accepted*, non-expired credential of the
    configured type issued by the trusted issuer.

    `verification_steps` is decoded from the credential URI field when present.
    It carries per-step outcomes (documentary, selfie, sanctions, PEP) modelled
    on Plaid IDV's step schema — giving compliance granular signal beyond a
    binary verified/unverified flag.
    """

    checked: bool
    verified: bool
    subject: str | None = None
    issuer: str | None = None
    credential_type: str | None = None
    expiration: datetime | None = None
    uri: str | None = None
    reason: str
    verification_steps: VerificationSteps | None = None


# ── KYA (Know Your Agent) schemas ────────────────────────────────────────────

class AgentIdentityStatus(CamelModel):
    """Result of a KYA credential lookup for an AI agent wallet.

    Parallels CredentialStatus (KYC) but targets agent wallets. `verified` is
    True only when the agent holds an accepted, non-expired KYA credential from
    the trusted issuer. `scope_ok` indicates whether the agent's declared scopes
    cover the requested action.
    """

    checked: bool
    verified: bool
    agent_address: str | None = None
    issuer: str | None = None
    credential_type: str | None = None
    # Decoded agent identity from the credential URI field.
    agent_type: str | None = None
    principal: str | None = None
    scopes: list[str] = Field(default_factory=list)
    issued_on: str | None = None
    ref: str | None = None
    scope_ok: bool = True
    scope_reason: str = ""
    reason: str


class AgentScopeStatus(CamelModel):
    """Whether a specific scope is authorized for this agent (used in API responses)."""

    scope: str
    authorized: bool
    reason: str = ""


class KYAIssueRequest(CamelModel):
    """Request to issue a KYA credential to an AI agent wallet."""

    agent_address: str
    agent_type: str = "orchestrator"   # orchestrator | sub_agent | monitor | api_gateway
    principal: str = ""                # controlling XRPL address
    scopes: list[str] = Field(default_factory=list)
    ref: str = ""
    credential_type: str = "KYA"


class KYAIssueResponse(CamelModel):
    """Response from the KYA credential issuance endpoint."""

    agent_address: str
    issuer: str | None = None
    credential_type: str
    uri: str
    identity: dict
    mock: bool = False
    status: str


class KYAVerifyResponse(CamelModel):
    """Response from the KYA credential verification endpoint."""

    agent_address: str
    verified: bool
    agent_type: str | None = None
    principal: str | None = None
    scopes: list[str] = Field(default_factory=list)
    scope_ok: bool = True
    scope_reason: str = ""
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
    sanctions_basis: list[str] = Field(default_factory=list)
    geopolitical_risk: GeopoliticalRiskResult | None = None
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
    guardrail_trail: list[GuardrailResult] = Field(default_factory=list)
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
    cover: PremiumQuote | None = None
    agent_id: str | None = None    # set when initiated by a business agent
    guardrail_trail: list[GuardrailResult] = Field(default_factory=list)
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


# ── Business-defined payment agents ───────────────────────────────────────────

class AgentStatus(str, Enum):
    active = "active"
    paused = "paused"


class AgentCreate(CamelModel):
    """Request body for creating a business-defined payment agent."""

    id: str                                            # slug e.g. "supplier-bot"
    name: str
    description: str | None = None                     # free-text context for this agent
    max_single_payment: str                            # Decimal string
    max_daily_spend: str                               # Decimal string
    requires_approval_above: str                       # Decimal string, ≤ max_single_payment
    currency: str = "RLUSD"
    allowed_categories: list[str] | None = None        # None=any, []=deny-all
    allowed_assets: list[str] = Field(default_factory=lambda: ["RLUSD"])
    allowed_network: str = "xrpl:1"
    allowed_addresses: list[str] | None = None         # None=any, []=deny-all
    blocked_addresses: list[str] = Field(default_factory=list)
    allowed_hosts: list[str] | None = None
    blocked_hosts: list[str] = Field(default_factory=list)
    require_known_merchant: bool = False


class Agent(AgentCreate):
    """A persisted business-defined payment agent."""

    status: AgentStatus = AgentStatus.active
    policy_revision: int = 1
    created_at: datetime
    updated_at: datetime


class AgentUpdate(CamelModel):
    """Partial update — only provided fields are changed; policy_revision auto-increments."""

    name: str | None = None
    description: str | None = None
    status: AgentStatus | None = None
    max_single_payment: str | None = None
    max_daily_spend: str | None = None
    requires_approval_above: str | None = None
    currency: str | None = None
    allowed_categories: list[str] | None = None
    allowed_assets: list[str] | None = None
    allowed_network: str | None = None
    allowed_addresses: list[str] | None = None
    blocked_addresses: list[str] | None = None
    allowed_hosts: list[str] | None = None
    blocked_hosts: list[str] | None = None
    require_known_merchant: bool | None = None


class AgentDashboardStats(CamelModel):
    """Per-agent mini dashboard snapshot."""

    agent_id: str
    payments_today: int
    amount_spent_today: str           # Decimal string (USD)
    pending_approvals: int
    last_run_at: datetime | None
    last_run_status: str | None
    total_payments: int
    total_blocked: int
    total_escalated: int


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
    agent_id: str | None = None   # set for goals owned by a business agent
    service_url: str | None = None
    service_type: str | None = None
    category: str | None = None


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
    service_url: str | None = None
    service_type: str | None = None
    category: str | None = None


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
    agent_id: str | None = None


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
    source_tag: int | None = None
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
    agent_id: str | None = None


class ServicePaymentRecord(CamelModel):
    """Audit record for one x402 service payment."""

    id: str
    agent_id: str | None = None
    status: str = "settled"       # "settled" | "blocked"
    service_host: str
    invoice_id: str
    asset_currency: str
    asset_issuer: str
    amount: str                 # Decimal string
    tx_hash: str | None = None
    explorer_url: str | None = None
    guardrail_trail: list[GuardrailResult] = Field(default_factory=list)
    audit_event_id: str | None = None
    cover: PremiumQuote | None = None
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
    guardrail_trail: list[GuardrailResult] = Field(default_factory=list)
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
    explorer_url: str | None = None         # on-ledger explorer link for the pool draw
    reputation_mpt_protected: bool = True   # principal score NOT burned on insured default
    guardrail_trail: list[GuardrailResult] = Field(default_factory=list)
    created_at: datetime


class CoverLine(str, Enum):
    merchant_default = "merchant_default"
    lender_credit = "lender_credit"
    principal_score = "principal_score"
    mandate_breach = "mandate_breach"


class QuoteDecision(str, Enum):
    offer = "OFFER"
    review = "REVIEW"
    decline = "DECLINE"


class TxnContext(CamelModel):
    category: str
    tenor_band: str
    cpty_band: str
    first_seen: bool = False
    amount: str
    amount_z: float = 0.0
    velocity_z: float = 0.0
    concentration_z: float = 0.0
    active_lines: list[CoverLine] = Field(default_factory=list)


class AgentRiskState(CamelModel):
    agent_address: str
    score_band: str
    alpha: float
    beta: float
    pd: float
    credibility: float
    updated_at: datetime


class PremiumQuote(CamelModel):
    decision: QuoteDecision
    premium: str
    lines: dict[str, str] = Field(default_factory=dict)
    pd: float
    credibility: float
    reason: str
    receipt_hash: str


class InsuranceQuoteRequest(CamelModel):
    agent_address: str
    score_band: str = "STANDARD"
    txn_context: TxnContext


class BindRequest(CamelModel):
    job_id: str
    agent_address: str
    score_band: str = "STANDARD"
    currency: str = "USD"
    quote: PremiumQuote


class ClaimRequest(CamelModel):
    job_id: str
    agent_address: str
    merchant: str
    merchant_name: str | None = None
    merchant_country: str = "CH"
    score_band: str = "STANDARD"
    currency: str = "USD"
    claim_amount: str
    collateral_available: str = "0.000000"
    aml_score: int = 0
    sanctioned: bool = False
    receipt_hash: str | None = None


class PoolStatus(CamelModel):
    """Insurance Vault capacity summary (first-loss capital + flows)."""

    first_loss: str                              # Decimal string — available capital
    currency: str = "RLUSD"
    premiums_collected: str = "0"                # Decimal string
    payouts_made: str = "0"                      # Decimal string
    capacity_ratio: float = 0.0                  # first_loss / base capital
    vault_balance: str = "0"                     # Decimal string — on-ledger XLS-65 vault balance
    lp_capital: str = "0"                        # Decimal string — total LP-provided capital


# ── ARS Insurance — Capital Provider (LP) ─────────────────────────────────────

class CapitalDepositRequest(CamelModel):
    """An LP contributes first-loss capital to the Insurance pool."""

    lp_address: str
    amount: str                                  # Decimal string
    currency: str = "RLUSD"


class CapitalWithdrawRequest(CamelModel):
    lp_address: str
    amount: str                                  # Decimal string


class LpPosition(CamelModel):
    """An LP's share of the first-loss pool."""

    lp_address: str
    capital: str                                 # Decimal string — capital contributed
    share_pct: float                             # pro-rata share of LP capital
    currency: str = "RLUSD"
    tx_hash: str | None = None
    explorer_url: str | None = None
    guardrail_trail: list[GuardrailResult] = Field(default_factory=list)
    updated_at: datetime


# ── Agent Cover (annual policy — hallucination + non-delivery) ────────────────

class CoverLineKind(str, Enum):
    hallucination = "hallucination"
    non_delivery = "non_delivery"


class CoverPolicyStatus(str, Enum):
    active = "active"
    expired = "expired"
    exhausted = "exhausted"
    cancelled = "cancelled"


class CoverLossBearerKind(str, Enum):
    merchant = "merchant"
    treasury = "treasury"


class CoverQuoteRequest(CamelModel):
    agent_address: str
    score_band: str = "STANDARD"
    cover_cap: str                      # Decimal string — max pool payout over the period
    per_claim_limit: str                # Decimal string — max payout per single claim
    term_days: int = 365
    lines: list[CoverLineKind] = Field(default_factory=lambda: [CoverLineKind.hallucination])


class CoverQuote(CamelModel):
    decision: str                       # "OFFER" | "REVIEW" | "DECLINE"
    premium: str                        # Decimal string — prorated premium (not always annual)
    line_rates: dict[str, str]          # line → annual rate e.g. {"hallucination": "0.030000"}
    pd: float
    credibility: float
    score_band: str
    cover_cap: str
    per_claim_limit: str
    term_days: int
    reason: str | None = None
    receipt_hash: str


class CoverBindRequest(CamelModel):
    agent_address: str
    score_band: str = "STANDARD"
    cover_cap: str                      # Decimal string — must match quote
    per_claim_limit: str                # Decimal string — must match quote
    term_days: int = 365
    lines: list[CoverLineKind] = Field(default_factory=lambda: [CoverLineKind.hallucination])
    quote: CoverQuote


class CoverPolicy(CamelModel):
    id: str
    agent_address: str
    period_start: datetime
    period_end: datetime
    lines: list[CoverLineKind]
    cover_cap: str                      # Decimal string — total pool capacity for this policy
    per_claim_limit: str                # Decimal string
    premium: str                        # Decimal string — what was paid
    cover_used: str                     # Decimal string — cumulative payouts
    cover_remaining: str                # Decimal string — cover_cap - cover_used
    score_band: str
    status: CoverPolicyStatus
    premium_tx_hash: str | None = None
    explorer_url: str | None = None
    created_at: datetime
    updated_at: datetime


class CoverClaimEvidence(CamelModel):
    """Evidence submitted by the caller. All financial data derived server-side
    from the immutable settled payment record — never trusted from the client."""

    policy_id: str
    payment_id: str                     # must be a settled payment in the store


class CoverDemoUnderpaymentRequest(CamelModel):
    invoice_amount: Decimal = Field(default=Decimal("500"), gt=0)
    paid_amount: Decimal = Field(default=Decimal("480"), gt=0)


class CoverPayout(CamelModel):
    id: str
    policy_id: str
    payment_id: str
    line: CoverLineKind
    loss_bearer: CoverLossBearerKind
    destination: str                    # XRPL address that received the payout
    amount_paid: str                    # Decimal string
    pool_drawn: str                     # Decimal string
    classification: str                 # "underpayment" | "wrong_recipient"
    narration: str | None = None
    guardrail_trail: list[GuardrailResult] = Field(default_factory=list)
    tx_hash: str | None = None
    explorer_url: str | None = None
    receipt_hash: str
    created_at: datetime


class CoverPoolStatus(CamelModel):
    first_loss: str                     # Decimal string — available first-loss capital
    reserved: str                       # Decimal string — capacity reserved by active policies
    free_capacity: str                  # first_loss - reserved
    currency: str
    premiums_collected: str
    claims_paid: str
    capacity_ratio: float               # free_capacity / first_loss
    policies_active: int
    cover_in_force: str                 # sum of active cover_caps


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


# ── Treasury summary (aggregated position for the operator dashboard) ─────────

class TreasurySummary(CamelModel):
    """Blended treasury position in USD for the operator dashboard hero row."""
    total_usd: str            # stableUsd + xrpUsd + vaultUsd (Decimal string)
    stable_usd: str           # sum of RLUSD/USD token balances at 1:1 (Decimal string)
    xrp_native: str           # raw XRP balance across active networks (Decimal string)
    xrp_usd: str              # XRP converted to USD via live rate / fallback (Decimal string)
    vault_usd: str            # XLS-65 vault wallet balance if RLUSD (Decimal string)
    reserved_usd: str         # sum of intent.amount for pending_approval payments (Decimal string)
    networks: list[str]       # active network labels
    fetched_at: datetime
