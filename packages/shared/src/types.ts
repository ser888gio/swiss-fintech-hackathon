// Shared types for the web dashboard and the Firefly bridge.
// Mirrored by apps/api/app/schemas.py (Pydantic) — keep the two in sync by hand.

export type PaymentStatus =
  | "routing"
  | "settled"
  | "pending_approval"
  | "released"
  | "blocked"
  | "failed";

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
