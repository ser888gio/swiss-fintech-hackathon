import type { Payment, PaymentIntent } from "@treasury/shared";

import { NewPaymentForm } from "../components/NewPaymentForm.js";
import { PaymentCard } from "../components/PaymentCard.js";

interface Props {
  payments: Payment[];
  busy: boolean;
  approvingId: string | null;
  tamperedId: string | null;
  tamperError: Record<string, string>;
  onSubmit: (intent: PaymentIntent) => Promise<Payment | null>;
  onApprove: (payment: Payment) => void;
  onTamperRetry: (payment: Payment) => void;
}

export function TransferPage({
  payments,
  busy,
  approvingId,
  tamperedId,
  tamperError,
  onSubmit,
  onApprove,
  onTamperRetry,
}: Props) {
  return (
    <div className="transfer-layout">
      <NewPaymentForm onSubmit={onSubmit} disabled={busy} />

      {payments.length > 0 && (
        <aside className="transfer-audit">
          <h2 className="transfer-audit-title">Recent payments</h2>
          <div className="transfer-audit-list">
            {payments.map((payment) => (
              <PaymentCard
                key={payment.id}
                payment={payment}
                onApprove={onApprove}
                approving={approvingId === payment.id}
                onTamperRetry={onTamperRetry}
                tampering={tamperedId === payment.id}
                tamperError={tamperError[payment.id]}
              />
            ))}
          </div>
        </aside>
      )}
    </div>
  );
}
