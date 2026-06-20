import { useCallback, useEffect, useMemo, useState, type ChangeEvent } from "react";
import type { MPTStatus, Payment, TreasuryAgentRun, TreasuryGoal, TreasuryGoalCreate, VaultStatus } from "@treasury/shared";

import { api } from "../lib/api.js";
import { hashShort, money } from "../lib/utils.js";

// XRP-only: the agent transacts natively in XRP so there is no FX step.
const CURRENCIES = ["XRP"];
type BusyKey = "goal" | "run" | "vault" | "mpt";

// Payments above this lock on-chain and require a physical Firefly approval —
// mirrors POLICY_THRESHOLD_USD on the backend. These are the agentic
// transactions whose step trail matters most to a reviewer.
const FIREFLY_THRESHOLD = 500;

const STATUS_LABEL: Record<Payment["status"], string> = {
  routing: "Routing",
  settled: "Settled",
  pending_approval: "Locked · Firefly",
  released: "Released",
  blocked: "Refused",
  failed: "Failed",
};

type StepState = "pass" | "flag" | "block" | "info";
interface TxStep {
  label: string;
  detail: string;
  state: StepState;
}

// Derive the deterministic decision pipeline from a payment so the agentic side
// shows *what* the agent did and *why*, not just that a goal fired.
function buildSteps(p: Payment): TxStep[] {
  const steps: TxStep[] = [];
  const { intent, routeQuote: route, compliance, policyDecision: policy, status } = p;

  if (route) {
    steps.push({
      label: "Route",
      detail: `${route.pathSummary}${route.sendMax != null ? ` · SendMax ${route.sendMax.toLocaleString()}` : ""}`,
      state: "info",
    });
  }

  if (compliance) {
    const kyc = compliance.credential?.checked
      ? compliance.credential.verified ? " · KYC verified" : " · KYC missing"
      : "";
    const top = compliance.sanctionsMatches[0];
    steps.push({
      label: "Compliance",
      detail: `AML ${compliance.amlScore}/100 · ${compliance.explanation}${kyc}${top ? ` · OpenSanctions ${Math.round(top.score * 100)}%` : ""}`,
      state: compliance.sanctioned ? "block" : compliance.flags.length > 0 ? "flag" : "pass",
    });
  }

  if (policy) {
    if (policy.blocked) {
      steps.push({ label: "Policy", detail: policy.blockReason ?? "Blocked outright", state: "block" });
    } else if (policy.requiresApproval) {
      steps.push({
        label: "Policy",
        detail: `Escalated (${policy.ruleFired ?? "rule"}) — ${policy.reasons.join("; ")}`,
        state: "flag",
      });
    } else {
      steps.push({
        label: "Policy",
        detail: `Auto-settle — at/below ${FIREFLY_THRESHOLD} ${intent.currency} threshold, low risk`,
        state: "pass",
      });
    }
  }

  if (status === "settled" || status === "released") {
    steps.push({ label: "Settlement", detail: "Delivered on-ledger", state: "pass" });
  } else if (status === "pending_approval") {
    steps.push({
      label: "Firefly veto",
      detail: `Locked in escrow${p.escrowSequence != null ? ` (seq ${p.escrowSequence})` : ""} — awaiting physical hardware approval`,
      state: "flag",
    });
  } else if (status === "blocked") {
    steps.push({ label: "Settlement", detail: "Not executed — blocked", state: "block" });
  } else if (status === "failed") {
    steps.push({ label: "Settlement", detail: "Submission failed", state: "block" });
  } else {
    steps.push({ label: "Settlement", detail: "Routing…", state: "info" });
  }

  return steps;
}

const STEP_SYMBOL: Record<StepState, string> = { pass: "✓", flag: "⚠", block: "✗", info: "•" };

