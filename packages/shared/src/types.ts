// Shared types for the web dashboard and the Firefly bridge.
// Mirrored by apps/api/app/schemas.py (Pydantic) — keep the two in sync by hand.

export interface TreasurySummary {
  totalUsd: string;      // blended USD total (stableUsd + xrpUsd + vaultUsd)
  stableUsd: string;     // RLUSD/USD token holdings at 1:1
  xrpNative: string;     // raw XRP balance
  xrpUsd: string;        // XRP converted to USD
  vaultUsd: string;      // XLS-65 vault wallet balance
  reservedUsd: string;   // sum of pending_approval payment amounts
  networks: string[];    // active network labels
  fetchedAt: string;     // ISO datetime
}

export type PaymentStatus =
  | "routing"
  | "settled"
  | "pending_approval"
  | "released"
  | "blocked"
  | "failed";

export interface WalletBalance {
  currency: string;
  value: string;
  issuer: string | null;
}

export interface WalletTransaction {
  hash: string;
  transactionType: string;
  direction: "incoming" | "outgoing" | "self" | "related";
  counterparty: string | null;
  amount: WalletBalance | null;
  feeXrp: string | null;
  result: string | null;
  ledgerIndex: number | null;
  timestamp: string | null;
  explorerUrl: string;
}

export interface WalletNetworkSnapshot {
  network: "testnet" | "devnet";
  active: boolean;
  xrpBalance: string;
  tokenBalances: WalletBalance[];
  ownerCount: number | null;
  sequence: number | null;
  ledgerIndex: number | null;
  transactions: WalletTransaction[];
  accountExplorerUrl: string;
  error: string | null;
}

export interface WalletOverview {
  address: string;
  fetchedAt: string;
  networks: WalletNetworkSnapshot[];
}

export interface RuntimeStatus {
  status: "ok";
  mockMode: boolean;
  network: "mock" | "testnet" | "devnet";
  fireflyConfirmationEnabled: boolean;
}

export interface PaymentIntent {
  from: string;
  to: string;
  senderName: string;
  senderCountry: string;
  receiverName: string;
  receiverCountry: string;
  receiverEntityType: "company" | "individual";
  purpose: string;
  amount: number;
  currency: string;
  reference: string;
  coverRequired?: boolean;
  coverRequiredAboveUsd?: number | null;
}

export interface QuoteRequest {
  amount: number;
  currency: string;
}

export interface RouteQuote {
  sourceAmount: number;
  destAmount: number;
  rate: number;
  pathSummary: string;
  estimatedFee: number;
  // XRPL pathfinding output (ripple_path_find). null falls back to the default path.
  paths?: unknown[][] | null;
  sendMax?: number | null; // Payment.SendMax cap on source spend
  deliverMin?: number | null; // Payment.DeliverMin floor for partial payments
}

export interface SanctionsMatch {
  id: string;
  caption: string;
  schema: string;
  score: number;
  datasets: string[];
  url: string | null;
}

export interface PublicIntelResult {
  score: number; // 0-100; advisory risk signal, never a block by itself.
  confidence: string;
  flags: string[];
  sources: string[];
  summary: string;
}

// XRPL Credentials (XLS-70) KYC status for the receiver. `checked` is false when
// the credential layer is disabled; `verified` is true only for an accepted,
// non-expired credential from the trusted issuer.
export interface CredentialStatus {
  checked: boolean;
  verified: boolean;
  subject: string | null;
  issuer: string | null;
  credentialType: string | null;
  expiration: string | null;
  uri: string | null;
  reason: string;
}

// Credential-issuing agent (XLS-70). Mirrors apps/api/app/schemas.py.
export type CredentialRecordStatus =
  | "issued"
  | "accepted"
  | "verified"
  | "refused"
  | "failed";

export interface CredentialIssueRequest {
  subject: string;
  subjectName?: string | null;
  credentialType?: string | null;
  uri?: string | null;
  expiration?: string | null;
  note?: string | null;
  // When true, the agent also runs the subject-side CredentialAccept so the
  // credential is immediately usable (inline KYC gate).
  autoAccept?: boolean;
}

export interface CredentialLogEntry {
  recordId: string;
  timestamp: string;
  message: string;
}

