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

export interface ComplianceResult {
  amlScore: number; // 0–100
  sanctioned: boolean;
  flags: string[];
  explanation: string;
  sanctionsMatches: SanctionsMatch[];
  publicIntel: PublicIntelResult | null;
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
}

export interface Receipt {
  paymentId: string;
  intent: PaymentIntent;
  routeQuote: RouteQuote | null;
  compliance: ComplianceResult | null;
  policyDecision: PolicyDecision | null;
  status: PaymentStatus;
  escrowSequence: number | null;
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
  approvalSignature: string | null;
  txHash: string | null;
  explorerUrl: string | null;
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

// Firefly bridge contract (browser <-> localhost bridge).
// The bridge derives the digest locally from these fields — WYSIWYS.
export interface BridgeSignRequest {
  paymentId: string;
  amount: number;
  currency: string;
  dest: string;
  reference: string;
}

export interface BridgeSignResponse {
  paymentId: string;
  signature: string; // hex secp256k1 signature
  publicKey: string; // hex, for the backend to verify against
}