function AgenticTxCard({ payment }: { payment: Payment }) {
  const { intent, status } = payment;
  const large = intent.amount > FIREFLY_THRESHOLD;
  const steps = buildSteps(payment);
  return (
    <article className={`agentic-tx status-${status}`}>
      <header className="agentic-tx-head">
        <strong>{intent.amount.toLocaleString()} {intent.currency}</strong>
        <span className="badge">{STATUS_LABEL[status]}</span>
        {large && (
          <span className="firefly-tag">🔒 &gt;{FIREFLY_THRESHOLD} {intent.currency} · Firefly hardware veto</span>
        )}
      </header>
      <p className="muted agentic-buying">
        Buying: <strong>{intent.purpose.replace(/_/g, " ")}</strong> · {intent.reference} → {intent.receiverName} ({intent.receiverCountry})
      </p>
      <ol className="agentic-steps">
        {steps.map((s, i) => (
          <li key={i} className={`agentic-step step-${s.state}`}>
            <span className="step-mark">{STEP_SYMBOL[s.state]}</span>
            <span className="step-label">{s.label}</span>
            <span className="step-detail">{s.detail}</span>
          </li>
        ))}
      </ol>
      {payment.auditExplanation && <p className="audit">{payment.auditExplanation}</p>}
      {payment.explorerUrl && (
        <a href={payment.explorerUrl} target="_blank" rel="noreferrer" className="agentic-tx-link">
          View on explorer ↗
        </a>
      )}
    </article>
  );
}

const DEFAULT_GOAL: TreasuryGoalCreate = {
  name: "Monthly supplier payment",
  beneficiaryName: "Acme Supplies AG",
  // Funded Devnet counterparty (activated account → payment lands; no tecNO_DST).
  // Replace with your own funded beneficiary when you change networks.
  beneficiaryAddress: "rBBHb3oX4JxoGRU28X94iDRiZUPU8Xu7ur",
  beneficiaryCountry: "US",
  receiverEntityType: "company",
  amount: 1000,
  currency: "XRP",
  reference: "INV-AUTO-001",
  purpose: "supplier_payment",
  triggerIntervalHours: 0.001, // ~3.6 s — fires immediately for demo
};

export function TreasuryPage() {
  const [goals, setGoals] = useState<TreasuryGoal[]>([]);
  const [runs, setRuns] = useState<TreasuryAgentRun[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [vault, setVault] = useState<VaultStatus | null>(null);
  const [mpt, setMpt] = useState<MPTStatus | null>(null);
  const [form, setForm] = useState<TreasuryGoalCreate>(DEFAULT_GOAL);
  const [vaultAmount, setVaultAmount] = useState<number>(10_000);
  const [mptHolder, setMptHolder] = useState<string>("");
  const [busy, setBusy] = useState<Record<BusyKey, boolean>>({
    goal: false,
    run: false,
    vault: false,
    mpt: false,
  });
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [g, r, p, v, m] = await Promise.all([
        api.listTreasuryGoals(),
        api.listTreasuryRuns(),
        api.listPayments().catch(() => [] as Payment[]),
        api.getVaultStatus().catch(() => null),
        api.getMptStatus().catch(() => null),
      ]);
      setGoals(g);
      setRuns(r);
      setPayments(p);
      setVault(v);
      setMpt(m);
    } catch (cause) {
      setError(String(cause));
    }
  }, []);

function ts() {
  return new Date().toISOString().slice(11, 19);
}

function isSettled(status: string) {
  return status === "settled" || status === "released";
}

// ── Pool status strip ─────────────────────────────────────────────────────────

function PoolStrip({ pool }: { pool: PoolStatus | null }) {
  if (!pool?.enabled) return null;
  return (
    <div style={{
      display: "flex",
      gap: "2rem",
      flexWrap: "wrap",
      padding: "0.75rem 1.25rem",
      background: "rgba(255,255,255,0.03)",
      border: "1px solid var(--border)",
      borderRadius: 10,
      marginBottom: "1.5rem",
      alignItems: "center",
    }}>
      <span className="eyebrow" style={{ marginRight: "0.5rem" }}>Insurance pool</span>
      {[
        ["Capacity", `${money(pool.availableCapacity)} ${pool.currency}`],
        ["Premiums", `${money(pool.premiumsCollected)} ${pool.currency}`],
        ["Claims paid", `${money(pool.claimsPaid)} ${pool.currency}`],
      ].map(([label, value]) => (
        <div key={label} style={{ display: "flex", gap: "0.4rem", alignItems: "baseline" }}>
          <span className="muted" style={{ fontSize: "0.72rem" }}>{label}</span>
          <strong style={{ fontSize: "0.9rem" }}>{value}</strong>
        </div>
      ))}
    </div>
  );
}

// ── Log line types ────────────────────────────────────────────────────────────

