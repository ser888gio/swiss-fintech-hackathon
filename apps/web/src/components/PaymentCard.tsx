import { api } from "../lib/api.js";
import type { Payment } from "@treasury/shared";

interface Props {
  payment: Payment;
  onApprove: (payment: Payment) => void;
  approving: boolean;
  onResolveKyc?: (payment: Payment) => void;
  resolvingKyc?: boolean;
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
  onResolveKyc,
  resolvingKyc,
  onTamperRetry,
  tampering,
  tamperError,
}: Props) {
  const { intent, compliance, policyDecision, status, explorerUrl, explorerUrlSecondary } = payment;
  const isTerminal = TERMINAL.has(status);
  const topSanctionsMatch = compliance?.sanctionsMatches[0];
  const publicIntel = compliance?.publicIntel;
  const credential = compliance?.credential;
  const route = payment.routeQuote;
  // Offer the inline KYC gate only when the escalation is (at least partly) a
  // missing credential — never for a sanctioned counterparty (that stays blocked).
  const kycMissing = Boolean(credential?.checked && !credential.verified);
  const canResolveKyc = status === "pending_approval" && kycMissing && Boolean(onResolveKyc);

  return (
    <article className={`payment status-${status}`}>
      <header>
        <strong>
          {intent.amount.toLocaleString()} {intent.currency}
        </strong>
        <span className="badge">{STATUS_LABEL[status]}</span>
      </header>
      <p className="muted">
        {intent.reference} to {intent.receiverName}, {intent.receiverCountry}
      </p>
      <p className="muted">
        {intent.senderName}, {intent.senderCountry} to {intent.receiverEntityType} payout
      </p>
      {route && (
        <p className="muted">
          Route: {route.pathSummary}
          {route.paths && route.paths.length > 0 ? " (ripple_path_find)" : ""}
          {route.sendMax != null
            ? ` · SendMax ${route.sendMax.toLocaleString()}`
            : ""}
        </p>
      )}
      {credential?.checked && (
        <p className="muted kyc">
          <span className={`kyc-badge ${credential.verified ? "verified" : "missing"}`}>
            {credential.verified ? "KYC verified" : "KYC missing"}
          </span>
          XLS-70 credential: {credential.reason}
        </p>
      )}
      {compliance && <p className="muted">{compliance.explanation}</p>}
      {topSanctionsMatch && (
        <p className="muted">
          OpenSanctions: {topSanctionsMatch.caption} ({Math.round(topSanctionsMatch.score * 100)}% match)
        </p>
      )}
      {publicIntel && (
        <p className="muted">
          Public intelligence: {publicIntel.score}/100 - {publicIntel.summary}
        </p>
      )}
      {policyDecision?.blocked && policyDecision.blockReason && (
        <p className="block-reason">Refused: {policyDecision.blockReason}</p>
      )}
      {payment.auditExplanation && <p className="audit">{payment.auditExplanation}</p>}

      {canResolveKyc && (
        <button
          className="kyc-resolve"
          disabled={resolvingKyc}
          onClick={() => onResolveKyc?.(payment)}
        >
          {resolvingKyc ? "Issuing credential..." : "Issue KYC credential & retry"}
        </button>
      )}

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
          testnet.xrpl.org
        </a>
      )}
      {explorerUrlSecondary && (
        <a href={explorerUrlSecondary} target="_blank" rel="noreferrer">
          test.bithomp.com
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
