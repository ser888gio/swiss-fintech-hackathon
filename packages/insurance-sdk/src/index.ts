/**
 * @treasury/insurance-sdk — typed, multi-party client for the agent-default
 * insurance protocol. One client per party (agent, merchant, LP, insurer), so an
 * integrator writes `protocol.agent.bindCover(...)` instead of raw fetch calls.
 *
 * See docs/insurance-protocol.md for the party model and the gates each action
 * passes. Every settlement/claim/capital response carries a `guardrailTrail`.
 */
import type {
  AgentRiskState,
  BindRequest,
  CapitalDepositRequest,
  CapitalWithdrawRequest,
  ClaimRequest,
  InsurancePayoutRecord,
  InsurancePremiumRecord,
  InsuranceQuoteRequest,
  LpPosition,
  PaymentIntent,
  PoolStatus,
  PremiumQuote,
} from "@treasury/shared";

export interface InsuranceSdkConfig {
  /** API origin. Default: http://localhost:8000 */
  baseUrl?: string;
  /** Route prefix. Default: /treasury/insurance */
  prefix?: string;
  /** Injectable fetch (for Node/tests). Default: global fetch. */
  fetch?: typeof fetch;
}

/** Thrown on a non-2xx response; carries the HTTP status and server detail. */
export class InsuranceProtocolError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "InsuranceProtocolError";
  }
}

class Transport {
  private readonly baseUrl: string;
  private readonly prefix: string;
  private readonly doFetch: typeof fetch;

  constructor(config: InsuranceSdkConfig = {}) {
    this.baseUrl = (config.baseUrl ?? "http://localhost:8000").replace(/\/$/, "");
    this.prefix = config.prefix ?? "/treasury/insurance";
    const f = config.fetch ?? (globalThis.fetch as typeof fetch | undefined);
    if (!f) throw new Error("No fetch available — pass config.fetch");
    this.doFetch = f.bind(globalThis);
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await this.doFetch(`${this.baseUrl}${this.prefix}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const data = (await res.json()) as { detail?: string };
        if (data?.detail) detail = data.detail;
      } catch {
        /* non-JSON error body */
      }
      throw new InsuranceProtocolError(res.status, detail);
    }
    return (await res.json()) as T;
  }
}

/** The Agent: requests quotes and binds (pays) cover for a job. */
export class AgentClient {
  constructor(private readonly t: Transport) {}
  quoteCover(req: InsuranceQuoteRequest): Promise<PremiumQuote> {
    return this.t.request("POST", "/quote", req);
  }
  bindCover(req: BindRequest): Promise<InsurancePremiumRecord> {
    return this.t.request("POST", "/bind", req);
  }
  getRisk(agentAddress: string): Promise<AgentRiskState> {
    return this.t.request("GET", `/agents/${encodeURIComponent(agentAddress)}/risk`);
  }
}

/** The Counterparty (merchant/lender): mandates cover as a payment condition. */
export class MerchantClient {
  /**
   * Attach a cover-required condition to a payment intent (pure — no network).
   * The orchestrator auto-binds a premium before settling such a payment.
   */
  requireCover(intent: PaymentIntent, opts: { aboveUsd?: number } = {}): PaymentIntent {
    return { ...intent, coverRequired: true, coverRequiredAboveUsd: opts.aboveUsd ?? null };
  }
}

/** The Capital Provider (LP): supplies / recalls first-loss capital. */
export class CapitalClient {
  constructor(private readonly t: Transport) {}
  depositCapital(req: CapitalDepositRequest): Promise<LpPosition> {
    return this.t.request("POST", "/capital/deposit", req);
  }
  withdrawCapital(req: CapitalWithdrawRequest): Promise<LpPosition> {
    return this.t.request("POST", "/capital/withdraw", req);
  }
  positions(): Promise<LpPosition[]> {
    return this.t.request("GET", "/capital");
  }
}

/** The Insurer (Pool): settles claims and exposes pool/portfolio read models. */
export class InsurerClient {
  constructor(private readonly t: Transport) {}
  settleClaim(req: ClaimRequest): Promise<InsurancePayoutRecord> {
    return this.t.request("POST", "/claim", req);
  }
  pool(): Promise<PoolStatus> {
    return this.t.request("GET", "/pool");
  }
  premiums(): Promise<InsurancePremiumRecord[]> {
    return this.t.request("GET", "/premiums");
  }
  payouts(): Promise<InsurancePayoutRecord[]> {
    return this.t.request("GET", "/payouts");
  }
}

/** Entry point: one object exposing every party's client. */
export class InsuranceProtocol {
  readonly agent: AgentClient;
  readonly merchant: MerchantClient;
  readonly lp: CapitalClient;
  readonly insurer: InsurerClient;

  constructor(config: InsuranceSdkConfig = {}) {
    const t = new Transport(config);
    this.agent = new AgentClient(t);
    this.merchant = new MerchantClient();
    this.lp = new CapitalClient(t);
    this.insurer = new InsurerClient(t);
  }
}

export function createInsuranceProtocol(config?: InsuranceSdkConfig): InsuranceProtocol {
  return new InsuranceProtocol(config);
}