export interface CredentialRecord {
  id: string;
  subject: string;
  subjectName: string | null;
  issuer: string | null;
  credentialType: string | null;
  uri: string | null;
  expiration: string | null;
  status: CredentialRecordStatus;
  accepted: boolean;
  verified: boolean;
  refusedReason: string | null;
  txHash: string | null;
  explorerUrl: string | null;
  acceptTxHash: string | null;
  acceptExplorerUrl: string | null;
  auditExplanation: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ComplianceResult {
  amlScore: number; // 0–100
  sanctioned: boolean;
  flags: string[];
  explanation: string;
  sanctionsMatches: SanctionsMatch[];
  publicIntel: PublicIntelResult | null;
  credential: CredentialStatus | null;
}

export interface PolicyDecision {
  requiresApproval: boolean;
  ruleFired: string | null;
  reasons: string[];
  blocked: boolean;
  blockReason: string | null;
}

export interface ApprovalChallenge {
  paymentId: string;
  digest: string; // hex digest the Firefly signs
  network: string; // e.g. "xrpl:testnet"
  owner: string;   // treasury wallet XRPL address
}

export interface Receipt {
  paymentId: string;
  intent: PaymentIntent;
  routeQuote: RouteQuote | null;
  compliance: ComplianceResult | null;
  policyDecision: PolicyDecision | null;
  status: PaymentStatus;
  escrowSequence: number | null;
  escrowCreateTxHash: string | null;
  approvalSignature: string | null;
  txHash: string | null;
  explorerUrl: string | null;
  auditExplanation: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface Payment {
  id: string;
  intent: PaymentIntent;
  routeQuote: RouteQuote | null;
  compliance: ComplianceResult | null;
  policyDecision: PolicyDecision | null;
  status: PaymentStatus;
  escrowSequence: number | null;
  escrowCreateTxHash: string | null;
  approvalSignature: string | null;
  txHash: string | null;
  explorerUrl: string | null;
  // Second explorer (bithomp) link for cross-checking the same tx hash.
  explorerUrlSecondary: string | null;
  auditExplanation: string | null;
  receiptHash: string | null;
  cover: PremiumQuote | null;
  createdAt: string;
  updatedAt: string;
}

export interface AgentLogEntry {
  paymentId: string;
  timestamp: string;
  message: string;
}

// ── XLS-33 MPTokens — COMPLY compliance-attestation ─────────────────────────

export interface MPTAttestationRecord {
  id: string;
  issuanceId: string;
  recipient: string;
  paymentId: string;
  amountSettled: number;
  txHash: string;
  explorerUrl: string | null;
  timestamp: string;
}

export interface MPTStatus {
  issuanceId: string | null;
  enabled: boolean;
  network: string;        // "mock" | "testnet" | "devnet"
  metadataHex: string;    // hex-encoded "COMPLY" metadata
  totalMinted: number;
  authorizedCount: number;
  recentAttestations: MPTAttestationRecord[];
}

export interface MPTAuthorizeRequest {
  holder: string;         // XRPL address to authorize
}

// ── XLS-65 Single Asset Vault ────────────────────────────────────────────────

export interface VaultOpRecord {
  id: string;
  operation: "create" | "deposit" | "withdraw";
  amount: number;
  txHash: string;
  explorerUrl: string | null;
  timestamp: string;
}

export interface VaultStatus {
  vaultId: string | null;
  enabled: boolean;
  network: string; // "mock" | "devnet" | "testnet"
  deposited: number;
  shares: number;
  walletBalance: number;
  assetCurrency: string;
  assetIssuer: string | null;
  sweepThresholdUsd: number;
  recallThresholdUsd: number;
  recentOperations: VaultOpRecord[];
}

// ── Autonomous Treasury Agent ─────────────────────────────────────────────────

export interface TreasuryGoal {
  id: string;
  name: string;
  enabled: boolean;
  beneficiaryName: string;
  beneficiaryAddress: string;
  beneficiaryCountry: string;
  receiverEntityType: "company" | "individual";
  amount: number;
  currency: string;
  reference: string;
  purpose: string;
  triggerIntervalHours: number;
  lastTriggeredAt: string | null;
  agentId?: string | null;
  serviceUrl?: string | null;
  serviceType?: string | null;
  category?: string | null;
}

export interface TreasuryGoalCreate {
  name: string;
  enabled?: boolean;
  beneficiaryName: string;
  beneficiaryAddress: string;
  beneficiaryCountry: string;
  receiverEntityType?: "company" | "individual";
  amount: number;
  currency: string;
  reference: string;
  purpose: string;
  triggerIntervalHours?: number;
  serviceUrl?: string | null;
  serviceType?: string | null;
  category?: string | null;
}

export interface TreasuryAgentRun {
  id: string;
  startedAt: string;
  completedAt: string | null;
  goalsEvaluated: number;
  goalsTriggered: number;
  paymentsInitiated: string[]; // payment IDs
  paymentsSkipped: string[];   // goal IDs
  triggerLog: string[];
  narration: string | null;
  status: string; // "completed" | "error"
  agentId?: string | null;
}

// Firefly bridge contract (browser <-> localhost bridge).
// The bridge derives the digest locally from these fields — WYSIWYS.
// All fields must exactly match what apps/api/app/tools/firefly.py::canonical_payload uses.
export interface BridgeSignRequest {
  paymentId: string;
  amount: number;
  currency: string;
  dest: string;
  reference: string;
  // XRPL escrow binding — pins approval to one specific on-chain escrow.
  network: string;          // e.g. "xrpl:testnet"
  owner: string;            // treasury wallet XRPL address
  escrowSequence: number;
  escrowCreateTxHash: string;
}

export interface BridgeSignResponse {
  paymentId: string;
  signature: string; // hex secp256k1 signature
  publicKey: string; // hex, for the backend to verify against
}

// ── Business-defined payment agents ──────────────────────────────────────────

export type AgentStatus = "active" | "paused";

export interface AgentCreate {
  id: string;
  name: string;
  description?: string | null;
  maxSinglePayment: string;
  maxDailySpend: string;
  requiresApprovalAbove: string;
  currency?: string;
  allowedCategories?: string[] | null;
  allowedAssets?: string[];
  allowedNetwork?: string;
  allowedAddresses?: string[] | null;
  blockedAddresses?: string[];
  allowedHosts?: string[] | null;
  blockedHosts?: string[];
  requireKnownMerchant?: boolean;
}

export interface Agent extends AgentCreate {
  status: AgentStatus;
  policyRevision: number;
  createdAt: string;
  updatedAt: string;
}

export interface AgentUpdate {
  name?: string;
  description?: string | null;
  status?: AgentStatus;
  maxSinglePayment?: string;
  maxDailySpend?: string;
  requiresApprovalAbove?: string;
  currency?: string;
  allowedCategories?: string[] | null;
  allowedAssets?: string[] | null;
  allowedNetwork?: string | null;
  allowedAddresses?: string[] | null;
  blockedAddresses?: string[] | null;
  allowedHosts?: string[] | null;
  blockedHosts?: string[] | null;
  requireKnownMerchant?: boolean;
}

export interface AgentDashboardStats {
  agentId: string;
  paymentsToday: number;
  amountSpentToday: string;
  pendingApprovals: number;
  lastRunAt: string | null;
  lastRunStatus: string | null;
  totalPayments: number;
  totalBlocked: number;
  totalEscalated: number;
}

// ── ARS Guardrails & Audit (Pillar 5) ────────────────────────────────────────
// Mirror of apps/api/app/schemas.py ARS section — keep in sync by hand.

export interface GuardrailResult {
  name: string;         // e.g. "G1_kya", "G4_scope", "G7_hardware_veto"
  passed: boolean;
  ruleFired: string | null;
  reason: string | null;
}

export interface ConstraintResult {
  allowed: boolean;
  action: "allow" | "review" | "block";
  ruleFired: string | null;
  reasons: string[];
  guardrailTrail: GuardrailResult[];
}

// ── ARS Scope Policy (G4) ────────────────────────────────────────────────────

export interface AgentScopeSchema {
  maxPerTransaction: string;   // Decimal string
  maxPerDay: string;           // Decimal string
  allowedServiceHosts: string[] | null;
  allowedServiceTypes: string[] | null;
}

export interface ScopeDecisionSchema {
  allowed: boolean;
  ruleFired: string | null;
  reasons: string[];
}

// ── ARS Delegation (G5) ──────────────────────────────────────────────────────

export interface DelegationGrant {
  id: string;
  parentAddress: string;
  childAddress: string;
  maxTotal: string;            // Decimal string
  maxPerTx: string;
  maxPerDay: string;
  currency: string;
  allowedServiceHosts: string[] | null;
  allowedServiceTypes: string[] | null;
  expiresAt: string | null;
  fundTxHash: string | null;
  fundExplorerUrl: string | null;
  revoked: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface DelegationGrantCreate {
  parentAddress: string;
  childAddress: string;
  maxTotal: string;
  maxPerTx: string;
  maxPerDay: string;
  currency?: string;
  allowedServiceHosts?: string[] | null;
  allowedServiceTypes?: string[] | null;
  expiresAt?: string | null;
}

// ── ARS x402 Service Payment ─────────────────────────────────────────────────

export interface X402PaymentRequirement {
  serviceUrl: string;
  facilitatorUrl: string;
  payTo: string;
  assetCurrency: string;
  assetIssuer: string;
  network: string;
  amount: string;              // Decimal string
  invoiceId: string;
  sourceTag: number | null;
  expiresAt: string | null;
}

export interface X402Settlement {
  invoiceId: string;
  txHash: string;
  explorerUrl: string | null;
  proofHeader: string;
  amount: string;              // Decimal string
  currency: string;
  guardrailTrail: GuardrailResult[];
  auditEventId: string | null;
  agentId: string | null;
}

export interface ServicePaymentRecord {
  id: string;
  agentId: string | null;
  status: "settled" | "blocked";
  serviceHost: string;
  invoiceId: string;
  assetCurrency: string;
  assetIssuer: string;
  amount: string;              // Decimal string
  txHash: string | null;
  explorerUrl: string | null;
  guardrailTrail: GuardrailResult[];
  auditEventId: string | null;
  cover: PremiumQuote | null;
  createdAt: string;
  updatedAt: string;
}

// ── ARS Trade Finance / Credit (Pillar 2) ────────────────────────────────────

export type ReceivableStatus =
  | "registered"
  | "funds_reserved"
  | "credit_drawn"
  | "supplier_paid"
  | "awaiting_maturity"
  | "repayment_received"
  | "credit_settled"
  | "closed"
  | "needs_recovery";

export interface Receivable {
  id: string;
  invoiceId: string;
  buyer: string;
  supplier: string;
  amount: string;              // Decimal string — face value
  discountRate: string;        // Decimal string
  dueDate: string;
  status: ReceivableStatus;
  drawTxHash: string | null;
  drawExplorerUrl: string | null;
  paymentTxHash: string | null;
  paymentExplorerUrl: string | null;
  repaymentTxHash: string | null;
  settleTxHash: string | null;
  loanId: string | null;
  guardrailTrail: GuardrailResult[];
  auditEventId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ReceivableCreate {
  invoiceId: string;
  buyer: string;
  supplier: string;
  amount: string;
  discountRate: string;
  dueDate: string;
}

// ── ARS Insurance (Pillar 3) ─────────────────────────────────────────────────

export interface InsurancePremiumRecord {
  id: string;
  jobId: string;
  agentAddress: string;
  premiumAmount: string;       // Decimal string
  currency: string;
  txHash: string | null;
  explorerUrl: string | null;
  scoreBand: string | null;
  guardrailTrail: GuardrailResult[];
  createdAt: string;
}

export interface InsurancePayoutRecord {
  id: string;
  jobId: string;
  merchant: string;
  collateralSlashed: string;   // Decimal string
  poolDrawn: string;
  totalPaid: string;
  currency: string;
  slashTxHash: string | null;
  poolDrawTxHash: string | null;
  reputationMptProtected: boolean;
  guardrailTrail: GuardrailResult[];
  createdAt: string;
}

export type QuoteDecision = "OFFER" | "REVIEW" | "DECLINE";
export type CoverLine =
  | "merchant_default"
  | "lender_credit"
  | "principal_score"
  | "mandate_breach";

export interface PremiumQuote {
  decision: QuoteDecision;
  premium: string;       // Decimal string
  lines: Record<string, string>;
  pd: number;
  credibility: number;
  reason: string;
  receiptHash: string;
}

export interface PoolStatus {
  enabled: boolean;
  currency: string;
  deposited: string;
  walletBalance: string;
  availableCapacity: string;
  premiumsCollected: string;
  claimsPaid: string;
}

export interface AgentRiskState {
  agentAddress: string;
  scoreBand: string;
  alpha: number;
  beta: number;
  pd: number;
  credibility: number;
  updatedAt: string;
}

export interface TxnContext {
  category: string;
  tenorBand: string;
  cptyBand: string;
  firstSeen?: boolean;
  amount: string;          // Decimal string
  amountZ?: number;
  velocityZ?: number;
  concentrationZ?: number;
  activeLines: CoverLine[];
}

export interface InsuranceQuoteRequest {
  agentAddress: string;
  scoreBand?: string;
  txnContext: TxnContext;
}

export interface BindRequest {
  jobId: string;
  agentAddress: string;
  scoreBand?: string;
  currency?: string;
  quote: PremiumQuote;
}

export interface ClaimRequest {
  jobId: string;
  agentAddress: string;
  merchant: string;
  merchantName?: string | null;
  merchantCountry?: string;
  scoreBand?: string;
  currency?: string;
  collateral?: string;
}

export interface AgentRiskState {
  agentAddress: string;
  scoreBand: string | null;
  alpha: number;
  beta: number;
  pd: number;
  credibility: number;
  updatedAt: string;
}

export interface PoolStatus {
  firstLoss: string;
  currency: string;
  premiumsCollected: string;
  payoutsMade: string;
  capacityRatio: number;
  vaultBalance: string;        // on-ledger XLS-65 vault balance
  lpCapital: string;           // total LP-provided capital
}

// Capital Provider (LP)
export interface CapitalDepositRequest {
  lpAddress: string;
  amount: string;
  currency?: string;
}

export interface CapitalWithdrawRequest {
  lpAddress: string;
  amount: string;
}

export interface LpPosition {
  lpAddress: string;
  capital: string;
  sharePct: number;
  currency: string;
  txHash: string | null;
  explorerUrl: string | null;
  guardrailTrail: GuardrailResult[];
  updatedAt: string;
}

// ── Agent Cover (annual policy — hallucination) ───────────────────────────────

export type CoverLineKind = "hallucination" | "non_delivery";
export type CoverPolicyStatus = "active" | "expired" | "exhausted" | "cancelled";
export type CoverLossBearerKind = "merchant" | "treasury";
export type CoverDecision = "OFFER" | "REVIEW" | "DECLINE";

export interface CoverQuoteRequest {
  agentAddress: string;
  scoreBand?: string;
  coverCap: string;           // Decimal string
  perClaimLimit: string;      // Decimal string
  termDays?: number;
  lines?: CoverLineKind[];
}

export interface CoverQuote {
  decision: CoverDecision;
  premium: string;            // Decimal string — prorated
  lineRates: Record<string, string>;
  pd: number;
  credibility: number;
  scoreBand: string;
  coverCap: string;
  perClaimLimit: string;
  termDays: number;
  reason: string | null;
  receiptHash: string;
}

export interface CoverBindRequest {
  agentAddress: string;
  scoreBand?: string;
  coverCap: string;
  perClaimLimit: string;
  termDays?: number;
  lines?: CoverLineKind[];
  quote: CoverQuote;
}

export interface CoverPolicy {
  id: string;
  agentAddress: string;
  periodStart: string;
  periodEnd: string;
  lines: CoverLineKind[];
  coverCap: string;
  perClaimLimit: string;
  premium: string;
  coverUsed: string;
  coverRemaining: string;
  scoreBand: string;
  status: CoverPolicyStatus;
  premiumTxHash: string | null;
  explorerUrl: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface CoverClaimEvidence {
  policyId: string;
  paymentId: string;
}

export interface CoverPayout {
  id: string;
  policyId: string;
  paymentId: string;
  line: CoverLineKind;
  lossBearerKind: CoverLossBearerKind;
  destination: string;
  amountPaid: string;
  poolDrawn: string;
  classification: string;
  narration: string | null;
  guardrailTrail: GuardrailResult[];
  txHash: string | null;
  explorerUrl: string | null;
  receiptHash: string;
  createdAt: string;
}

export interface CoverPoolStatus {
  firstLoss: string;
  reserved: string;
  freeCapacity: string;
  currency: string;
  premiumsCollected: string;
  claimsPaid: string;
  capacityRatio: number;
  policiesActive: number;
  coverInForce: string;
}

// ── ARS Audit Log Event ──────────────────────────────────────────────────────

export interface AuditEventRecord {
  eventId: string;
  eventType: string;
  actor: string;
  contextKind: string;
  payload: Record<string, unknown>;
  timestamp: string;
  priorEventHash: string;
  eventHash: string;
  signature: string;
}
