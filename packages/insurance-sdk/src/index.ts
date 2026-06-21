/**
 * @treasury/insurance-sdk — typed, multi-party client for the agent-default
 * insurance protocol. Pricing and premium binding are internal deterministic
 * payment-workflow steps; this client exposes mandates and insurer read/claim APIs.
 *
 * See docs/insurance-protocol.md for the party model and the gates each action
 * passes. Every settlement/claim/capital response carries a `guardrailTrail`.
 */
import type {
  ClaimRequest,
  InsurancePayoutRecord,
  InsurancePremiumRecord,
  PaymentIntent,
  PoolStatus,
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
  readonly merchant: MerchantClient;
  readonly insurer: InsurerClient;

  constructor(config: InsuranceSdkConfig = {}) {
    const t = new Transport(config);
    this.merchant = new MerchantClient();
    this.insurer = new InsurerClient(t);
  }
}

export function createInsuranceProtocol(config?: InsuranceSdkConfig): InsuranceProtocol {
  return new InsuranceProtocol(config);
}
