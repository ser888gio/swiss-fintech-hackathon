import type {
  AgentLogEntry,
  Payment,
  PaymentIntent,
  QuoteRequest,
  Receipt,
  RouteQuote,
} from "@treasury/shared";

const DEFAULT_API_BASE_URL = "http://localhost:8000";
const RAILWAY_API_BASE_URL = "https://api-production-c47fd.up.railway.app";

function getApiBaseUrl(): string {
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL;
  }

  if (
    typeof window !== "undefined" &&
    window.location.hostname === "web-production-cba3.up.railway.app"
  ) {
    return RAILWAY_API_BASE_URL;
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
  releaseTampered: (id: string, signature: string) =>
    request<never>(`/payments/${id}/release-tampered`, {
      method: "POST",
      body: JSON.stringify({ signature }),
    }),
  getReceipt: (id: string) =>
    request<{ receipt: Receipt; receiptHash: string }>(`/payments/${id}/receipt`),
};
