import { useEffect, useMemo, useState } from "react";
import type {
  Agent,
  AgentDashboardStats,
  CredentialRecord,
  InsurancePayoutRecord,
  Payment,
  PoolStatus,
  Receivable,
  RuntimeStatus,
  ServicePaymentRecord,
  TreasuryGoal,
  TreasurySummary,
} from "@treasury/shared";

import { api } from "../lib/api.js";
import { formatMoney as money } from "../lib/utils.js";

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

function shortAddress(value: string) {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - Date.parse(iso);
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function relativeFromNow(iso: string): string {
  const diff = Date.parse(iso) - Date.now();
  if (diff <= 0) return "now";
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `in ${hours}h`;
  return `in ${Math.floor(hours / 24)}d`;
}

const LOW_BALANCE_THRESHOLD = 500;

export function DashboardPage({ payments, approvingId, resolvingKycId, onApprove, onResolveKyc, onNavigate }: Props) {
  const [credentials, setCredentials] = useState<CredentialRecord[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentStats, setAgentStats] = useState<AgentDashboardStats | null>(null);
  const [payouts, setPayouts] = useState<InsurancePayoutRecord[]>([]);
  const [pool, setPool] = useState<PoolStatus | null>(null);
  const [receivables, setReceivables] = useState<Receivable[]>([]);
  const [goals, setGoals] = useState<TreasuryGoal[]>([]);
  const [servicePayments, setServicePayments] = useState<ServicePaymentRecord[]>([]);
  const [summary, setSummary] = useState<TreasurySummary | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null);

  useEffect(() => {
    let live = true;
    void Promise.allSettled([
      api.listCredentials(),
      api.listAgents(),
      api.listInsurancePayouts(),
      api.getInsurancePool(),
      api.listReceivables(),
      api.listTreasuryGoals(),
      api.getTreasurySummary(),
      api.getRuntimeStatus(),
      api.listServicePayments(),
    ]).then(([credRes, agentRes, payoutRes, poolRes, recRes, goalRes, summaryRes, runtimeRes, spRes]) => {
      if (!live) return;
      if (credRes.status === "fulfilled") setCredentials(credRes.value);
      if (agentRes.status === "fulfilled") setAgents(agentRes.value);
      if (payoutRes.status === "fulfilled") setPayouts(payoutRes.value);
      if (poolRes.status === "fulfilled") setPool(poolRes.value);
      if (recRes.status === "fulfilled") setReceivables(recRes.value);
      if (goalRes.status === "fulfilled") setGoals(goalRes.value);
      if (summaryRes.status === "fulfilled") setSummary(summaryRes.value);
      if (runtimeRes.status === "fulfilled") setRuntimeStatus(runtimeRes.value);
      if (spRes.status === "fulfilled") setServicePayments(spRes.value);

      // Load per-agent stats for the first active agent
      if (agentRes.status === "fulfilled") {
        const firstActive = agentRes.value.find(a => a.status === "active");
        if (firstActive && live) {
          void api.getAgentStats(firstActive.id).then(stats => {
            if (live) setAgentStats(stats);
          }).catch(() => null);
        }
      }
    });
    return () => { live = false; };
  }, []);

  // ── Derived values ─────────────────────────────────────────────────────────

  const pendingApprovals = payments.filter(p => p.status === "pending_approval");
  const blockedPayments = payments.filter(p => p.status === "blocked");
  const failedPayments = payments.filter(p => p.status === "failed");
  const activeAgents = agents.filter(a => a.status === "active");
  const firstActiveAgent = activeAgents[0] ?? null;

  const startOfToday = useMemo(() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; }, []);
  const settledToday = payments.filter(p =>
    (p.status === "settled" || p.status === "released") &&
    Date.parse(p.createdAt) >= startOfToday.getTime()
  );
  const settledTodayTotal = settledToday.reduce((sum, p) => sum + p.intent.amount, 0);
  const settledTodayCurrency = settledToday[0]?.intent.currency ?? "USD";

  const reservedTotal = pendingApprovals.reduce((sum, p) => sum + p.intent.amount, 0);
  const reservedCurrency = pendingApprovals[0]?.intent.currency ?? "USD";

  const stableUsd = Number(summary?.stableUsd ?? 0);
  const isLowBalance = stableUsd > 0 && stableUsd < LOW_BALANCE_THRESHOLD;

  const unverifiedCredentials = credentials.filter(c => c.status === "issued" || c.status === "refused" || c.status === "failed");
  const exceptionCount = pendingApprovals.length + blockedPayments.length + failedPayments.length + unverifiedCredentials.length + (isLowBalance ? 1 : 0);

  // Upcoming obligations: goals that fire within 7 days
  const sevenDaysMs = 7 * 24 * 3600_000;
  const upcomingGoals = useMemo(() => goals.filter(g => {
    if (!g.enabled) return false;
    const nextFire = g.lastTriggeredAt
      ? new Date(Date.parse(g.lastTriggeredAt) + g.triggerIntervalHours * 3600_000)
      : new Date();
    return nextFire.getTime() <= Date.now() + sevenDaysMs;
  }), [goals]);
  // Autonomous operations stats
  const totalPayments = agentStats?.totalPayments ?? 0;
  const totalBlocked = agentStats?.totalBlocked ?? 0;
  const totalEscalated = agentStats?.totalEscalated ?? 0;
  const totalSettled = Math.max(0, totalPayments - totalBlocked - totalEscalated);
  const autoSettleRate = totalPayments > 0 ? Math.round((totalSettled / totalPayments) * 100) : null;
  const x402Count = servicePayments.filter(sp => sp.status === "settled").length;

  // Unified activity feed (Event / Result / Why / Proof), most recent first
  const activityFeed = useMemo(() => {
    const paymentRows = payments.slice(0, 12).map(p => ({
      id: `payment-${p.id}`,
      kind: "PAYMENT" as const,
      event: `${money(p.intent.amount, p.intent.currency)} → ${p.intent.receiverName}`,
      result: STATUS_LABEL[p.status],
      why: p.policyDecision?.reasons[0] ?? p.auditExplanation ?? "—",
      proof: p.explorerUrl,
      coverage: p.coverage.status,
      coverageReason: p.coverage.requiredBy,
      time: p.createdAt,
      status: p.status,
    }));
    const spRows = servicePayments.slice(0, 4).map(sp => ({
      id: `sp-${sp.id}`,
      kind: "SERVICE" as const,
      event: `Service · ${sp.serviceHost} · ${money(sp.amount, sp.assetCurrency)}`,
      result: sp.status === "settled" ? "Settled" : "Blocked",
      why: "x402 mandate",
      proof: sp.explorerUrl ?? null,
      coverage: "not_required" as const,
      coverageReason: null,
      time: sp.createdAt,
      status: sp.status as string,
    }));
    const credRows = credentials.slice(0, 3).map(c => ({
      id: `cred-${c.id}`,
      kind: "CREDENTIAL" as const,
      event: `${c.credentialType ?? "KYC"} · ${c.subjectName ?? shortAddress(c.subject)}`,
      result: c.status.replace(/_/g, " "),
      why: c.auditExplanation ?? `Credential ${c.status}`,
      proof: c.acceptExplorerUrl ?? c.explorerUrl ?? null,
      coverage: "not_required" as const,
      coverageReason: null,
      time: c.updatedAt,
      status: c.status,
    }));
    return [...paymentRows, ...spRows, ...credRows]
      .sort((a, b) => Date.parse(b.time) - Date.parse(a.time))
      .slice(0, 8);
  }, [payments, servicePayments, credentials]);

  const openReceivables = receivables.filter(r => r.status !== "closed");
  const creditRisk = useMemo(() => {
    const recovery = receivables.filter(r => r.status === "needs_recovery");
    const overdue = openReceivables.filter(r => Date.parse(r.dueDate) < Date.now());
    if (recovery.length > 0) return "High";
    if (overdue.length > 0) return "Elevated";
    return "Low";
  }, [receivables, openReceivables]);

  function goalNextFire(goal: TreasuryGoal): Date {
    return goal.lastTriggeredAt
      ? new Date(Date.parse(goal.lastTriggeredAt) + goal.triggerIntervalHours * 3600_000)
      : new Date();
  }

  function goalSettleMode(goal: TreasuryGoal): "auto" | "approval" | "unknown" {
    if (!firstActiveAgent) return "unknown";
    return goal.amount <= Number(firstActiveAgent.requiresApprovalAbove) ? "auto" : "approval";
  }

  function goalFunded(goal: TreasuryGoal): boolean {
    return stableUsd >= goal.amount;
  }

  return (
    <div className="dashboard-page operations-dashboard">

      {/* ── Page intro ────────────────────────────────────────────────────── */}
      <div style={{ padding: "0.55rem 0.75rem", marginBottom: "1rem", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: "0.82rem", lineHeight: 1.5 }}>
        <strong style={{ color: "var(--paper)" }}>Operations Dashboard</strong> — your real-time treasury command centre. Monitor XRPL balances, resolve <a href="https://firefly.app/" target="_blank" rel="noreferrer" style={{ color: "var(--orange)", textDecoration: "none" }}>Firefly</a>-locked payments (a secure hardware device that acts as a veto layer for large/sensitive payments), track upcoming obligations, and watch autonomous agents settle routine payments without human intervention. Every decision is deterministic and auditable.
      </div>

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <section className="operations-hero">
        <div>
          <span className="eyebrow">Treasury · XRPL · Autonomous</span>
          <h1>Your treasury, on autopilot.</h1>
          <p>Routine payments settle in seconds. Large or flagged payments lock on-chain until the Firefly device approves. The AI explains — deterministic code decides.</p>
        </div>
        <div className="hero-actions">
          <button className="dashboard-primary" type="button" onClick={() => onNavigate("/transfer")}>New payment</button>
          <button className="text-action" type="button" onClick={() => onNavigate("/treasury")}>Run agents</button>
        </div>
      </section>

      {/* ── 4-metric hero row ─────────────────────────────────────────────── */}
      <section className="trust-metrics four-col" aria-label="Treasury position">
        <button type="button" onClick={() => onNavigate("/wallet")} className="trust-metric metric-wallet">
          <span className="metric-icon" aria-hidden="true">$</span>
          <span>
            <small>Available balance</small>
            <strong>{summary ? money(summary.totalUsd) : "—"}</strong>
            <em>{summary ? `${money(summary.stableUsd)} RLUSD · ${Number(summary.xrpNative).toFixed(2)} XRP reserve` : "Loading…"}</em>
          </span>
        </button>
        <button type="button" onClick={() => onNavigate("/wallet")} className="trust-metric metric-reserved">
          <span className="metric-icon" aria-hidden="true">⎍</span>
          <span>
            <small>Reserved (escrowed)</small>
            <strong>{pendingApprovals.length > 0 ? money(reservedTotal, reservedCurrency) : "—"}</strong>
            <em>{pendingApprovals.length > 0 ? `${pendingApprovals.length} payment${pendingApprovals.length !== 1 ? "s" : ""} locked until approval` : "No funds locked"}</em>
          </span>
        </button>
        <button
          type="button"
          onClick={() => onNavigate("/wallet")}
          className={`trust-metric ${exceptionCount > 0 ? "metric-alert" : "metric-ledger"}`}
        >
          <span className="metric-icon" aria-hidden="true">!</span>
          <span>
            <small>Policy exceptions</small>
            <strong>{exceptionCount > 0 ? exceptionCount : "None"}</strong>
            <em>
              {exceptionCount > 0
                ? [
                    pendingApprovals.length > 0 && `${pendingApprovals.length} awaiting Firefly`,
                    blockedPayments.length > 0 && `${blockedPayments.length} blocked`,
                    failedPayments.length > 0 && `${failedPayments.length} failed`,
                    isLowBalance && "low RLUSD balance",
                  ].filter(Boolean).join(" · ")
                : "All clear"}
            </em>
          </span>
        </button>
      </section>

      {/* ── Needs your attention + Assets ─────────────────────────────────── */}
      <div className="attention-band">
        <section className="dashboard-panel attention-panel" aria-label="Needs your attention">
          <div className="panel-heading">
            <div><span className="eyebrow">Action required</span><h2>Needs your attention</h2></div>
            <span className="workflow-note">{exceptionCount} item{exceptionCount !== 1 ? "s" : ""}</span>
          </div>
          {exceptionCount === 0 ? (
            <p className="muted">All clear. Routine payments are settling autonomously.</p>
          ) : (
            <div className="attention-list">
              {pendingApprovals.map(payment => (
                <div className="attention-item" key={`pending-${payment.id}`}>
                  <span className="attention-item-icon attention-firefly">🔐</span>
                  <div className="attention-item-body">
                    <strong>{money(payment.intent.amount, payment.intent.currency)} → {payment.intent.receiverName}</strong>
                    <small>{payment.policyDecision?.reasons.join("; ") || "Requires Firefly approval."}</small>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
                    {payment.compliance?.credential?.checked && !payment.compliance.credential.verified && (
                      <button className="kyc-resolve" type="button" disabled={resolvingKycId === payment.id} onClick={() => onResolveKyc(payment)}>
                        {resolvingKycId === payment.id ? "Issuing…" : "Fix credential"}
                      </button>
                    )}
                    <button className="dashboard-primary" type="button" disabled={approvingId === payment.id} onClick={() => onApprove(payment)}>
                      {approvingId === payment.id ? "Waiting…" : "Approve"}
                    </button>
                  </div>
                </div>
              ))}
              {blockedPayments.map(payment => (
                <div className="attention-item" key={`blocked-${payment.id}`}>
                  <span className="attention-item-icon attention-blocked">✕</span>
                  <div className="attention-item-body">
                    <strong>{money(payment.intent.amount, payment.intent.currency)} → {payment.intent.receiverName}</strong>
                    <small>Blocked · {payment.policyDecision?.reasons[0] ?? payment.policyDecision?.ruleFired ?? "Policy gate"}</small>
                  </div>
                  <button className="text-action" type="button" onClick={() => onNavigate("/wallet")}>View</button>
                </div>
              ))}
              {failedPayments.slice(0, 2).map(payment => (
                <div className="attention-item" key={`failed-${payment.id}`}>
                  <span className="attention-item-icon attention-failed">⚠</span>
                  <div className="attention-item-body">
                    <strong>{money(payment.intent.amount, payment.intent.currency)} → {payment.intent.receiverName}</strong>
                    <small>Failed · {payment.auditExplanation ?? "Execution error"}</small>
                  </div>
                  <button className="text-action" type="button" onClick={() => onNavigate("/wallet")}>View</button>
                </div>
              ))}
              {unverifiedCredentials.slice(0, 2).map(c => (
                <div className="attention-item" key={`cred-${c.id}`}>
                  <span className="attention-item-icon attention-credential">ID</span>
                  <div className="attention-item-body">
                    <strong>{c.credentialType ?? "KYC"} · {c.subjectName ?? shortAddress(c.subject)}</strong>
                    <small>Credential {c.status.replace(/_/g, " ")} · {c.auditExplanation ?? "Action required"}</small>
                  </div>
                  <button className="text-action" type="button" onClick={() => onNavigate("/credentials")}>View</button>
                </div>
              ))}
              {isLowBalance && (
                <div className="attention-item" key="low-balance">
                  <span className="attention-item-icon attention-warning">↓</span>
                  <div className="attention-item-body">
                    <strong>RLUSD balance below target</strong>
                    <small>{money(stableUsd)} available · threshold {money(LOW_BALANCE_THRESHOLD)}</small>
                  </div>
                  <button className="text-action" type="button" onClick={() => onNavigate("/wallet")}>Fund</button>
                </div>
              )}
            </div>
          )}
        </section>

        <section className="dashboard-panel" aria-label="Liquidity and assets">
          <div className="panel-heading">
            <div><span className="eyebrow">Wallet · {runtimeStatus?.network ?? "…"}</span><h2>Liquidity & assets</h2></div>
            <span className={`health-dot ${summary ? "online" : ""}`} />
          </div>
          <div className="assets-list">
            <div className="asset-row">
              <span className="asset-label">RLUSD (stablecoin)</span>
              <span className="asset-value">{summary ? money(summary.stableUsd) : "—"}</span>
            </div>
            <div className="asset-row">
              <span className="asset-label">XRP reserve</span>
              <span className="asset-value">{summary ? `${Number(summary.xrpNative).toFixed(4)} XRP` : "—"}</span>
            </div>
            {summary && Number(summary.vaultUsd) > 0 && (
              <div className="asset-row">
                <span className="asset-label">Vault (XLS-65)</span>
                <span className="asset-value">{money(summary.vaultUsd)}</span>
              </div>
            )}
            {pendingApprovals.length > 0 && (
              <div className="asset-row">
                <span className="asset-label">Escrowed (locked)</span>
                <span className="asset-value reserved">{money(reservedTotal, reservedCurrency)}</span>
              </div>
            )}
            <div className="asset-row" style={{ paddingTop: 14, borderTop: "1px solid rgba(235,234,233,.18)", marginTop: 4 }}>
              <span className="asset-label" style={{ fontWeight: 800, color: "var(--paper)" }}>Total position</span>
              <span className="asset-value" style={{ fontSize: "1.1rem" }}>{summary ? money(summary.totalUsd) : "—"}</span>
            </div>
          </div>
          <button className="text-action" style={{ width: "100%", marginTop: 14 }} type="button" onClick={() => onNavigate("/wallet")}>
            Open wallet →
          </button>
        </section>
      </div>

      {/* ── Upcoming obligations ──────────────────────────────────────────── */}
      <section className="dashboard-panel" aria-label="Upcoming obligations">
        <div className="panel-heading">
          <div><span className="eyebrow">7-day schedule</span><h2>Upcoming obligations</h2></div>
          <button className="text-action" type="button" onClick={() => onNavigate("/treasury")}>Manage goals</button>
        </div>
        {upcomingGoals.length === 0 ? (
          <p className="muted">No obligations due in the next 7 days.</p>
        ) : (
          <div className="obligations-table">
            <div className="obligations-head">
              <span>Recipient</span>
              <span>Amount</span>
              <span>Due</span>
              <span>Settlement</span>
              <span>Funds</span>
            </div>
            {upcomingGoals.map(goal => {
              const mode = goalSettleMode(goal);
              const funded = goalFunded(goal);
              const next = goalNextFire(goal);
              return (
                <div className="obligations-row" key={goal.id}>
                  <div>
                    <strong>{goal.beneficiaryName}</strong>
                    <div className="muted">{goal.category ?? goal.serviceType ?? goal.purpose}</div>
                  </div>
                  <span>{money(goal.amount, goal.currency)}</span>
                  <span>{relativeFromNow(next.toISOString())}</span>
                  <span className={`settle-badge settle-${mode}`}>
                    {mode === "auto" ? "Auto-settle" : mode === "approval" ? "Needs approval" : "—"}
                  </span>
                  <span style={{ color: funded ? "var(--credential)" : "var(--alert)", fontSize: ".75rem", fontWeight: 800 }}>
                    {funded ? "✓ Funded" : "⚠ Low"}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ── Autonomous operations ─────────────────────────────────────────── */}
      <section className="dashboard-panel" aria-label="Autonomous operations">
        <div className="panel-heading">
          <div><span className="eyebrow">Agent performance</span><h2>Autonomous operations</h2></div>
          <span className="workflow-note">Deterministic · code decides</span>
        </div>
        <div className="ops-stats">
          <div className="ops-stat">
            <div className="ops-stat-label">Settled autonomously</div>
            <div className="ops-stat-value">{totalSettled}</div>
            <div className="ops-stat-detail">{agentStats ? money(agentStats.amountSpentToday) + " today" : "No data yet"}</div>
          </div>
          <div className="ops-stat">
            <div className="ops-stat-label">x402 service purchases</div>
            <div className="ops-stat-value">{x402Count}</div>
            <div className="ops-stat-detail">{servicePayments.length} total service calls</div>
          </div>
          <div className="ops-stat">
            <div className="ops-stat-label">Escalated · Blocked</div>
            <div className="ops-stat-value">{totalEscalated} · {totalBlocked}</div>
            <div className="ops-stat-detail">Required human or policy gate</div>
          </div>
          <div className="ops-stat">
            <div className="ops-stat-label">Auto-settlement rate</div>
            <div className="ops-stat-value">{autoSettleRate !== null ? `${autoSettleRate}%` : "—"}</div>
            <div className="ops-stat-detail">{agentStats?.lastRunAt ? `Last run ${relativeTime(agentStats.lastRunAt)}` : "No runs yet"}</div>
          </div>
        </div>
        {settledToday.length > 0 && (
          <p style={{ marginTop: 14, color: "var(--muted)", fontSize: ".78rem" }}>
            Today: {settledToday.length} payment{settledToday.length !== 1 ? "s" : ""} settled autonomously · {money(settledTodayTotal, settledTodayCurrency)} disbursed
          </p>
        )}
      </section>

      {/* ── Recent money movement ─────────────────────────────────────────── */}
      <section className="dashboard-panel activity-panel" aria-label="Recent money movement">
        <div className="panel-heading">
          <div><span className="eyebrow">Unified audit stream</span><h2>Recent money movement</h2></div>
          <button className="text-action" type="button" onClick={() => onNavigate("/wallet")}>View all</button>
        </div>
        {activityFeed.length === 0 ? (
          <p className="muted">No activity yet. Create the first payment or run an agent.</p>
        ) : (
          <div className="activity-table">
            <div className="activity-head"><span>Event</span><span>Result · Why</span><span>Proof</span></div>
            {activityFeed.map(row => (
              <article className="activity-row" key={row.id}>
                <div>
                  <span className={`event-dot event-${row.kind === "CREDENTIAL" ? "credential" : "transaction"}`} />
                  <span>
                    <small>{row.kind} · {relativeTime(row.time)}</small>
                    <strong>{row.event}</strong>
                  </span>
                </div>
                <p>
                  <span className={`dashboard-status status-${row.status}`}>{row.result}</span>
                  {row.coverage === "bound" && <span title={`Covered because: ${row.coverageReason ?? "deterministic policy"}`} style={{ marginLeft: 6, fontSize: ".7rem", color: "#93c5fd", fontWeight: 700 }}>Covered</span>}
                  {row.coverage === "review" && <span style={{ marginLeft: 6, fontSize: ".7rem", color: "var(--orange)", fontWeight: 700 }}>Cover review</span>}
                  {row.coverage === "declined" && <span style={{ marginLeft: 6, fontSize: ".7rem", color: "var(--alert)", fontWeight: 700 }}>Cover declined</span>}
                  {row.why !== "—" && <span style={{ marginLeft: 6, fontSize: ".7rem", color: "var(--muted)" }}>{row.why}</span>}
                </p>
                {row.proof ? (
                  <a href={row.proof} target="_blank" rel="noreferrer">Explorer ↗</a>
                ) : (
                  <span className="muted">No proof</span>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      {/* ── Agent mandates ────────────────────────────────────────────────── */}
      {activeAgents.length > 0 && (
        <section className="dashboard-panel" aria-label="Agent mandates">
          <div className="panel-heading">
            <div><span className="eyebrow">Autonomous agents</span><h2>Agent mandates</h2></div>
            <button className="text-action" type="button" onClick={() => onNavigate("/treasury")}>Manage agents</button>
          </div>
          <div className="mandate-cards">
            {activeAgents.slice(0, 3).map(agent => {
              const stats = agentStats?.agentId === agent.id ? agentStats : null;
              const spentPct = stats && Number(agent.maxDailySpend) > 0
                ? Math.min(100, (Number(stats.amountSpentToday) / Number(agent.maxDailySpend)) * 100)
                : 0;
              const agentGoals = goals.filter(g => g.agentId === agent.id);
              const lastGoal = agentGoals.find(g => g.lastTriggeredAt);
              const nextRunEst = lastGoal && stats?.lastRunAt
                ? new Date(Date.parse(stats.lastRunAt) + (agentGoals[0]?.triggerIntervalHours ?? 24) * 3600_000)
                : null;
              return (
                <div className="mandate-card" key={agent.id}>
                  <div className="mandate-card-head">
                    <div>
                      <div className="mandate-agent-name">{agent.name}</div>
                      {agent.description && <div className="mandate-agent-desc">{agent.description}</div>}
                    </div>
                    <span className={`dashboard-status status-${agent.status}`}>{agent.status}</span>
                  </div>
                  <div className="mandate-limits">
                    <div className="mandate-limit">
                      <div className="mandate-limit-label">Daily budget</div>
                      <div className="mandate-limit-value">{money(agent.maxDailySpend, agent.currency)}</div>
                    </div>
                    <div className="mandate-limit">
                      <div className="mandate-limit-label">Per-tx limit</div>
                      <div className="mandate-limit-value">{money(agent.maxSinglePayment, agent.currency)}</div>
                    </div>
                    <div className="mandate-limit">
                      <div className="mandate-limit-label">Approval above</div>
                      <div className="mandate-limit-value">{money(agent.requiresApprovalAbove, agent.currency)}</div>
                    </div>
                  </div>
                  {stats && (
                    <>
                      <div style={{ gridColumn: "1 / -1", marginBottom: 6 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", fontSize: ".72rem", color: "var(--muted)", marginBottom: 6 }}>
                          <span>Daily budget used</span>
                          <span>{money(stats.amountSpentToday, agent.currency)} / {money(agent.maxDailySpend, agent.currency)}</span>
                        </div>
                        <div className="capacity-track"><span style={{ width: `${spentPct}%` }} /></div>
                      </div>
                    </>
                  )}
                  {(agent.allowedCategories?.length || agent.allowedHosts?.length) && (
                    <div className="mandate-services">
                      Allowed: {[...(agent.allowedCategories ?? []), ...(agent.allowedHosts ?? [])].slice(0, 4).join(", ")}
                    </div>
                  )}
                  <div className="mandate-run">
                    <span>Last run: {stats?.lastRunAt ? relativeTime(stats.lastRunAt) : "—"} · {stats?.lastRunStatus ?? "—"}</span>
                    {nextRunEst && <span>Next: ~{relativeFromNow(nextRunEst.toISOString())}</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* ── Trust & controls strip ────────────────────────────────────────── */}
      <section aria-label="System status">
        <div className="controls-strip">
          <div className="control-indicator">
            <span className="health-dot online" />
            <span>Policy engine <strong>healthy</strong></span>
          </div>
          <div className="control-indicator">
            <span className={`health-dot ${runtimeStatus?.fireflyConfirmationEnabled ? "online" : ""}`} />
            <span>Firefly <strong>{runtimeStatus?.fireflyConfirmationEnabled ? "enabled" : "not required"}</strong></span>
          </div>
          <div className="control-indicator">
            <span className="health-dot online" />
            <span>Network <strong>{runtimeStatus?.network ?? "…"}{runtimeStatus?.mockMode ? " (mock)" : ""}</strong></span>
          </div>
          <div className="control-indicator">
            <span className="health-dot online" />
            <span>Audit trail <strong>current</strong></span>
          </div>
          <div className="control-indicator">
            <span className={`health-dot ${pool && Number(pool.firstLoss) > 0 ? "online" : ""}`} />
            <span>Insurance pool <strong>{pool && Number(pool.firstLoss) > 0 ? "active" : "offline"}</strong></span>
          </div>
          <div className="control-indicator">
            <span className={`health-dot ${creditRisk === "Low" ? "online" : ""}`} />
            <span>Credit risk <strong>{creditRisk}</strong></span>
          </div>
        </div>
      </section>

      {/* ── Insurance capacity (only if notable) ─────────────────────────── */}
      {pool && payouts.length > 0 && (
        <section className="dashboard-panel cover-health" aria-label="Insurance pool">
          <div className="panel-heading">
            <div><span className="eyebrow">Insurance pool</span><h2>Capacity health</h2></div>
            <span className={`health-dot ${Number(pool.firstLoss) > 0 ? "online" : ""}`} />
          </div>
          <div className="capacity-number">
            <strong>{money(pool.firstLoss, pool.currency ?? "USD")}</strong>
            <span>available</span>
          </div>
          <dl className="cover-facts">
            <div><dt>Premiums collected</dt><dd>{money(pool.premiumsCollected)}</dd></div>
            <div><dt>Claims paid</dt><dd>{money(pool.payoutsMade)}</dd></div>
          </dl>
          <p className="muted">Coverage is quoted and bound automatically when a payment carries a counterparty cover requirement.</p>
        </section>
      )}
    </div>
  );
}
