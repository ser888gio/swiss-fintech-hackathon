import { useEffect, useMemo, useState } from "react";
import type {
  Agent,
  CredentialRecord,
  InsurancePayoutRecord,
  InsurancePremiumRecord,
  Payment,
  PoolStatus,
} from "@treasury/shared";

import { api } from "../lib/api.js";

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
  settled: "Settled",
  pending_approval: "Awaiting Firefly",
  released: "Released",
  blocked: "Blocked by policy",
  failed: "Failed",
};

function money(amount: number | string, currency = "USD") {
  const value = Number(amount);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: value % 1 === 0 ? 0 : 2,
  }).format(Number.isFinite(value) ? value : 0);
}

function shortAddress(value: string) {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value;
}

function statusClass(status: Payment["status"]) {
  return `dashboard-status status-${status}`;
}

export function DashboardPage({ payments, approvingId, resolvingKycId, onApprove, onResolveKyc, onNavigate }: Props) {
  const [credentials, setCredentials] = useState<CredentialRecord[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [premiums, setPremiums] = useState<InsurancePremiumRecord[]>([]);
  const [payouts, setPayouts] = useState<InsurancePayoutRecord[]>([]);
  const [pool, setPool] = useState<PoolStatus | null>(null);

  useEffect(() => {
    let live = true;
    void Promise.allSettled([
      api.listCredentials(),
      api.listAgents(),
      api.listInsurancePremiums(),
      api.listInsurancePayouts(),
      api.getInsurancePool(),
    ]).then(([credentialResult, agentResult, premiumResult, payoutResult, poolResult]) => {
      if (!live) return;
      if (credentialResult.status === "fulfilled") setCredentials(credentialResult.value);
      if (agentResult.status === "fulfilled") setAgents(agentResult.value);
      if (premiumResult.status === "fulfilled") setPremiums(premiumResult.value);
      if (payoutResult.status === "fulfilled") setPayouts(payoutResult.value);
      if (poolResult.status === "fulfilled") setPool(poolResult.value);
    });
    return () => { live = false; };
  }, []);

  const pendingApprovals = payments.filter((payment) => payment.status === "pending_approval");
  const verifiedCredentials = credentials.filter((credential) => credential.verified || credential.status === "verified");
  const activeAgents = agents.filter((agent) => agent.status === "active");
  const ledgerPayments = payments.filter((payment) => payment.txHash);
  const recent = payments.slice(0, 6);

  const activity = useMemo(() => {
    const credentialActivity = credentials.slice(0, 3).map((credential) => ({
      id: `credential-${credential.id}`,
      kind: "CREDENTIAL",
      title: `${credential.credentialType ?? "KYC"} · ${credential.subjectName ?? shortAddress(credential.subject)}`,
      detail: credential.auditExplanation ?? `Credential ${credential.status}`,
      status: credential.status,
      time: credential.updatedAt,
      url: credential.acceptExplorerUrl ?? credential.explorerUrl,
    }));
    const paymentActivity = recent.map((payment) => ({
      id: `payment-${payment.id}`,
      kind: "TRANSACTION",
      title: `${money(payment.intent.amount, payment.intent.currency)} · ${payment.intent.receiverName}`,
      detail: `${payment.policyDecision?.ruleFired ?? "policy evaluated"} · AML ${payment.compliance?.amlScore ?? "—"}/100`,
      status: payment.status,
      time: payment.updatedAt,
      url: payment.explorerUrl,
    }));
    return [...credentialActivity, ...paymentActivity]
      .sort((a, b) => Date.parse(b.time) - Date.parse(a.time))
      .slice(0, 7);
  }, [credentials, recent]);

  return (
    <div className="dashboard-page operations-dashboard">
      <section className="operations-hero">
        <div>
          <span className="eyebrow">Trust operations · XRPL</span>
          <h1>Credentials. Cover. Settlement.</h1>
          <p>One control room for proving who may transact, what risk is insured, and exactly what reached the ledger.</p>
        </div>
        <div className="hero-actions">
          <button className="dashboard-primary" type="button" onClick={() => onNavigate("/transfer")}>New transaction</button>
          <button className="text-action" type="button" onClick={() => onNavigate("/credentials")}>Issue credential</button>
        </div>
      </section>

      <section className="trust-metrics" aria-label="Trust operations summary">
        <button type="button" onClick={() => onNavigate("/credentials")} className="trust-metric metric-credential">
          <span className="metric-icon" aria-hidden="true">✓</span>
          <span><small>Verified identities</small><strong>{verifiedCredentials.length}</strong><em>{credentials.length} issued credentials</em></span>
        </button>
        <button type="button" onClick={() => onNavigate("/insurance")} className="trust-metric metric-cover">
          <span className="metric-icon" aria-hidden="true">◈</span>
          <span><small>Available cover</small><strong>{money(pool?.availableCapacity ?? 0, pool?.currency ?? "USD")}</strong><em>{premiums.length} bound premiums · {payouts.length} claims</em></span>
        </button>
        <button type="button" onClick={() => onNavigate("/transfer")} className="trust-metric metric-ledger">
          <span className="metric-icon" aria-hidden="true">↗</span>
          <span><small>Ledger transactions</small><strong>{ledgerPayments.length}</strong><em>{pendingApprovals.length} awaiting hardware approval</em></span>
        </button>
      </section>

      <section className="agent-workflow dashboard-panel" aria-label="Agent workflow">
        <div className="panel-heading">
          <div><span className="eyebrow">Live workflow</span><h2>How the operators hand off</h2></div>
          <span className="workflow-note">One orchestrator · deterministic authority</span>
        </div>
        <div className="agent-rail">
          <article className="agent-stage">
            <div className="agent-avatar avatar-credential">ID</div>
            <div><span className="agent-mode">DETERMINISTIC TOOL</span><h3>Credential verifier</h3><p>Checks accepted XLS-70 identity before compliance scoring.</p></div>
            <span className="agent-signal">{verifiedCredentials.length} verified</span>
          </article>
          <span className="rail-arrow" aria-hidden="true">→</span>
          <article className="agent-stage">
            <div className="agent-avatar avatar-cover">CV</div>
            <div><span className="agent-mode">PRICING ENGINE</span><h3>Cover underwriter</h3><p>Prices transaction risk and binds capacity under code rules.</p></div>
            <span className="agent-signal">{pool?.enabled ? "pool online" : "pool offline"}</span>
          </article>
          <span className="rail-arrow" aria-hidden="true">→</span>
          <article className="agent-stage">
            <div className="agent-avatar avatar-settlement">TX</div>
            <div><span className="agent-mode">POLICY + XRPL</span><h3>Settlement operator</h3><p>Routes, gates and submits; Firefly releases escalations.</p></div>
            <span className="agent-signal">{activeAgents.length || 1} active</span>
          </article>
        </div>
      </section>

      <section className="operations-grid">
        <section className="dashboard-panel activity-panel">
          <div className="panel-heading">
            <div><span className="eyebrow">Unified audit stream</span><h2>Credential & transaction activity</h2></div>
            <button className="text-action" type="button" onClick={() => onNavigate("/transfer")}>View transactions</button>
          </div>
          {activity.length === 0 ? <p className="muted">No activity yet. Issue a credential or create the first transaction.</p> : (
            <div className="activity-table">
              <div className="activity-head"><span>Event</span><span>Deterministic result</span><span>Proof</span></div>
              {activity.map((event) => (
                <article className="activity-row" key={event.id}>
                  <div><span className={`event-dot event-${event.kind.toLowerCase()}`} /><span><small>{event.kind}</small><strong>{event.title}</strong></span></div>
                  <p><span className="dashboard-status">{event.status.replace(/_/g, " ")}</span>{event.detail}</p>
                  {event.url ? <a href={event.url} target="_blank" rel="noreferrer">Explorer ↗</a> : <span className="muted">No ledger proof</span>}
                </article>
              ))}
            </div>
          )}
        </section>

        <aside className="operations-side">
          <section className="dashboard-panel cover-health">
            <div className="panel-heading"><div><span className="eyebrow">Insurance pool</span><h2>Capacity health</h2></div><span className={`health-dot ${pool?.enabled ? "online" : ""}`} /></div>
            <div className="capacity-number"><strong>{money(pool?.availableCapacity ?? 0, pool?.currency ?? "USD")}</strong><span>available</span></div>
            <div className="capacity-track"><span style={{ width: `${Math.min(100, Number(pool?.deposited) ? (Number(pool?.availableCapacity) / Number(pool?.deposited)) * 100 : 0)}%` }} /></div>
            <dl className="cover-facts"><div><dt>Deposited</dt><dd>{money(pool?.deposited ?? 0)}</dd></div><div><dt>Premiums</dt><dd>{money(pool?.premiumsCollected ?? 0)}</dd></div><div><dt>Claims paid</dt><dd>{money(pool?.claimsPaid ?? 0)}</dd></div></dl>
            <button className="dashboard-primary" type="button" onClick={() => onNavigate("/insurance")}>Open insurance desk</button>
          </section>

          <section className="dashboard-panel pending-panel">
            <div className="panel-heading"><div><span className="eyebrow">Human boundary</span><h2>Firefly queue</h2></div><strong>{pendingApprovals.length}</strong></div>
            {pendingApprovals.length === 0 ? <p className="muted">No locked funds. Routine, compliant transactions can settle automatically.</p> : pendingApprovals.slice(0, 2).map((payment) => (
              <article className="pending-card" key={payment.id}>
                <span className={statusClass(payment.status)}>{STATUS_LABEL[payment.status]}</span>
                <strong>{money(payment.intent.amount, payment.intent.currency)} to {payment.intent.receiverName}</strong>
                <p>{payment.policyDecision?.reasons.join("; ") || "Requires signed approval."}</p>
                {payment.compliance?.credential?.checked && !payment.compliance.credential.verified && (
                  <button className="kyc-resolve" type="button" disabled={resolvingKycId === payment.id} onClick={() => onResolveKyc(payment)}>
                    {resolvingKycId === payment.id ? "Issuing credential…" : "Resolve credential gate"}
                  </button>
                )}
                <button className="dashboard-primary" type="button" disabled={approvingId === payment.id} onClick={() => onApprove(payment)}>
                  {approvingId === payment.id ? "Waiting for Firefly…" : "Approve with Firefly"}
                </button>
              </article>
            ))}
          </section>
        </aside>
      </section>
    </div>
  );
}
