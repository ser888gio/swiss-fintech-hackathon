import type {
  AgentLogEntry,
  ApprovalChallenge,
  CredentialIssueRequest,
  CredentialLogEntry,
  CredentialRecord,
  CredentialStatus,
  MPTAttestationRecord,
  MPTAuthorizeRequest,
  MPTStatus,
  Payment,
  PaymentIntent,
  QuoteRequest,
  Receipt,
  RouteQuote,
  TreasuryAgentRun,
  TreasuryGoal,
  TreasuryGoalCreate,
  VaultOpRecord,
  VaultStatus,
} from "@treasury/shared";

const DEFAULT_API_BASE_URL = "http://localhost:8000";
const RAILWAY_API_BASE_URL = "https://api-production-c47fd.up.railway.app";

function getApiBaseUrl(): string {
  // Explicit build-time override always wins (set VITE_API_BASE_URL in the
  // Cloudflare Pages / hosting build environment).
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL;
  }

  // Any deployed (non-localhost) origin — Railway, Cloudflare Pages, a custom
  // domain — talks to the Railway API. Only local dev falls back to localhost.
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    const isLocal = host === "localhost" || host === "127.0.0.1" || host === "";
    if (!isLocal) {
      return RAILWAY_API_BASE_URL;
    }
  }

  return DEFAULT_API_BASE_URL;
}

const BASE_URL = getApiBaseUrl();

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${detail}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  createPayment: (intent: PaymentIntent) =>
    request<Payment>("/payments", { method: "POST", body: JSON.stringify(intent) }),
  quotePayment: (quote: QuoteRequest) =>
    request<RouteQuote>("/payments/quote", { method: "POST", body: JSON.stringify(quote) }),
  listPayments: () => request<Payment[]>("/payments"),
  getLogs: (id: string) => request<AgentLogEntry[]>(`/payments/${id}/logs`),
  release: (id: string, signature: string) =>
    request<Payment>(`/payments/${id}/release`, {
      method: "POST",
      body: JSON.stringify({ signature }),
    }),
  challenge: (id: string) =>
    request<ApprovalChallenge>(`/payments/${id}/challenge`),
  releaseTampered: (id: string, signature: string) =>
    request<never>(`/payments/${id}/release-tampered`, {
      method: "POST",
      body: JSON.stringify({ signature }),
    }),
  getReceipt: (id: string) =>
    request<{ receipt: Receipt; receiptHash: string }>(`/payments/${id}/receipt`),

  // Credential-issuing agent.
  issueCredential: (req: CredentialIssueRequest) =>
    request<CredentialRecord>("/credentials", { method: "POST", body: JSON.stringify(req) }),
  listCredentials: () => request<CredentialRecord[]>("/credentials"),
  getCredentialLogs: (id: string) => request<CredentialLogEntry[]>(`/credentials/${id}/logs`),
  acceptCredential: (id: string) =>
    request<CredentialRecord>(`/credentials/${id}/accept`, { method: "POST" }),
  verifyCredential: (id: string) =>
    request<CredentialRecord>(`/credentials/${id}/verify`, { method: "POST" }),
  verifySubject: (subject: string) =>
    request<CredentialStatus>(`/credentials/verify/${subject}`),

  // Autonomous treasury agent.
  listTreasuryGoals: () => request<TreasuryGoal[]>("/treasury/goals"),
  createTreasuryGoal: (goal: TreasuryGoalCreate) =>
    request<TreasuryGoal>("/treasury/goals", { method: "POST", body: JSON.stringify(goal) }),
  deleteTreasuryGoal: (id: string) =>
    request<void>(`/treasury/goals/${id}`, { method: "DELETE" }),
  triggerTreasuryRun: () =>
    request<TreasuryAgentRun>("/treasury/run", { method: "POST" }),
  listTreasuryRuns: () => request<TreasuryAgentRun[]>("/treasury/runs"),

  // XLS-33 MPToken compliance attestation.
  getMptStatus: () => request<MPTStatus>("/treasury/mpt"),
  createMptIssuance: () => request<MPTStatus>("/treasury/mpt/issuance", { method: "POST" }),
  authorizeMptHolder: (req: MPTAuthorizeRequest) =>
    request<MPTAttestationRecord>("/treasury/mpt/authorize", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  mintMptAttestation: () =>
    request<MPTAttestationRecord>("/treasury/mpt/mint", { method: "POST" }),

  // XLS-65 vault.
  getVaultStatus: () => request<VaultStatus>("/treasury/vault"),
  createVault: () => request<VaultOpRecord>("/treasury/vault", { method: "POST" }),
  depositToVault: (amount: number) =>
    request<VaultOpRecord>("/treasury/vault/deposit", {
      method: "POST",
      body: JSON.stringify({ amount }),
    }),
  withdrawFromVault: (amount: number) =>
    request<VaultOpRecord>("/treasury/vault/withdraw", {
      method: "POST",
      body: JSON.stringify({ amount }),
    }),
};