interface LogLine {
  id: number;
  kind: "info" | "success" | "error" | "insurance" | "tx" | "heading";
  text: string;
  txHash?: string;
  explorerUrl?: string;
}

function LogPanel({ lines, running }: { lines: LogLine[]; running: boolean }) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  return (
    <div style={{
      background: "rgba(0,0,0,0.35)",
      border: "1px solid var(--border)",
      borderRadius: 12,
      height: "100%",
      minHeight: 480,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
    }}>
      <div style={{
        padding: "0.6rem 1rem",
        borderBottom: "1px solid var(--border)",
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
      }}>
        <span className="eyebrow">Agent log</span>
        {running && (
          <span style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.4rem",
            fontSize: "0.72rem",
            color: "var(--orange)",
            fontWeight: 800,
          }}>
            <span style={{ animation: "pulse 1s infinite", display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "var(--orange)" }} />
            RUNNING
          </span>
        )}
        {!running && lines.length > 0 && (
          <span className="muted" style={{ fontSize: "0.7rem" }}>{lines.length} events</span>
        )}
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0.75rem 1rem", fontFamily: "monospace", fontSize: "0.78rem" }}>
        {lines.length === 0 && (
          <p className="muted" style={{ marginTop: "2rem", textAlign: "center" }}>
            Click "Run Agent Now" to watch the agent work.
          </p>
        )}
        {lines.map((line) => (
          <div key={line.id} style={{
            padding: "0.2rem 0",
            borderBottom: line.kind === "heading" ? "1px solid rgba(255,255,255,0.06)" : "none",
            marginBottom: line.kind === "heading" ? "0.3rem" : 0,
          }}>
            {line.kind === "heading" && (
              <span style={{ color: "var(--orange)", fontWeight: 800, fontSize: "0.82rem" }}>{line.text}</span>
            )}
            {line.kind === "info" && (
              <span style={{ color: "var(--muted)" }}>{line.text}</span>
            )}
            {line.kind === "success" && (
              <span style={{ color: "#6ee7b7" }}>{line.text}</span>
            )}
            {line.kind === "error" && (
              <span style={{ color: "var(--orange)" }}>{line.text}</span>
            )}
            {line.kind === "insurance" && (
              <span style={{ color: "#93c5fd" }}>{line.text}</span>
            )}
            {line.kind === "tx" && (
              <span>
                <span style={{ color: "#6ee7b7" }}>{line.text} </span>
                {line.txHash && line.explorerUrl && (
                  <a href={line.explorerUrl} target="_blank" rel="noreferrer"
                    style={{ color: "var(--orange)", fontWeight: 700, fontSize: "0.75rem", display: "inline", margin: 0 }}>
                    {hashShort(line.txHash)} ↗
                  </a>
                )}
                {line.txHash && !line.explorerUrl && (
                  <code style={{ color: "var(--muted)", fontSize: "0.72rem" }}>{hashShort(line.txHash)} (simulated)</code>
                )}
              </span>
            )}
          </div>
        ))}
        <div ref={bottom} />
      </div>
    </div>
  );
}

// ── Payment outcome card ──────────────────────────────────────────────────────

