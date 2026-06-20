import type {
  Agent,
  AgentCreate,
  AgentDashboardStats,
  AgentLogEntry,
  AgentRiskState,
  AgentUpdate,
  ApprovalChallenge,
  BindRequest,
  CapitalDepositRequest,
  CapitalWithdrawRequest,
  ClaimRequest,
  CoverBindRequest,
  CoverClaimEvidence,
  CoverPolicy,
  CoverPoolStatus,
  CoverPayout,
  CoverQuote,
  CoverQuoteRequest,
  CredentialIssueRequest,
  CredentialLogEntry,
  CredentialRecord,
  CredentialStatus,
  DelegationGrant,
  DelegationGrantCreate,
  InsurancePayoutRecord,
  InsurancePremiumRecord,
  InsuranceQuoteRequest,
  LpPosition,
  MPTAttestationRecord,
  MPTAuthorizeRequest,
  MPTStatus,
  Payment,
  PaymentIntent,
  PoolStatus,
  PremiumQuote,
  QuoteRequest,
  Receivable,
  ReceivableCreate,
  RouteQuote,
  RuntimeStatus,
  ServicePaymentRecord,
  TreasuryAgentRun,
  TreasuryGoal,
  TreasuryGoalCreate,
  TreasurySummary,
  VaultOpRecord,
  VaultStatus,
  WalletOverview,
  X402Settlement,
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
  getRuntimeStatus: () => request<RuntimeStatus>("/health"),
  getWallet: () => request<WalletOverview>("/wallet"),
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
  getReceiptPdf: async (id: string): Promise<Blob> => {
    const res = await fetch(`${BASE_URL}/payments/${id}/receipt.pdf`);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.blob();
  },

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

  getTreasurySummary: () => request<TreasurySummary>("/treasury/summary"),

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

  // Trade Finance / On-chain Credit.
  listReceivables: () => request<Receivable[]>("/treasury/receivables"),
  registerReceivable: (create: ReceivableCreate) =>
    request<Receivable>("/treasury/receivables", { method: "POST", body: JSON.stringify(create) }),
  paySupplierEarly: (invoiceId: string) =>
    request<Receivable>(`/treasury/receivables/${invoiceId}/pay-early`, { method: "POST" }),
  collectRepayment: (invoiceId: string) =>
    request<Receivable>(`/treasury/receivables/${invoiceId}/collect`, { method: "POST" }),

  // x402 service payments.
  triggerServicePayment: (serviceUrl: string, serviceType = "data_lookup") =>
    request<X402Settlement>("/treasury/service-payment", {
      method: "POST",
      body: JSON.stringify({ service_url: serviceUrl, service_type: serviceType }),
    }),

  // Agent-to-Agent Delegation.
  listDelegations: () => request<DelegationGrant[]>("/treasury/delegations"),
  createDelegation: (create: DelegationGrantCreate) =>
    request<DelegationGrant>("/treasury/delegations", { method: "POST", body: JSON.stringify(create) }),
  revokeDelegation: (grantId: string) =>
    request<DelegationGrant>(`/treasury/delegations/${grantId}`, { method: "DELETE" }),

  // Insurance pricing & risk engine.
  quoteInsurance: (req: InsuranceQuoteRequest) =>
    request<PremiumQuote>("/insurance/quote", { method: "POST", body: JSON.stringify(req) }),
  bindInsurance: (req: BindRequest) =>
    request<InsurancePremiumRecord>("/treasury/insurance/bind", { method: "POST", body: JSON.stringify(req) }),
  listInsurancePremiums: () =>
    request<InsurancePremiumRecord[]>("/treasury/insurance/premiums"),
  // Backward-compatible aliases still used by some pages.
  listPremiums: () =>
    request<InsurancePremiumRecord[]>("/treasury/insurance/premiums"),
  claimInsurance: (req: ClaimRequest) =>
    request<InsurancePayoutRecord>("/treasury/insurance/claim", { method: "POST", body: JSON.stringify(req) }),
  settleClaim: (req: ClaimRequest) =>
    request<InsurancePayoutRecord>("/treasury/insurance/claim", { method: "POST", body: JSON.stringify(req) }),
  listInsurancePayouts: () =>
    request<InsurancePayoutRecord[]>("/treasury/insurance/payouts"),
  listPayouts: () =>
    request<InsurancePayoutRecord[]>("/treasury/insurance/payouts"),
  getInsurancePool: () =>
    request<PoolStatus>("/treasury/insurance/pool"),
  getAgentRisk: (address: string) =>
    request<AgentRiskState>(`/treasury/insurance/agents/${address}/risk`),

  // Insurance first-loss capital providers (LPs).
  listInsuranceCapital: () =>
    request<LpPosition[]>("/treasury/insurance/capital"),
  depositInsuranceCapital: (req: CapitalDepositRequest) =>
    request<LpPosition>("/treasury/insurance/capital/deposit", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  withdrawInsuranceCapital: (req: CapitalWithdrawRequest) =>
    request<LpPosition>("/treasury/insurance/capital/withdraw", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  // Business-defined payment agents.
  listAgents: () => request<Agent[]>("/agents"),
  createAgent: (req: AgentCreate) =>
    request<Agent>("/agents", { method: "POST", body: JSON.stringify(req) }),
  getAgent: (agentId: string) => request<Agent>(`/agents/${agentId}`),
  updateAgent: (agentId: string, req: AgentUpdate) =>
    request<Agent>(`/agents/${agentId}`, { method: "PUT", body: JSON.stringify(req) }),
  deleteAgent: (agentId: string) =>
    request<void>(`/agents/${agentId}`, { method: "DELETE" }),
  listAgentGoals: (agentId: string) => request<TreasuryGoal[]>(`/agents/${agentId}/goals`),
  createAgentGoal: (agentId: string, req: TreasuryGoalCreate) =>
    request<TreasuryGoal>(`/agents/${agentId}/goals`, { method: "POST", body: JSON.stringify(req) }),
  deleteAgentGoal: (agentId: string, goalId: string) =>
    request<void>(`/agents/${agentId}/goals/${goalId}`, { method: "DELETE" }),
  runAgent: (agentId: string) =>
    request<TreasuryAgentRun>(`/agents/${agentId}/run`, { method: "POST" }),
  listAgentRuns: (agentId: string) => request<TreasuryAgentRun[]>(`/agents/${agentId}/runs`),
  getAgentStats: (agentId: string) => request<AgentDashboardStats>(`/agents/${agentId}/stats`),
  seedMaersk: () => request<Agent[]>("/agents/seed-maersk", { method: "POST" }),
  runController: () => request<TreasuryAgentRun>("/agents/controller/run", { method: "POST" }),
  listServicePayments: (agentId?: string) => request<ServicePaymentRecord[]>(
    `/agents/service-payments/history${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ""}`
  ),

  // Agent Cover (annual policy — hallucination line).
  coverQuote: (req: CoverQuoteRequest) =>
    request<CoverQuote>("/cover/quote", { method: "POST", body: JSON.stringify(req) }),
  coverBind: (req: CoverBindRequest) =>
    request<CoverPolicy>("/cover/bind", { method: "POST", body: JSON.stringify(req) }),
  coverPolicies: (agent?: string) =>
    request<CoverPolicy[]>(`/cover/policies${agent ? `?agent=${encodeURIComponent(agent)}` : ""}`),
  coverClaim: (evidence: CoverClaimEvidence) =>
    request<CoverPayout>("/cover/claim", { method: "POST", body: JSON.stringify(evidence) }),
  coverPayouts: (policyId?: string) =>
    request<CoverPayout[]>(`/cover/payouts${policyId ? `?policy_id=${encodeURIComponent(policyId)}` : ""}`),
  coverPool: () =>
    request<CoverPoolStatus>("/cover/pool"),
  coverRunDemo41: () =>
    request<{ scenario: string; description: string; payout: CoverPayout; narration: string }>(
      "/cover/demo/underpayment", { method: "POST" }
    ),
};

