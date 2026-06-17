import type { Payment } from "@treasury/shared";

interface Props {
  payments: Payment[];
  approvingId: string | null;
  resolvingKycId: string | null;
  onApprove: (payment: Payment) => void;
  onResolveKyc: (payment: Payment) => void;
  onNavigate: (path: string) => void;
}

const STATUS_LABEL: Record<Payment["status"], string> = {
  routing: "Routing",
  settled: "Auto-settled",
  pending_approval: "Locked for approval",
  released: "Released by Firefly",
  blocked: "Refused in code",
  failed: "Failed",
};

function money(amount: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: amount % 1 === 0 ? 0 : 2,
  }).format(amount);
}

function totalRouted(payments: Payment[]) {
  return payments.reduce((sum, payment) => sum + (payment.routeQuote?.destAmount ?? payment.intent.amount), 0);
}

function statusClass(status: Payment["status"]) {
  return `dashboard-status status-${status}`;
}

export function DashboardPage({ payments, approvingId, resolvingKycId, onApprove, onResolveKyc, onNavigate }: Props) {
  const settledCount = payments.filter((payment) => payment.status === "settled" || payment.status === "released").length;
  const pendingApprovals = payments.filter((payment) => payment.status === "pending_approval");
  const refusedCount = payments.filter((payment) => payment.status === "blocked").length;
  const recent = payments.slice(0, 5);

  return (
    <div className="dashboard-page">
      <section className="dashboard-hero">
        <div>
          <span className="eyebrow">XRPL treasury control room</span>
          <h1>Code decides. The AI explains.</h1>
          <p>
            Run the demo from one screen: routine payments auto-settle, risky payments lock on-chain, and
            Firefly releases only the exact payment the operator sees.
          </p>
        </div>
        <button className="dashboard-primary" type="button" onClick={() => onNavigate("/transfer")}>
          Open transfer flow
        </button>
      </section>

      <section className="proof-grid" aria-label="Treasury proof metrics">
        <div className="proof-metric">
          <span>Settled / released</span>
          <strong>{settledCount}</strong>
        </div>
        <div className="proof-metric">
          <span>Awaiting Firefly</span>
          <strong>{pendingApprovals.length}</strong>
        </div>
        <div className="proof-metric">
          <span>Refused in code</span>
          <strong>{refusedCount}</strong>
        </div>
        <div className="proof-metric">
          <span>Total routed</span>
          <strong>{money(totalRouted(payments))}</strong>
        </div>
      </section>

      <section className="dashboard-layout">
        <div className="dashboard-main">
          <section className="dashboard-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Demo beats</span>
                <h2>Four proof shots for judges</h2>
              </div>
            </div>
            <div className="beat-grid">
              <article className="beat-card">
                <span>01</span>
                <strong>Clean auto-settle</strong>
                <p>Low-risk invoice routes, clears compliance, and shows explorer proof when real XRPL submission is enabled.</p>
              </article>
              <article className="beat-card">
                <span>02</span>
                <strong>Sanctions refusal</strong>
                <p>Sanctioned counterparties are blocked outright. Hardware approval cannot override policy.</p>
              </article>
              <article className="beat-card">
                <span>03</span>
                <strong>Firefly hardware veto</strong>
                <p>Large payments are locked on-chain until the device signs the visible payment details.</p>
              </article>
              <article className="beat-card">
                <span>04</span>
                <strong>Tamper rejection</strong>
                <p>Change the payment after signing and the backend rejects the signature before release.</p>
              </article>
            </div>
          </section>

          <section className="dashboard-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Recent activity</span>
                <h2>Decision trail</h2>
              </div>
              <button className="text-action" type="button" onClick={() => onNavigate("/transfer")}>
                Create payment
              </button>
            </div>
            {recent.length === 0 ? (
              <p className="muted">No payments yet. Open the transfer flow to run the first demo beat.</p>
            ) : (
              <div className="decision-list">
                {recent.map((payment) => (
                  <article className="decision-row" key={payment.id}>
                    <div>
                      <strong>
                        {money(payment.intent.amount, payment.intent.currency)} to {payment.intent.receiverName}
                      </strong>
                      <p>
                        {payment.policyDecision?.ruleFired ?? "auto policy"} · AML{" "}
                        {payment.compliance?.amlScore ?? "--"}/100 ·{" "}
                        {payment.routeQuote?.pathSummary ?? "route pending"}
                      </p>
                      {payment.receiptHash && <code>{payment.receiptHash.slice(0, 18)}...</code>}
                    </div>
                    <div className="decision-actions">
                      <span className={statusClass(payment.status)}>{STATUS_LABEL[payment.status]}</span>
                      {payment.explorerUrl && (
                        <a href={payment.explorerUrl} target="_blank" rel="noreferrer">
                          Explorer
                        </a>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>

        <aside className="dashboard-side">
          <section className="dashboard-panel pending-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Pending approval</span>
                <h2>Firefly queue</h2>
              </div>
            </div>
            {pendingApprovals.length === 0 ? (
              <p className="muted">No funds are locked right now. Run a large transfer to create a hardware approval.</p>
            ) : (
              pendingApprovals.map((payment) => (
                <article className="pending-card" key={payment.id}>
                  <span className={statusClass(payment.status)}>{STATUS_LABEL[payment.status]}</span>
                  <strong>
                    {money(payment.intent.amount, payment.intent.currency)} to {payment.intent.receiverName}
                  </strong>
                  <p>{payment.policyDecision?.reasons.join("; ") || "Requires signed approval."}</p>
                  {payment.escrowSequence && <code>Escrow #{payment.escrowSequence}</code>}
                  {payment.compliance?.credential?.checked && !payment.compliance.credential.verified && (
                    <button
                      className="kyc-resolve"
                      type="button"
                      disabled={resolvingKycId === payment.id}
                      onClick={() => onResolveKyc(payment)}
                    >
                      {resolvingKycId === payment.id ? "Issuing credential..." : "Issue KYC credential & retry"}
                    </button>
                  )}
                  <button className="dashboard-primary" type="button" disabled={approvingId === payment.id} onClick={() => onApprove(payment)}>
                    {approvingId === payment.id ? "Waiting for Firefly..." : "Approve with Firefly"}
                  </button>
                </article>
              ))
            )}
          </section>

          <section className="dashboard-panel rogue-panel">
            <span className="eyebrow">Rogue agent proof</span>
            <h2>Try to fool the AI. The money still cannot move.</h2>
            <p>
              A poisoned invoice can trick narration, but it cannot change the policy engine or forge the
              Firefly signature. The worst case is bad explanation, not a bad payment.
            </p>
            <div className="guardrail-stack">
              <span>Deterministic policy threshold</span>
              <span>On-chain escrow lock</span>
              <span>Verified Firefly signature</span>
              <span>Audit receipt hash</span>
            </div>
          </section>
        </aside>
      </section>
    </div>
  );
}
