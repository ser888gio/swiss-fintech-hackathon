import type { Payment } from "@treasury/shared";

interface Props {
  payment: Payment;
  onApprove: (payment: Payment) => void;
  approving: boolean;
}

const STATUS_LABEL: Record<Payment["status"], string> = {
  routing: "Routing",
  settled: "Settled",
  pending_approval: "Pending approval",
  released: "Released",
  failed: "Failed",
};

export function PaymentCard({ payment, onApprove, approving }: Props) {
  const { intent, compliance, status, explorerUrl } = payment;
  return (
    <article className={`payment status-${status}`}>
      <header>
        <strong>
          {intent.amount.toLocaleString()} {intent.currency}
        </strong>
        <span className="badge">{STATUS_LABEL[status]}</span>
      </header>
      <p className="muted">{intent.reference} → {intent.to.slice(0, 10)}…</p>
      {compliance && <p className="muted">{compliance.explanation}</p>}
      {payment.auditExplanation && <p className="audit">{payment.auditExplanation}</p>}

      {status === "pending_approval" && (
        <button className="approve" disabled={approving} onClick={() => onApprove(payment)}>
          {approving ? "Waiting for Firefly…" : "Approve on Firefly"}
        </button>
      )}

      {explorerUrl && (
        <a href={explorerUrl} target="_blank" rel="noreferrer">
          View on testnet explorer ↗
        </a>
      )}
    </article>
  );
}
