import { api } from "../lib/api.js";
import type { Payment } from "@treasury/shared";

interface Props {
  payment: Payment;
  onApprove: (payment: Payment) => void;
  approving: boolean;
  onTamperRetry: (payment: Payment) => void;
  tampering: boolean;
  tamperError?: string;
}

const STATUS_LABEL: Record<Payment["status"], string> = {
  routing: "Routing",
  settled: "Settled",
  pending_approval: "Pending approval",
  released: "Released",
  blocked: "Refused",
  failed: "Failed",
};

const TERMINAL = new Set<Payment["status"]>(["settled", "released", "blocked"]);

async function downloadReceipt(payment: Payment) {
  try {
    const data = await api.getReceipt(payment.id);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `receipt-${payment.id.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  } catch {
    alert("Receipt not yet available.");
  }
}

export function PaymentCard({
  payment,
  onApprove,
  approving,
  onTamperRetry,
  tampering,
  tamperError,
}: Props) {
  const { intent, compliance, policyDecision, status, explorerUrl } = payment;
  const isTerminal = TERMINAL.has(status);

  return (
    <article className={`payment status-${status}`}>
      <header>
        <strong>
          {intent.amount.toLocaleString()} {intent.currency}
        </strong>
        <span className="badge">{STATUS_LABEL[status]}</span>
      </header>
      <p className="muted">
        {intent.reference} to {intent.to.slice(0, 10)}...
      </p>
      {compliance && <p className="muted">{compliance.explanation}</p>}
      {policyDecision?.blocked && policyDecision.blockReason && (
        <p className="block-reason">Refused: {policyDecision.blockReason}</p>
      )}
      {payment.auditExplanation && <p className="audit">{payment.auditExplanation}</p>}

      {status === "pending_approval" && (
        <button className="approve" disabled={approving} onClick={() => onApprove(payment)}>
          {approving ? "Waiting for Firefly..." : "Approve on Firefly"}
        </button>
      )}

      {status === "released" && payment.approvalSignature && (
        <button className="tamper-demo" disabled={tampering} onClick={() => onTamperRetry(payment)}>
          {tampering ? "Testing..." : "Tamper & retry (DEMO)"}
        </button>
      )}

      {tamperError && <p className="tamper-error">{tamperError}</p>}

      {explorerUrl && (
        <a href={explorerUrl} target="_blank" rel="noreferrer">
          View on testnet explorer
        </a>
      )}

      {isTerminal && (
        <div className="receipt-row">
          <button className="receipt-btn" onClick={() => void downloadReceipt(payment)}>
            Download audit receipt
          </button>
          {payment.receiptHash && (
            <code className="receipt-hash" title="SHA-256 of the canonical decision trail">
              {payment.receiptHash.slice(0, 16)}...
            </code>
          )}
        </div>
      )}
    </article>
  );
}
