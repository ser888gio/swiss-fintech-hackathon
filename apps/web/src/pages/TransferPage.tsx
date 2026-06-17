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
  );
}
