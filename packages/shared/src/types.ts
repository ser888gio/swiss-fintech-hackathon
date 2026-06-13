// Shared types for the web dashboard and the Firefly bridge.
// Mirrored by apps/api/app/schemas.py (Pydantic) — keep the two in sync by hand.

export type PaymentStatus =
  | "routing"
  | "settled"
  | "pending_approval"
  | "released"
  | "failed";

export interface PaymentIntent {
  from: string;
  to: string;
  amount: number;
  currency: string;
  reference: string;
}

export interface RouteQuote {
  sourceAmount: number;
  destAmount: number;
  rate: number;
  pathSummary: string;
  estimatedFee: number;
}

export interface ComplianceResult {
  amlScore: number; // 0–100
  sanctioned: boolean;
  flags: string[];
  explanation: string;
}

export interface PolicyDecision {
  requiresApproval: boolean;
  ruleFired: string | null;
  reasons: string[];
}

export interface ApprovalChallenge {
  paymentId: string;
  digest: string; // hex digest the Firefly signs
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
  createdAt: string;
  updatedAt: string;
}

export interface AgentLogEntry {
  paymentId: string;
  timestamp: string;
  message: string;
}

// Firefly bridge contract (browser <-> localhost bridge).
export interface BridgeSignRequest {
  paymentId: string;
  digest: string;
}

export interface BridgeSignResponse {
  paymentId: string;
  signature: string; // hex secp256k1 signature
  publicKey: string; // hex, for the backend to verify against
}
