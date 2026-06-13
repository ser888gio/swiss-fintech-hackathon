import type {
  AgentLogEntry,
  Payment,
  PaymentIntent,
  Receipt,
} from "@treasury/shared";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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
