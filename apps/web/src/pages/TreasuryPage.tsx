import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import type {
  Agent,
  AgentCreate,
  AgentDashboardStats,
  AgentStatus,
  AgentUpdate,
  InsurancePayoutRecord,
  Payment,
  PoolStatus,
  TreasuryAgentRun,
  TreasuryGoal,
  TreasuryGoalCreate,
} from "@treasury/shared";
import { api } from "../lib/api.js";
import { hashShort, money } from "../lib/utils.js";

function isSettled(s: string) {
  return s === "settled" || s === "released";
}
function ts() {
  return new Date().toISOString().slice(11, 19);
}

// ── Log ───────────────────────────────────────────────────────────────────────

interface LogLine {
  id: number;
  kind: "info" | "success" | "error" | "insurance" | "tx" | "heading";
  text: string;
  txHash?: string;
  explorerUrl?: string;
}

function LogPanel({ lines, running }: { lines: LogLine[]; running: boolean }) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [lines]);
  return (
    <div style={{ background: "rgba(0,0,0,0.35)", border: "1px solid var(--border)", borderRadius: 12, minHeight: 300, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ padding: "0.5rem 1rem", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <span className="eyebrow">Agent log</span>
        {running && <span style={{ fontSize: "0.72rem", color: "var(--orange)", fontWeight: 800 }}>● RUNNING</span>}
        {!running && lines.length > 0 && <span className="muted" style={{ fontSize: "0.7rem" }}>{lines.length} events</span>}
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0.75rem 1rem", fontFamily: "monospace", fontSize: "0.78rem" }}>
        {lines.length === 0 && <p className="muted" style={{ marginTop: "1.5rem", textAlign: "center" }}>Click "Run Agent" to watch the agent work.</p>}
        {lines.map((line) => (
          <div key={line.id} style={{ padding: "0.15rem 0" }}>
            {line.kind === "heading" && <span style={{ color: "var(--orange)", fontWeight: 800 }}>{line.text}</span>}
            {line.kind === "info" && <span style={{ color: "var(--muted)" }}>{line.text}</span>}
            {line.kind === "success" && <span style={{ color: "#6ee7b7" }}>{line.text}</span>}
            {line.kind === "error" && <span style={{ color: "var(--orange)" }}>{line.text}</span>}
            {line.kind === "insurance" && <span style={{ color: "#93c5fd" }}>{line.text}</span>}
            {line.kind === "tx" && (
              <span>
                <span style={{ color: "#6ee7b7" }}>{line.text} </span>
                {line.txHash && line.explorerUrl && (
                  <a href={line.explorerUrl} target="_blank" rel="noreferrer" style={{ color: "var(--orange)", fontWeight: 700, display: "inline", margin: 0 }}>{hashShort(line.txHash)} ↗</a>
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

function PaymentOutcomeCard({ payment, onClaim, claiming }: {
  payment: Payment;
  onClaim: (p: Payment) => void;
  claiming: boolean;
}) {
  const color = isSettled(payment.status) ? "#6ee7b7" : payment.status === "pending_approval" ? "var(--orange)" : payment.status === "blocked" ? "#f87171" : "var(--muted)";
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 12, padding: "1rem 1.25rem", background: "rgba(255,255,255,0.03)", display: "grid", gap: "0.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <strong style={{ fontSize: "1rem" }}>{money(payment.intent.amount)} {payment.intent.currency}</strong>
          <span className="muted" style={{ marginLeft: "0.5rem", fontSize: "0.8rem" }}>→ {payment.intent.receiverName} ({payment.intent.receiverCountry})</span>
        </div>
        <span style={{ fontSize: "0.72rem", fontWeight: 800, color, border: `1px solid ${color}`, borderRadius: 999, padding: "0.1rem 0.6rem" }}>
          {payment.status.toUpperCase().replace("_", " ")}
        </span>
      </div>
      <div className="muted" style={{ fontSize: "0.74rem" }}>{payment.intent.purpose} · ref {payment.intent.reference} · {payment.id.slice(0, 8)}…</div>
      {payment.auditExplanation && <p className="audit" style={{ fontSize: "0.76rem", margin: 0 }}>{payment.auditExplanation}</p>}
      {payment.txHash && (
        <div style={{ fontSize: "0.78rem" }}>
          <span className="muted">Tx: </span>
          {payment.explorerUrl
            ? <a href={payment.explorerUrl} target="_blank" rel="noreferrer" style={{ color: "var(--orange)", fontWeight: 700, display: "inline", margin: 0 }}>{hashShort(payment.txHash)} ↗</a>
            : <code style={{ color: "var(--muted)" }}>{hashShort(payment.txHash)} (simulated)</code>
          }
        </div>
      )}
      {isSettled(payment.status) && payment.cover?.decision === "OFFER" && (
        <button type="button" onClick={() => onClaim(payment)} disabled={claiming}
          style={{ padding: "0.25rem 0.75rem", fontSize: "0.75rem", borderRadius: 6, border: "1px solid rgba(248,113,113,0.4)", background: "rgba(248,113,113,0.08)", color: "#f87171", cursor: claiming ? "not-allowed" : "pointer", opacity: claiming ? 0.5 : 1 }}>
          {claiming ? "Filing claim..." : "Simulate claim (merchant default)"}
        </button>
      )}
    </div>
  );
}

// ── Pool strip ────────────────────────────────────────────────────────────────

function PoolStrip({ pool }: { pool: PoolStatus | null }) {
  if (!pool) return null;
  return (
    <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap", padding: "0.6rem 1rem", background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)", borderRadius: 8, marginBottom: "1rem", alignItems: "center" }}>
      <span className="eyebrow" style={{ marginRight: "0.25rem" }}>Insurance pool</span>
      {[["LP Capital", `${money(pool.lpCapital)} ${pool.currency}`],
        ["Premiums", `${money(pool.premiumsCollected)} ${pool.currency}`],
        ["Payouts", `${money(pool.payoutsMade)} ${pool.currency}`]].map(([l, v]) => (
        <div key={l} style={{ display: "flex", gap: "0.35rem", alignItems: "baseline" }}>
          <span className="muted" style={{ fontSize: "0.72rem" }}>{l}</span>
          <strong style={{ fontSize: "0.88rem" }}>{v}</strong>
        </div>
      ))}
    </div>
  );
}

// ── Stats widgets ─────────────────────────────────────────────────────────────

function StatWidget({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: "0.75rem 1rem", background: "rgba(255,255,255,0.025)", display: "flex", flexDirection: "column", gap: "0.2rem" }}>
      <span className="muted" style={{ fontSize: "0.7rem" }}>{label}</span>
      <strong style={{ fontSize: "1.15rem", color: color ?? "var(--text)" }}>{value}</strong>
      {sub && <span className="muted" style={{ fontSize: "0.68rem" }}>{sub}</span>}
    </div>
  );
}

function AgentStats({ stats }: { stats: AgentDashboardStats | null }) {
  if (!stats) return null;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.6rem", marginBottom: "1rem" }}>
      <StatWidget label="Payments today" value={stats.paymentsToday} />
      <StatWidget label="Spent today (USD)" value={`$${parseFloat(stats.amountSpentToday || "0").toFixed(2)}`} />
      <StatWidget label="Pending approval" value={stats.pendingApprovals} color={stats.pendingApprovals > 0 ? "var(--orange)" : undefined} />
      <StatWidget label="Total payments" value={stats.totalPayments} />
      <StatWidget label="Blocked" value={stats.totalBlocked} color={stats.totalBlocked > 0 ? "#f87171" : undefined} />
      <StatWidget label="Escalated" value={stats.totalEscalated} sub={stats.lastRunAt ? `Last run ${new Date(stats.lastRunAt).toLocaleTimeString()}` : "Never run"} />
    </div>
  );
}

// ── Agent creation form ───────────────────────────────────────────────────────

const DEFAULT_AGENT: AgentCreate = {
  id: "",
  name: "",
  maxSinglePayment: "50",
  maxDailySpend: "200",
  requiresApprovalAbove: "25",
  currency: "RLUSD",
  allowedAssets: ["RLUSD"],
  allowedNetwork: "XRPL",
  requireKnownMerchant: false,
};

function toSlug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function AgentCreateForm({ onCreated, onCancel }: { onCreated: (a: Agent) => void; onCancel: () => void }) {
  const [form, setForm] = useState<AgentCreate & { description: string }>(
    { ...DEFAULT_AGENT, description: "" }
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleNameChange = (e: ChangeEvent<HTMLInputElement>) => {
    const name = e.target.value;
    setForm((p) => ({ ...p, name, id: toSlug(name) }));
  };

  const set = (key: keyof AgentCreate | "description") => (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((p) => ({ ...p, [key]: e.target.value }));

  const submit = async () => {
    if (!form.name.trim()) { setErr("Name is required"); return; }
    const id = form.id || toSlug(form.name);
    if (!id) { setErr("Could not generate an ID from name — please enter one manually"); return; }
    setSaving(true); setErr(null);
    try {
      const agent = await api.createAgent({ ...form, id, description: form.description || null });
      onCreated(agent);
    } catch (e) { setErr(String(e)); }
    finally { setSaving(false); }
  };

  const numField = (key: keyof AgentCreate, label: string, hint?: string) => (
    <label style={{ display: "flex", flexDirection: "column", gap: "0.15rem", fontSize: "0.75rem" }}>
      <span className="muted">{label}{hint ? <span style={{ marginLeft: "0.4rem", opacity: 0.6 }}>({hint})</span> : null}</span>
      <input value={String(form[key] ?? "")} onChange={set(key)}
        style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.3rem 0.5rem", fontSize: "0.75rem" }} />
    </label>
  );

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 12, padding: "1.25rem", background: "rgba(255,255,255,0.025)", display: "grid", gap: "0.75rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong style={{ fontSize: "0.9rem" }}>New Agent</strong>
        <button type="button" className="text-action" onClick={onCancel} style={{ fontSize: "0.75rem" }}>cancel</button>
      </div>

      <label style={{ display: "flex", flexDirection: "column", gap: "0.15rem", fontSize: "0.75rem" }}>
        <span className="muted">Display name</span>
        <input value={form.name} onChange={handleNameChange}
          style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.3rem 0.5rem", fontSize: "0.75rem" }} />
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: "0.15rem", fontSize: "0.75rem" }}>
        <span className="muted">Agent ID <span style={{ opacity: 0.55 }}>(auto-generated from name)</span></span>
        <input value={form.id} onChange={set("id")}
          style={{ background: "rgba(255,255,255,0.04)", border: "1px solid var(--border)", borderRadius: 6, color: "rgba(255,255,255,0.5)", padding: "0.3rem 0.5rem", fontSize: "0.75rem", fontFamily: "monospace" }} />
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: "0.15rem", fontSize: "0.75rem" }}>
        <span className="muted">Context <span style={{ opacity: 0.55 }}>(what this agent is responsible for)</span></span>
        <textarea value={form.description} onChange={set("description")} rows={2}
          placeholder="e.g. Responsible for paying cloud service providers (AWS, GCP, Azure). Only approved SaaS vendors."
          style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.3rem 0.5rem", fontSize: "0.75rem", resize: "vertical", fontFamily: "inherit" }} />
      </label>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.5rem" }}>
        {numField("maxSinglePayment", "Max per tx (USD)")}
        {numField("maxDailySpend", "Max per day (USD)")}
        {numField("requiresApprovalAbove", "Approval above (USD)", "≤ max per tx")}
      </div>
      {err && <p style={{ color: "#f87171", fontSize: "0.75rem", margin: 0 }}>{err}</p>}
      <button type="button" className="primary-action" disabled={saving} onClick={() => void submit()}
        style={{ minHeight: "unset", padding: "0.4rem", fontSize: "0.82rem", borderRadius: 8 }}>
        {saving ? "Creating..." : "Create agent"}
      </button>
    </div>
  );
}

// ── Goal form ─────────────────────────────────────────────────────────────────

const DEFAULT_GOAL: TreasuryGoalCreate = {
  name: "Monthly supplier payment",
  beneficiaryName: "Acme Supplies AG",
  beneficiaryAddress: "rBBHb3oX4JxoGRU28X94iDRiZUPU8Xu7ur",
  beneficiaryCountry: "US",
  receiverEntityType: "company",
  amount: 20,
  currency: "RLUSD",
  reference: "INV-AUTO-001",
  purpose: "supplier_payment",
  triggerIntervalHours: 0.001,
};

function GoalList({ agentId, goals, onRefresh }: { agentId: string; goals: TreasuryGoal[]; onRefresh: () => void }) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<TreasuryGoalCreate>(DEFAULT_GOAL);
  const [adding, setAdding] = useState(false);

  const fieldChange = (key: keyof TreasuryGoalCreate) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((p) => ({ ...p, [key]: e.target.type === "number" ? Number(e.target.value) : e.target.value }));

  const addGoal = async () => {
    setAdding(true);
    try { await api.createAgentGoal(agentId, form); onRefresh(); setShowForm(false); }
    finally { setAdding(false); }
  };

  const removeGoal = async (id: string) => {
    await api.deleteAgentGoal(agentId, id);
    onRefresh();
  };

  return (
    <div style={{ marginBottom: "1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
        <span style={{ fontSize: "0.8rem", fontWeight: 700 }}>Goals ({goals.length})</span>
        <button type="button" className="text-action" style={{ fontSize: "0.72rem", minHeight: "unset", padding: "0.15rem 0.45rem" }} onClick={() => setShowForm(!showForm)}>
          {showForm ? "cancel" : "+ add"}
        </button>
      </div>
      {goals.map((g) => (
        <div key={g.id} style={{ padding: "0.5rem 0", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.5rem" }}>
          <div>
            <div style={{ fontSize: "0.8rem", fontWeight: 700 }}>{g.name}</div>
            <div className="muted" style={{ fontSize: "0.71rem" }}>{money(g.amount)} {g.currency} → {g.beneficiaryName} · every {g.triggerIntervalHours}h</div>
            {g.lastTriggeredAt && <div className="muted" style={{ fontSize: "0.68rem" }}>last: {new Date(g.lastTriggeredAt).toLocaleTimeString()}</div>}
          </div>
          <button type="button" className="text-action" style={{ fontSize: "0.68rem", minHeight: "unset", padding: "0.1rem 0.4rem", flexShrink: 0 }} onClick={() => void removeGoal(g.id)}>✕</button>
        </div>
      ))}
      {goals.length === 0 && !showForm && <p className="muted" style={{ fontSize: "0.75rem" }}>No goals yet — add one to automate payments.</p>}
      {showForm && (
        <div style={{ marginTop: "0.75rem", display: "grid", gap: "0.5rem" }}>
          {[
            { key: "name", label: "Name" },
            { key: "beneficiaryName", label: "Beneficiary" },
            { key: "beneficiaryAddress", label: "XRPL address" },
            { key: "reference", label: "Reference" },
          ].map(({ key, label }) => (
            <label key={key} style={{ display: "flex", flexDirection: "column", gap: "0.15rem", fontSize: "0.74rem" }}>
              <span className="muted">{label}</span>
              <input value={String(form[key as keyof TreasuryGoalCreate] ?? "")} onChange={fieldChange(key as keyof TreasuryGoalCreate)}
                style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.25rem 0.4rem", fontSize: "0.74rem" }} />
            </label>
          ))}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.4rem" }}>
            <label style={{ fontSize: "0.74rem", display: "flex", flexDirection: "column", gap: "0.15rem" }}>
              <span className="muted">Amount</span>
              <input type="number" value={form.amount} onChange={fieldChange("amount")}
                style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.25rem 0.4rem", fontSize: "0.74rem" }} />
            </label>
            <label style={{ fontSize: "0.74rem", display: "flex", flexDirection: "column", gap: "0.15rem" }}>
              <span className="muted">Interval (h)</span>
              <input type="number" value={form.triggerIntervalHours} onChange={fieldChange("triggerIntervalHours")} step={0.001}
                style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.25rem 0.4rem", fontSize: "0.74rem" }} />
            </label>
          </div>
          <button type="button" className="primary-action" disabled={adding} onClick={() => void addGoal()}
            style={{ minHeight: "unset", padding: "0.35rem", fontSize: "0.78rem", borderRadius: 8 }}>
            {adding ? "Adding..." : "Add goal"}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Policy summary card ───────────────────────────────────────────────────────

function PolicyCard({ agent, onEdit }: { agent: Agent; onEdit: () => void }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: "0.75rem 1rem", background: "rgba(255,255,255,0.02)", marginBottom: "1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
        <span style={{ fontSize: "0.8rem", fontWeight: 700 }}>Policy · revision {agent.policyRevision}</span>
        <button type="button" className="text-action" style={{ fontSize: "0.72rem", minHeight: "unset", padding: "0.15rem 0.45rem" }} onClick={onEdit}>edit</button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.35rem 1rem", fontSize: "0.74rem" }}>
        {[
          ["Max per tx", `$${agent.maxSinglePayment}`],
          ["Max per day", `$${agent.maxDailySpend}`],
          ["Approval above", `$${agent.requiresApprovalAbove}`],
          ["Global ceiling", "$500"],
          ["Currency", agent.currency ?? "RLUSD"],
          ["Network", agent.allowedNetwork ?? "XRPL"],
        ].map(([l, v]) => (
          <div key={l}>
            <span className="muted">{l}: </span>
            <strong>{v}</strong>
          </div>
        ))}
        {agent.allowedAddresses && agent.allowedAddresses.length > 0 && (
          <div style={{ gridColumn: "1/-1" }}>
            <span className="muted">Allowed addresses: </span>
            <span style={{ fontSize: "0.7rem" }}>{agent.allowedAddresses.join(", ")}</span>
          </div>
        )}
        {agent.blockedAddresses && agent.blockedAddresses.length > 0 && (
          <div style={{ gridColumn: "1/-1" }}>
            <span className="muted">Blocked addresses: </span>
            <span style={{ fontSize: "0.7rem", color: "#f87171" }}>{agent.blockedAddresses.join(", ")}</span>
          </div>
        )}
        {agent.allowedCategories && agent.allowedCategories.length > 0 && (
          <div style={{ gridColumn: "1/-1" }}>
            <span className="muted">Categories: </span>
            <span style={{ fontSize: "0.7rem" }}>{agent.allowedCategories.join(", ")}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Inline policy editor ──────────────────────────────────────────────────────

function PolicyEditor({ agent, onSaved, onCancel }: { agent: Agent; onSaved: (a: Agent) => void; onCancel: () => void }) {
  const [f, setF] = useState<AgentUpdate>({
    maxSinglePayment: agent.maxSinglePayment,
    maxDailySpend: agent.maxDailySpend,
    requiresApprovalAbove: agent.requiresApprovalAbove,
    allowedCategories: agent.allowedCategories ?? null,
    allowedAddresses: agent.allowedAddresses ?? null,
    blockedAddresses: agent.blockedAddresses ?? [],
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const set = (key: keyof AgentUpdate) => (e: ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [key]: e.target.value }));

  const setArr = (key: keyof AgentUpdate) => (e: ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [key]: e.target.value ? e.target.value.split(",").map((s) => s.trim()) : null }));

  const save = async () => {
    setSaving(true); setErr(null);
    try { const a = await api.updateAgent(agent.id, f); onSaved(a); }
    catch (e) { setErr(String(e)); }
    finally { setSaving(false); }
  };

  const field = (key: keyof AgentUpdate, label: string) => (
    <label style={{ display: "flex", flexDirection: "column", gap: "0.12rem", fontSize: "0.74rem" }}>
      <span className="muted">{label}</span>
      <input value={String(f[key] ?? "")} onChange={set(key)}
        style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.25rem 0.4rem", fontSize: "0.74rem" }} />
    </label>
  );

  return (
    <div style={{ border: "1px solid var(--orange)", borderRadius: 10, padding: "1rem", marginBottom: "1rem", background: "rgba(255,165,0,0.04)", display: "grid", gap: "0.6rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: "0.8rem", fontWeight: 700 }}>Edit policy</span>
        <button type="button" className="text-action" onClick={onCancel} style={{ fontSize: "0.72rem" }}>cancel</button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.5rem" }}>
        {field("maxSinglePayment", "Max per tx (USD)")}
        {field("maxDailySpend", "Max per day (USD)")}
        {field("requiresApprovalAbove", "Approval above (USD)")}
      </div>
      <label style={{ fontSize: "0.74rem", display: "flex", flexDirection: "column", gap: "0.12rem" }}>
        <span className="muted">Allowed addresses (comma-sep, blank=any)</span>
        <input value={(f.allowedAddresses ?? []).join(", ")} onChange={setArr("allowedAddresses")}
          style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.25rem 0.4rem", fontSize: "0.74rem" }} />
      </label>
      <label style={{ fontSize: "0.74rem", display: "flex", flexDirection: "column", gap: "0.12rem" }}>
        <span className="muted">Blocked addresses (comma-sep)</span>
        <input value={(f.blockedAddresses ?? []).join(", ")} onChange={setArr("blockedAddresses")}
          style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.25rem 0.4rem", fontSize: "0.74rem" }} />
      </label>
      <label style={{ fontSize: "0.74rem", display: "flex", flexDirection: "column", gap: "0.12rem" }}>
        <span className="muted">Allowed categories (comma-sep, blank=any)</span>
        <input value={(f.allowedCategories ?? []).join(", ")} onChange={setArr("allowedCategories")}
          style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.25rem 0.4rem", fontSize: "0.74rem" }} />
      </label>
      {err && <p style={{ color: "#f87171", fontSize: "0.74rem", margin: 0 }}>{err}</p>}
      <button type="button" className="primary-action" disabled={saving} onClick={() => void save()}
        style={{ minHeight: "unset", padding: "0.4rem", fontSize: "0.8rem", borderRadius: 8 }}>
        {saving ? "Saving..." : "Save policy"}
      </button>
    </div>
  );
}

// ── Agent card (left rail) ────────────────────────────────────────────────────

function AgentCard({ agent, selected, onClick }: { agent: Agent; selected: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} style={{
      width: "100%", textAlign: "left", padding: "0.7rem 0.85rem",
      border: `1px solid ${selected ? "var(--orange)" : "var(--border)"}`,
      borderRadius: 10, background: selected ? "rgba(255,165,0,0.06)" : "rgba(255,255,255,0.025)",
      cursor: "pointer", display: "grid", gap: "0.2rem",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: "0.82rem", fontWeight: 700 }}>{agent.name}</span>
        <span style={{
          fontSize: "0.65rem", fontWeight: 800, padding: "0.1rem 0.4rem", borderRadius: 999,
          border: `1px solid ${agent.status === "active" ? "#6ee7b7" : "var(--muted)"}`,
          color: agent.status === "active" ? "#6ee7b7" : "var(--muted)",
        }}>{agent.status.toUpperCase()}</span>
      </div>
      <div className="muted" style={{ fontSize: "0.7rem" }}>
        ${agent.maxSinglePayment} / tx · ${agent.maxDailySpend} / day
      </div>
      <div className="muted" style={{ fontSize: "0.68rem" }}>rev {agent.policyRevision} · {agent.currency ?? "RLUSD"}</div>
    </button>
  );
}

// ── Agent detail panel ────────────────────────────────────────────────────────

function AgentDetail({ agent, onAgentUpdated, onAgentDeleted }: {
  agent: Agent;
  onAgentUpdated: (a: Agent) => void;
  onAgentDeleted: (id: string) => void;
}) {
  const [goals, setGoals] = useState<TreasuryGoal[]>([]);
  const [stats, setStats] = useState<AgentDashboardStats | null>(null);
  const [logLines, setLogLines] = useState<LogLine[]>([]);
  const [running, setRunning] = useState(false);
  const [runPayments, setRunPayments] = useState<Payment[]>([]);
  const [claimResults, setClaimResults] = useState<Record<string, InsurancePayoutRecord>>({});
  const [claimingId, setClaimingId] = useState<string | null>(null);
  const [editingPolicy, setEditingPolicy] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const lineId = useRef(0);

  const addLine = useCallback((line: Omit<LogLine, "id">) => {
    setLogLines((p) => [...p, { ...line, id: lineId.current++ }]);
  }, []);

  const refresh = useCallback(async () => {
    const [g, s] = await Promise.allSettled([
      api.listAgentGoals(agent.id),
      api.getAgentStats(agent.id).catch(() => null),
    ]);
    if (g.status === "fulfilled") setGoals(g.value);
    if (s.status === "fulfilled") setStats(s.value);
  }, [agent.id]);

  useEffect(() => { void refresh(); }, [refresh]);

  const runAgent = useCallback(async () => {
    setRunning(true);
    setLogLines([]);
    setRunPayments([]);
    setClaimResults({});
    addLine({ kind: "heading", text: `[${ts()}] Agent cycle started — ${agent.name}` });
    addLine({ kind: "info", text: `Evaluating ${goals.length} goal(s)…` });
    let run: TreasuryAgentRun;
    try {
      run = await api.runAgent(agent.id);
    } catch (e) {
      addLine({ kind: "error", text: `Run failed: ${String(e)}` });
      setRunning(false);
      return;
    }
    const fetchPromise = api.listPayments().catch(() => [] as Payment[]);
    for (const line of run.triggerLog) {
      await new Promise((r) => setTimeout(r, 100));
      const lower = line.toLowerCase();
      const kind = lower.includes("insurance") || lower.includes("premium") ? "insurance"
        : lower.includes("tx ") || lower.includes("tx=") ? "tx"
        : lower.includes("failed") || lower.includes("error") ? "error"
        : "info";
      addLine({ kind, text: line });
    }
    const allPayments = await fetchPromise;
    const runIds = new Set(run.paymentsInitiated);
    const thisRunPayments = allPayments.filter((p) => runIds.has(p.id));
    setRunPayments(thisRunPayments);
    addLine({ kind: "heading", text: `[${ts()}] ${run.goalsTriggered} payment(s) initiated` });
    for (const p of thisRunPayments) {
      addLine({ kind: "info", text: `  ${p.intent.receiverName} · ${money(p.intent.amount)} ${p.intent.currency}` });
      if (p.txHash) addLine({ kind: "tx", text: "  Settlement", txHash: p.txHash, explorerUrl: p.explorerUrl ?? undefined });
      addLine({ kind: isSettled(p.status) ? "success" : "info", text: `  Status: ${p.status.toUpperCase()}` });
    }
    if (run.narration) {
      addLine({ kind: "heading", text: `[${ts()}] Narration` });
      addLine({ kind: "info", text: run.narration });
    }
    addLine({ kind: "success", text: `[${ts()}] Cycle complete.` });
    await refresh();
    setRunning(false);
  }, [agent.id, agent.name, goals.length, addLine, refresh]);

  const simulateClaim = useCallback(async (payment: Payment) => {
    setClaimingId(payment.id);
    try {
      const payout = await api.settleClaim({
        jobId: payment.id,
        agentAddress: payment.intent.from,
        merchant: payment.intent.to,
        merchantName: payment.intent.receiverName,
        merchantCountry: payment.intent.receiverCountry,
        scoreBand: "STANDARD",
        currency: payment.intent.currency,
        collateral: "0.000000",
      });
      setClaimResults((p) => ({ ...p, [payment.id]: payout }));
      await refresh();
    } catch (e) {
      addLine({ kind: "error", text: `Claim failed: ${String(e)}` });
    } finally { setClaimingId(null); }
  }, [addLine, refresh]);

  const togglePause = async () => {
    setPausing(true);
    try {
      const newStatus: AgentStatus = agent.status === "active" ? "paused" : "active";
      const updated = await api.updateAgent(agent.id, { status: newStatus });
      onAgentUpdated(updated);
    } finally { setPausing(false); }
  };

  const deleteAgent = async () => {
    if (!confirm(`Delete agent "${agent.name}"? This cannot be undone.`)) return;
    setDeleting(true);
    try { await api.deleteAgent(agent.id); onAgentDeleted(agent.id); }
    finally { setDeleting(false); }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {/* Agent header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h3 style={{ margin: 0, fontSize: "1.1rem" }}>{agent.name}</h3>
          <span className="muted" style={{ fontSize: "0.76rem" }}>id: {agent.id} · policy rev {agent.policyRevision}</span>
          {agent.description && <p className="muted" style={{ margin: "0.2rem 0 0", fontSize: "0.76rem", maxWidth: 480 }}>{agent.description}</p>}
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <button type="button"
            className="primary-action"
            disabled={running || agent.status === "paused" || goals.length === 0}
            onClick={() => void runAgent()}
            style={{ fontSize: "0.88rem", padding: "0.4rem 1rem", minHeight: "unset" }}>
            {running ? "Running…" : "Run Agent"}
          </button>
          <button type="button" className="text-action" disabled={pausing} onClick={() => void togglePause()}
            style={{ fontSize: "0.75rem", minHeight: "unset", padding: "0.3rem 0.65rem" }}>
            {agent.status === "active" ? "Pause" : "Unpause"}
          </button>
          <button type="button" className="text-action" disabled={deleting} onClick={() => void deleteAgent()}
            style={{ fontSize: "0.75rem", minHeight: "unset", padding: "0.3rem 0.65rem", color: "#f87171" }}>
            Delete
          </button>
        </div>
      </div>

      {agent.status === "paused" && (
        <div style={{ background: "rgba(251,191,36,0.08)", border: "1px solid rgba(251,191,36,0.3)", borderRadius: 8, padding: "0.5rem 0.75rem", fontSize: "0.76rem", color: "#fbbf24" }}>
          Agent is paused — new runs and payment initiations are stopped. Existing pending approvals are still valid.
        </div>
      )}

      {/* Stats */}
      <AgentStats stats={stats} />

      {/* Policy */}
      {editingPolicy
        ? <PolicyEditor agent={agent} onSaved={(a) => { onAgentUpdated(a); setEditingPolicy(false); }} onCancel={() => setEditingPolicy(false)} />
        : <PolicyCard agent={agent} onEdit={() => setEditingPolicy(true)} />
      }

      {/* Goals */}
      <GoalList agentId={agent.id} goals={goals} onRefresh={() => void refresh()} />

      {/* Log */}
      <LogPanel lines={logLines} running={running} />

      {/* Payment outcomes */}
      {runPayments.length > 0 && (
        <div>
          <span className="eyebrow" style={{ display: "block", marginBottom: "0.6rem" }}>Payment outcomes ({runPayments.length})</span>
          <div style={{ display: "grid", gap: "0.6rem" }}>
            {runPayments.map((p) => (
              <div key={p.id}>
                <PaymentOutcomeCard payment={p} onClaim={simulateClaim} claiming={claimingId === p.id} />
                {claimResults[p.id] && (
                  <div style={{ marginTop: "0.4rem", border: "1px solid rgba(248,113,113,0.35)", borderRadius: 10, padding: "0.75rem 1rem", background: "rgba(248,113,113,0.05)" }}>
                    <span style={{ color: "#f87171", fontWeight: 800, fontSize: "0.82rem" }}>Claim settled</span>
                    <span className="muted" style={{ marginLeft: "0.75rem", fontSize: "0.78rem" }}>{money(claimResults[p.id].totalPaid)} {claimResults[p.id].currency} paid</span>
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

// ── Main page ─────────────────────────────────────────────────────────────────

export function TreasuryPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pool, setPool] = useState<PoolStatus | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const [a, p] = await Promise.allSettled([
      api.listAgents(),
      api.getInsurancePool().catch(() => null),
    ]);
    if (a.status === "fulfilled") setAgents(a.value);
    if (p.status === "fulfilled") setPool(p.value);
    setLoading(false);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const selected = agents.find((a) => a.id === selectedId) ?? null;

  const onAgentCreated = (agent: Agent) => {
    setAgents((p) => [agent, ...p]);
    setSelectedId(agent.id);
    setShowCreate(false);
  };

  const onAgentUpdated = (agent: Agent) => {
    setAgents((p) => p.map((a) => (a.id === agent.id ? agent : a)));
  };

  const onAgentDeleted = (id: string) => {
    setAgents((p) => p.filter((a) => a.id !== id));
    setSelectedId(null);
  };

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto" }}>
      {/* Page header */}
      <div style={{ marginBottom: "1rem", display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <span className="eyebrow">Payment Agents</span>
          <h2 style={{ margin: "0.2rem 0 0.2rem" }}>Agent Builder</h2>
          <p className="muted" style={{ margin: 0, fontSize: "0.82rem" }}>
            Create agents with policy guardrails. Code decides and signs — the agent explains.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <span style={{
            fontSize: "0.7rem", padding: "0.2rem 0.6rem", borderRadius: 999,
            border: "1px solid rgba(147,197,253,0.4)", color: "#93c5fd",
          }}>
            mock mode
          </span>
        </div>
      </div>

      <PoolStrip pool={pool} />

      {/* Two-column layout */}
      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: "1.5rem", alignItems: "start" }}>
        {/* Left rail — agent list */}
        <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
          <button type="button" className="primary-action"
            onClick={() => { setShowCreate(!showCreate); setSelectedId(null); }}
            style={{ fontSize: "0.85rem", padding: "0.45rem", minHeight: "unset" }}>
            {showCreate ? "Cancel" : "+ New Agent"}
          </button>

          {loading && <p className="muted" style={{ fontSize: "0.78rem" }}>Loading agents…</p>}

          {agents.length === 0 && !loading && !showCreate && (
            <p className="muted" style={{ fontSize: "0.78rem" }}>No agents yet. Create one to automate payments with policy guardrails.</p>
          )}

          {agents.map((a) => (
            <AgentCard key={a.id} agent={a} selected={selectedId === a.id} onClick={() => { setSelectedId(a.id); setShowCreate(false); }} />
          ))}
        </div>

        {/* Right — detail or create form */}
        <div>
          {showCreate && (
            <AgentCreateForm onCreated={onAgentCreated} onCancel={() => setShowCreate(false)} />
          )}
          {!showCreate && selected && (
            <AgentDetail key={selected.id} agent={selected} onAgentUpdated={onAgentUpdated} onAgentDeleted={onAgentDeleted} />
          )}
          {!showCreate && !selected && !loading && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: 320, border: "1px dashed var(--border)", borderRadius: 14 }}>
              <p className="muted" style={{ fontSize: "0.85rem" }}>Select an agent or create a new one.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