function PaymentOutcomeCard({
  payment,
  premium,
  onClaim,
  claiming,
}: {
  payment: Payment;
  premium: InsurancePremiumRecord | undefined;
  onClaim: (p: Payment) => void;
  claiming: boolean;
}) {
  const statusColor =
    isSettled(payment.status) ? "#6ee7b7"
    : payment.status === "pending_approval" ? "var(--orange)"
    : payment.status === "blocked" ? "#f87171"
    : "var(--muted)";

  const cover = payment.cover;

  const paymentsById = useMemo(() => new Map(payments.map((p) => [p.id, p])), [payments]);

  return (
    <div style={{
      border: "1px solid var(--border)",
      borderRadius: 12,
      padding: "1rem 1.25rem",
      background: "rgba(255,255,255,0.03)",
      display: "grid",
      gap: "0.5rem",
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <strong style={{ fontSize: "1rem" }}>
            {money(payment.intent.amount)} {payment.intent.currency}
          </strong>
          <span className="muted" style={{ marginLeft: "0.5rem", fontSize: "0.8rem" }}>
            to {payment.intent.receiverName} ({payment.intent.receiverCountry})
          </span>
        </div>
        <span style={{
          fontSize: "0.72rem",
          fontWeight: 800,
          color: statusColor,
          border: `1px solid ${statusColor}`,
          borderRadius: 999,
          padding: "0.1rem 0.6rem",
        }}>
          {payment.status.toUpperCase()}
        </span>
      </div>

      <div className="muted" style={{ fontSize: "0.74rem" }}>
        {payment.intent.purpose} · ref {payment.intent.reference} · id {payment.id.slice(0, 8)}...
      </div>

      {/* Insurance row */}
      {cover && (
        <div style={{
          background: cover.decision === "OFFER" ? "rgba(147,197,253,0.07)" : "rgba(255,255,255,0.03)",
          border: "1px solid rgba(147,197,253,0.2)",
          borderRadius: 8,
          padding: "0.5rem 0.75rem",
          display: "flex",
          alignItems: "center",
          gap: "1rem",
          flexWrap: "wrap",
        }}>
          <span style={{ fontSize: "0.8rem" }}>
            {cover.decision === "OFFER" ? "🛡" : cover.decision === "REVIEW" ? "⚠" : "✗"}
          </span>
          <span style={{ fontSize: "0.8rem", color: "#93c5fd", fontWeight: 700 }}>
            Cover {cover.decision}
          </span>
          {cover.decision === "OFFER" && (
            <span style={{ fontSize: "0.8rem" }}>
              <strong>{money(cover.premium)} USD</strong>
              <span className="muted"> premium</span>
            </span>
          )}
          <span className="muted" style={{ fontSize: "0.72rem" }}>
            PD {(cover.pd * 100).toFixed(3)}% · cred {(cover.credibility * 100).toFixed(1)}%
          </span>
          {premium?.txHash && (
            <span style={{ fontSize: "0.75rem" }}>
              <span className="muted">Premium tx: </span>
              <a href={premium.explorerUrl ?? "#"} target="_blank" rel="noreferrer"
                style={{ color: "var(--orange)", fontWeight: 700, display: "inline", margin: 0 }}>
                {hashShort(premium.txHash)} ↗
              </a>
            </span>
          )}
          {premium && !premium.txHash && (
            <span className="muted" style={{ fontSize: "0.72rem" }}>Premium tx: simulated</span>
          )}
        </div>
      )}

      {/* Settlement tx row */}
      {payment.txHash && (
        <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", fontSize: "0.78rem" }}>
          <span>
            <span className="muted">Settlement: </span>
            {payment.explorerUrl
              ? <a href={payment.explorerUrl} target="_blank" rel="noreferrer"
                  style={{ color: "var(--orange)", fontWeight: 700, display: "inline", margin: 0 }}>
                  {hashShort(payment.txHash)} ↗
                </a>
              : <code style={{ color: "var(--muted)" }}>{hashShort(payment.txHash)} (simulated)</code>
            }
          </span>
          {payment.explorerUrlSecondary && (
            <span>
              <span className="muted">Bithomp: </span>
              <a href={payment.explorerUrlSecondary} target="_blank" rel="noreferrer"
                style={{ color: "var(--orange)", fontWeight: 700, display: "inline", margin: 0 }}>
                verify ↗
              </a>
            </span>
          )}
        </div>
      )}

      {/* Audit narration */}
      {payment.auditExplanation && (
        <p className="audit" style={{ fontSize: "0.76rem", margin: 0 }}>
          {payment.auditExplanation}
        </p>
      )}

      {/* Simulate claim */}
      {isSettled(payment.status) && cover?.decision === "OFFER" && (
        <div style={{ marginTop: "0.25rem" }}>
          <button
            type="button"
            onClick={() => onClaim(payment)}
            disabled={claiming}
            style={{
              padding: "0.25rem 0.75rem",
              fontSize: "0.75rem",
              borderRadius: 6,
              border: "1px solid rgba(248,113,113,0.4)",
              background: "rgba(248,113,113,0.08)",
              color: "#f87171",
              cursor: claiming ? "not-allowed" : "pointer",
              opacity: claiming ? 0.5 : 1,
            }}
          >
            {claiming ? "Filing claim..." : "Simulate claim (merchant default)"}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Claim outcome banner ──────────────────────────────────────────────────────

function ClaimBanner({ payout }: { payout: InsurancePayoutRecord }) {
  return (
    <div style={{
      border: "1px solid rgba(248,113,113,0.4)",
      borderRadius: 12,
      padding: "1rem 1.25rem",
      background: "rgba(248,113,113,0.06)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
        <span style={{ color: "#f87171", fontWeight: 800 }}>Claim settled</span>
        <span className="muted" style={{ fontSize: "0.8rem" }}>
          {money(payout.totalPaid)} {payout.currency} paid to merchant
        </span>
        <span style={{
          fontSize: "0.72rem",
          padding: "0.1rem 0.5rem",
          borderRadius: 999,
          border: "1px solid #6ee7b7",
          color: "#6ee7b7",
          fontWeight: 700,
        }}>
          {payout.reputationMptProtected ? "Reputation PROTECTED" : "Reputation burned"}
        </span>
      </div>
      <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", fontSize: "0.78rem" }}>
        <span className="muted">
          Collateral slashed: <strong style={{ color: "var(--text)" }}>{money(payout.collateralSlashed)}</strong>
        </span>
        <span className="muted">
          Pool drawn: <strong style={{ color: "var(--text)" }}>{money(payout.poolDrawn)}</strong>
        </span>
        {payout.slashTxHash && (
          <span>
            <span className="muted">Slash tx: </span>
            <a href="#" target="_blank" rel="noreferrer"
              style={{ color: "var(--orange)", fontWeight: 700, display: "inline", margin: 0 }}>
              {hashShort(payout.slashTxHash)} ↗
            </a>
          </span>
        )}
        {payout.poolDrawTxHash && (
          <span>
            <span className="muted">Pool draw tx: </span>
            <a href="#" target="_blank" rel="noreferrer"
              style={{ color: "var(--orange)", fontWeight: 700, display: "inline", margin: 0 }}>
              {hashShort(payout.poolDrawTxHash)} ↗
            </a>
          </span>
        )}
      </div>
    </div>
  );
}

// ── Goals sidebar ─────────────────────────────────────────────────────────────

function GoalsSidebar({
  goals,
  onAdd,
  onDelete,
  onRun,
  running,
  busy,
}: {
  goals: TreasuryGoal[];
  onAdd: (g: TreasuryGoalCreate) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onRun: () => void;
  running: boolean;
  busy: boolean;
}) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<TreasuryGoalCreate>(DEMO_GOALS[0]);
  const [adding, setAdding] = useState(false);

  const fieldChange = (key: keyof TreasuryGoalCreate) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((p) => ({ ...p, [key]: e.target.type === "number" ? Number(e.target.value) : e.target.value }));

  const runAdd = async (g: TreasuryGoalCreate, closeForm = false) => {
    setAdding(true);
    try { await onAdd(g); if (closeForm) setShowForm(false); }
    finally { setAdding(false); }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {/* Run button — the main CTA */}
      <button
        type="button"
        className="primary-action"
        disabled={running || busy || goals.length === 0}
        onClick={onRun}
        style={{ fontSize: "1rem", letterSpacing: "0.02em" }}
      >
        {running ? "Agent running..." : "Run Agent Now"}
      </button>

      {/* Active goals */}
      <section className="queue" style={{ marginTop: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
          <h2 style={{ margin: 0, fontSize: "0.9rem" }}>Goals ({goals.length})</h2>
          <button type="button" className="text-action"
            style={{ fontSize: "0.75rem", minHeight: "unset", padding: "0.2rem 0.5rem" }}
            onClick={() => setShowForm(!showForm)}>
            {showForm ? "cancel" : "+ add"}
          </button>
        </div>

        {/* Active goals */}
        <section className="queue">
          <h2>Active goals ({goals.length})</h2>
          {goals.length === 0 && <p className="muted">No goals yet. Add one above to get started.</p>}
          {goals.map((goal) => (
            <article className="decision-row" key={goal.id}>
              <div>
                <strong>{goal.name}</strong>
                <p className="muted">
                  {goal.amount.toLocaleString()} {goal.currency} → {goal.beneficiaryName} ({goal.beneficiaryCountry})
                  · every {goal.triggerIntervalHours}h
                </p>
                <p className="muted">
                  {goal.lastTriggeredAt
                    ? `Last fired: ${new Date(goal.lastTriggeredAt).toLocaleString()}`
                    : "Never triggered"}
                </p>
              </div>
              <div className="decision-actions">
                <span className={`dashboard-status ${goal.enabled ? "status-settled" : "status-blocked"}`}>
                  {goal.enabled ? "Enabled" : "Disabled"}
                </span>
                <button className="text-action" type="button" onClick={() => void deleteGoal(goal.id)}>
                  Remove
                </button>
              </div>
            </article>
          ))}
        </section>

        {/* Run history */}
        <section className="queue">
          <h2>Recent runs ({runs.length})</h2>
          {runs.length === 0 && <p className="muted">No runs yet. Click "Run agent cycle now" above.</p>}
          {runs.map((run) => (
            <article className="decision-row" key={run.id}>
              <div>
                <strong>
                  {run.goalsTriggered}/{run.goalsEvaluated} goals fired
                  <span className={`dashboard-status status-${run.goalsTriggered > 0 ? "settled" : "routing"}`} style={{ marginLeft: "0.5rem" }}>
                    {run.status}
                  </span>
                </strong>
                <p className="muted">{new Date(run.startedAt).toLocaleString()}</p>
                {run.narration && <p className="audit">{run.narration}</p>}
                <ul className="credential-log">
                  {run.triggerLog.map((line, i) => (
                    <li key={i} className="muted">{line}</li>
                  ))}
                </ul>
                {run.paymentsInitiated.length > 0 && (
                  <div className="agentic-tx-list">
                    {run.paymentsInitiated.map((pid) => {
                      const p = paymentsById.get(pid);
                      return p ? <AgenticTxCard key={pid} payment={p} /> : null;
                    })}
                  </div>
                )}
              </div>
            </article>
          ))}
        </section>
        {/* XLS-33 MPTokens */}
        <section className="queue" aria-label="XLS-33 MPTokens">
          <div className="section-heading" style={{ marginBottom: "0.75rem" }}>
            <span className="eyebrow">XLS-33 · MPTokens</span>
            <strong>COMPLY compliance-attestation issuance</strong>
          </div>
        )}

        {goals.map((goal) => (
          <article key={goal.id} style={{
            padding: "0.6rem 0",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: "0.5rem",
          }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: "0.8rem", fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {goal.name}
              </div>
              <div className="muted" style={{ fontSize: "0.72rem" }}>
                {money(goal.amount)} {goal.currency} · {goal.beneficiaryCountry} · every {goal.triggerIntervalHours}h
              </div>
              {goal.lastTriggeredAt && (
                <div className="muted" style={{ fontSize: "0.68rem" }}>
                  last: {new Date(goal.lastTriggeredAt).toLocaleTimeString()}
                </div>
              )}
            </div>
            <button type="button" className="text-action"
              style={{ fontSize: "0.7rem", minHeight: "unset", padding: "0.1rem 0.4rem", flexShrink: 0 }}
              onClick={() => void onDelete(goal.id)}>
              remove
            </button>
          </article>
        ))}

        {showForm && (
          <div style={{ marginTop: "0.75rem", display: "grid", gap: "0.5rem" }}>
            {[
              { key: "name", label: "Name" },
              { key: "beneficiaryName", label: "Beneficiary" },
              { key: "beneficiaryAddress", label: "XRPL address" },
              { key: "reference", label: "Reference" },
            ].map(({ key, label }) => (
              <label key={key} style={{ display: "flex", flexDirection: "column", gap: "0.15rem", fontSize: "0.75rem" }}>
                <span className="muted">{label}</span>
                <input value={String(form[key as keyof TreasuryGoalCreate] ?? "")}
                  onChange={fieldChange(key as keyof TreasuryGoalCreate)}
                  style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.25rem 0.4rem", fontSize: "0.75rem" }} />
              </label>
            ))}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.4rem" }}>
              <label style={{ fontSize: "0.75rem", display: "flex", flexDirection: "column", gap: "0.15rem" }}>
                <span className="muted">Amount</span>
                <input type="number" value={form.amount} onChange={fieldChange("amount")}
                  style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.25rem 0.4rem", fontSize: "0.75rem" }} />
              </label>
              <label style={{ fontSize: "0.75rem", display: "flex", flexDirection: "column", gap: "0.15rem" }}>
                <span className="muted">Interval (h)</span>
                <input type="number" value={form.triggerIntervalHours} onChange={fieldChange("triggerIntervalHours")} step={0.001}
                  style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.25rem 0.4rem", fontSize: "0.75rem" }} />
              </label>
            </div>
            <button type="button" className="primary-action" disabled={adding} onClick={() => void runAdd(form, true)}
              style={{ minHeight: "unset", padding: "0.4rem", fontSize: "0.8rem", borderRadius: 8 }}>
              {adding ? "Adding..." : "Add goal"}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function TreasuryPage() {
  const [goals, setGoals] = useState<TreasuryGoal[]>([]);
  const [pool, setPool] = useState<PoolStatus | null>(null);
  const [logLines, setLogLines] = useState<LogLine[]>([]);
  const [running, setRunning] = useState(false);
  const [runPayments, setRunPayments] = useState<Payment[]>([]);
  const [premiums, setPremiums] = useState<InsurancePremiumRecord[]>([]);
  const [claimResults, setClaimResults] = useState<Record<string, InsurancePayoutRecord>>({});
  const [claimingId, setClaimingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lineId = useRef(0);

  const addLine = useCallback((line: Omit<LogLine, "id">) => {
    setLogLines((prev) => [...prev, { ...line, id: lineId.current++ }]);
  }, []);

  const refresh = useCallback(async () => {
    const [g, p] = await Promise.allSettled([
      api.listTreasuryGoals(),
      api.getInsurancePool().catch(() => null),
    ]);
    if (g.status === "fulfilled") setGoals(g.value);
    if (p.status === "fulfilled") setPool(p.value);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const goalAction = useCallback(async (action: () => Promise<unknown>) => {
    setBusy(true);
    try { await action(); await refresh(); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }, [refresh]);

  const addGoal = useCallback(
    (form: TreasuryGoalCreate) => goalAction(() => api.createTreasuryGoal(form)),
    [goalAction],
  );

  const deleteGoal = useCallback(
    (id: string) => goalAction(() => api.deleteTreasuryGoal(id)),
    [goalAction],
  );

  const runAgent = useCallback(async () => {
    setRunning(true);
    setError(null);
    setRunPayments([]);
    setPremiums([]);
    setClaimResults({});
    setLogLines([]);

    addLine({ kind: "heading", text: `[${ts()}] Agent cycle started` });
    addLine({ kind: "info", text: `Evaluating ${goals.length} goal(s)...` });

    let run: TreasuryAgentRun;
    try {
      run = await api.triggerTreasuryRun();
    } catch (e) {
      addLine({ kind: "error", text: `Run failed: ${String(e)}` });
      setRunning(false);
      return;
    }

    // Kick off fetch immediately — don't wait for the animation to finish
    const fetchPromise = Promise.all([
      api.listPayments().catch(() => [] as Payment[]),
      api.listPremiums().catch(() => [] as InsurancePremiumRecord[]),
    ]);

    // Animate trigger log lines with small delay for visual effect
    for (const line of run.triggerLog) {
      await new Promise((r) => setTimeout(r, 120));
      const lower = line.toLowerCase();
      const isInsurance = lower.includes("insurance") || lower.includes("premium") || lower.includes("cover");
      const isTx = lower.includes("tx ") || lower.includes("tx=");
      const isError = lower.includes("failed") || lower.includes("error");
      const kind = isInsurance ? "insurance" : isTx ? "tx" : isError ? "error" : "info";
      addLine({ kind, text: line });
    }

    const [allPayments, allPremiums] = await fetchPromise;

    const runIds = new Set(run.paymentsInitiated);
    const thisRunPayments = allPayments.filter((p) => runIds.has(p.id));
    const thisRunPremiums = allPremiums.filter((p) => runIds.has(p.jobId));

    setRunPayments(thisRunPayments);
    setPremiums(thisRunPremiums);

    // Log each payment outcome
    addLine({ kind: "heading", text: `[${ts()}] ${run.goalsTriggered} payment(s) initiated` });

    for (const payment of thisRunPayments) {
      addLine({ kind: "info", text: `  ${payment.intent.receiverName} · ${money(payment.intent.amount)} ${payment.intent.currency}` });

      if (payment.cover) {
        const prem = thisRunPremiums.find((p) => p.jobId === payment.id);
        addLine({
          kind: "insurance",
          text: `  Insurance ${payment.cover.decision} · premium ${money(payment.cover.premium)} USD`,
          txHash: prem?.txHash ?? undefined,
          explorerUrl: prem?.explorerUrl ?? undefined,
        });
      }

      if (payment.txHash) {
        addLine({
          kind: "tx",
          text: `  Settlement`,
          txHash: payment.txHash,
          explorerUrl: payment.explorerUrl ?? undefined,
        });
      }

      addLine({
        kind: isSettled(payment.status) ? "success" : "info",
        text: `  Status: ${payment.status.toUpperCase()}`,
      });
    }

    if (run.narration) {
      addLine({ kind: "heading", text: `[${ts()}] Agent narration` });
      addLine({ kind: "info", text: run.narration });
    }

    addLine({ kind: "success", text: `[${ts()}] Cycle complete.` });

    // Refresh pool so numbers update
    await refresh();
    setRunning(false);
  }, [goals.length, addLine, refresh]);

  const simulateClaim = useCallback(async (payment: Payment) => {
    setClaimingId(payment.id);
    addLine({ kind: "heading", text: `[${ts()}] Simulating merchant default on ${payment.intent.receiverName}` });
    try {
      const payout = await api.settleClaim({
        jobId: payment.id,
        agentAddress: payment.intent.from,
        merchant: payment.intent.to,
        merchantName: payment.intent.receiverName,
        merchantCountry: payment.intent.receiverCountry,
        claimAmount: payment.intent.amount.toFixed(6),
        collateralAvailable: "0.000000",
        scoreBand: "STANDARD",
        currency: payment.intent.currency,
      });
      setClaimResults((prev) => ({ ...prev, [payment.id]: payout }));
      addLine({ kind: "error", text: `  Merchant default detected — filing claim...` });
      addLine({
        kind: "insurance",
        text: `  Collateral slashed: ${money(payout.collateralSlashed)} · Pool drawn: ${money(payout.poolDrawn)}`,
        txHash: payout.slashTxHash ?? undefined,
        explorerUrl: undefined,
      });
      addLine({
        kind: "success",
        text: `  Reputation ${payout.reputationMptProtected ? "PROTECTED" : "burned"} — ${money(payout.totalPaid)} ${payout.currency} paid to merchant`,
        txHash: payout.poolDrawTxHash ?? undefined,
      });
      await refresh();
    } catch (e) {
      addLine({ kind: "error", text: `  Claim failed: ${String(e)}` });
    } finally {
      setClaimingId(null);
    }
  }, [addLine, refresh]);

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      {/* Page header */}
      <div style={{ marginBottom: "1rem" }}>
        <span className="eyebrow">Autonomous Treasury Agent</span>
        <h2 style={{ margin: "0.2rem 0 0.25rem" }}>Mission Control</h2>
        <p className="muted">
          The agent evaluates goals, prices insurance, and settles payments autonomously.
          You watch — code decides.
        </p>
      </div>

      {/* Insurance pool strip */}
      <PoolStrip pool={pool} />

      {error && <p className="error" style={{ marginBottom: "1rem" }}>{error}</p>}

      {/* Main 2-column layout */}
      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: "1.5rem", alignItems: "start" }}>

        {/* Left: Goals */}
        <GoalsSidebar
          goals={goals}
          onAdd={addGoal}
          onDelete={deleteGoal}
          onRun={() => void runAgent()}
          running={running}
          busy={busy}
        />

        {/* Right: Live log */}
        <LogPanel lines={logLines} running={running} />
      </div>

      {/* Payment outcomes — full width below */}
      {runPayments.length > 0 && (
        <div style={{ marginTop: "1.5rem" }}>
          <span className="eyebrow" style={{ display: "block", marginBottom: "0.75rem" }}>
            Payment outcomes ({runPayments.length})
          </span>
          <div style={{ display: "grid", gap: "0.75rem" }}>
            {runPayments.map((payment) => (
              <div key={payment.id}>
                <PaymentOutcomeCard
                  payment={payment}
                  premium={premiums.find((p) => p.jobId === payment.id)}
                  onClaim={simulateClaim}
                  claiming={claimingId === payment.id}
                />
                {claimResults[payment.id] && (
                  <div style={{ marginTop: "0.5rem" }}>
                    <ClaimBanner payout={claimResults[payment.id]} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
