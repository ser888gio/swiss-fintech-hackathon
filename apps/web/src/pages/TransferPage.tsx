import type { Payment, PaymentIntent } from "@treasury/shared";

import { NewPaymentForm } from "../components/NewPaymentForm.js";
import { PaymentCard } from "../components/PaymentCard.js";

interface Props {
  payments: Payment[];
  busy: boolean;
  approvingId: string | null;
  resolvingKycId: string | null;
  tamperedId: string | null;
  tamperError: Record<string, string>;
  onSubmit: (intent: PaymentIntent) => Promise<Payment | null>;
  onApprove: (payment: Payment) => void;
  onResolveKyc: (payment: Payment) => void;
  onTamperRetry: (payment: Payment) => void;
}

export function TransferPage({
  payments,
  busy,
  approvingId,
  resolvingKycId,
  tamperedId,
  tamperError,
  onSubmit,
  onApprove,
  onResolveKyc,
  onTamperRetry,
}: Props) {
  return (
    <>
      <div style={{ padding: "0.55rem 0.75rem", marginBottom: "1rem", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: "0.82rem", lineHeight: 1.5 }}>
        <strong style={{ color: "var(--paper)" }}>New Payment</strong> — initiate a cross-border XRPL payment. Amounts within your policy threshold settle autonomously in seconds; larger or compliance-flagged amounts lock on-chain and require <a href="https://firefly.app/" target="_blank" rel="noreferrer" style={{ color: "var(--orange)", textDecoration: "none" }}>Firefly</a> (a secure hardware device that acts as a veto layer) approval via the Bridge before funds move. Policy rules are deterministic code, not LLM decisions. Every transaction is recorded in the audit trail on the right.
      </div>
      <div className="transfer-layout">
      <NewPaymentForm onSubmit={onSubmit} disabled={busy} />

      <aside className="transfer-audit">
        <h2 className="transfer-audit-title">Audit trail</h2>
        {payments.length === 0 ? (
          <p className="muted">No payments yet.</p>
        ) : (
          <div className="transfer-audit-list">
            {payments.map((payment) => (
              <PaymentCard
                key={payment.id}
                payment={payment}
                onApprove={onApprove}
                approving={approvingId === payment.id}
                onResolveKyc={onResolveKyc}
                resolvingKyc={resolvingKycId === payment.id}
                onTamperRetry={onTamperRetry}
                tampering={tamperedId === payment.id}
                tamperError={tamperError[payment.id]}
              />
            ))}
          </div>
        )}
      </aside>
    </div>
    </>
  );
}
