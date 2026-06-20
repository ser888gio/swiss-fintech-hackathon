import { useCallback, useEffect, useState, type ChangeEvent } from "react";
import type {
  AgentRiskState,
  BindRequest,
  CoverLine,
  InsurancePayoutRecord,
  InsurancePremiumRecord,
  PoolStatus,
  PremiumQuote,
} from "@treasury/shared";
import { api } from "../lib/api.js";
import { hashShort, money } from "../lib/utils.js";

// ── Helpers ───────────────────────────────────────────────────────────────────

function decisionClass(d: string) {
  if (d === "OFFER") return "status-settled";
  if (d === "REVIEW") return "status-routing";
  return "status-blocked";
}

function field<T extends object>(setState: (fn: (p: T) => T) => void, key: keyof T) {
  return (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setState((p) => ({ ...p, [key]: e.target.value }));
}

const COVER_LINES: CoverLine[] = [
  "merchant_default",
  "lender_credit",
  "principal_score",
  "mandate_breach",
];
const SCORE_BANDS = ["ELITE", "HIGH", "STANDARD", "HIGH_RISK"];
const CATEGORIES = ["supplier_payment", "vendor_invoice", "treasury_transfer", "payroll", "marketplace"];
const TENOR_BANDS = ["instant", "short", "medium", "long"];
const CPTY_BANDS = ["low", "standard", "elevated", "high"];

// ── Pool Status ───────────────────────────────────────────────────────────────

function PoolPanel({ pool }: { pool: PoolStatus | null }) {
  if (!pool) return <p className="muted">Loading pool status…</p>;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "1.5rem" }}>
      {[
        ["First-loss capital", `${money(pool.firstLoss)} ${pool.currency}`],
        ["Capacity ratio", `${(pool.capacityRatio * 100).toFixed(1)}%`],
        ["LP capital", `${money(pool.lpCapital)} ${pool.currency}`],
        ["Vault balance", `${money(pool.vaultBalance)} ${pool.currency}`],
        ["Premiums collected", `${money(pool.premiumsCollected)} ${pool.currency}`],
        ["Payouts made", `${money(pool.payoutsMade)} ${pool.currency}`],
      ].map(([label, value]) => (
        <div key={label}>
          <span className="eyebrow">{label}</span>
          <p style={{ margin: "0.2rem 0 0", fontWeight: 700 }}>{value}</p>
        </div>
      ))}
    </div>
  );
}

// ── Quote Panel ───────────────────────────────────────────────────────────────

interface QuoteForm {
  agentAddress: string;
  scoreBand: string;
  category: string;
  tenorBand: string;
  cptyBand: string;
  firstSeen: boolean;
  amount: string;
  activeLines: CoverLine[];
}

const DEFAULT_FORM: QuoteForm = {
  agentAddress: "rAGENT00000000000000000000000000",
  scoreBand: "STANDARD",
  category: "supplier_payment",
  tenorBand: "short",
  cptyBand: "standard",
  firstSeen: false,
  amount: "500",
  activeLines: ["merchant_default"],
};

function QuotePanel({ onBound }: { onBound: () => void }) {
  const [form, setForm] = useState<QuoteForm>(DEFAULT_FORM);
  const [quote, setQuote] = useState<PremiumQuote | null>(null);
  const [busy, setBusy] = useState(false);
  const [binding, setBinding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bound, setBound] = useState<InsurancePremiumRecord | null>(null);

  const toggleLine = (line: CoverLine) => {
    setForm((f) => ({
      ...f,
      activeLines: f.activeLines.includes(line)
        ? f.activeLines.filter((l) => l !== line)
        : [...f.activeLines, line],
    }));
    setQuote(null);
    setBound(null);
  };

  const runQuote = async () => {
    setBusy(true);
    setError(null);
    setQuote(null);
    setBound(null);
    try {
      const q = await api.quoteInsurance({
        agentAddress: form.agentAddress,
        scoreBand: form.scoreBand,
        txnContext: {
          category: form.category,
          tenorBand: form.tenorBand,
          cptyBand: form.cptyBand,
          firstSeen: form.firstSeen,
          amount: form.amount,
          activeLines: form.activeLines,
        },
      });
      setQuote(q);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const bind = async () => {
    if (!quote) return;
    setBinding(true);
    setError(null);
    const req: BindRequest = {
      jobId: `demo-${Date.now()}`,
      agentAddress: form.agentAddress,
      scoreBand: form.scoreBand,
      currency: "USD",
      quote,
    };
    try {
      const record = await api.bindInsurance(req);
      setBound(record);
      onBound();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBinding(false);
    }
  };

  return (
    <section className="queue ars-panel" aria-label="Quote a cover">
      <div className="section-heading">
        <span className="eyebrow">Pricing engine</span>
        <strong>Quote a cover</strong>
      </div>
      <p className="muted" style={{ marginBottom: "1rem" }}>
        Price insurance for a transaction using the Bayesian PD model. Select cover lines,
        fill in context, then bind to collect the premium on-chain.
      </p>

      {error && <p className="error">{error}</p>}

      <div className="ars-form-grid">
        <label><span>Agent address</span>
          <input name="agent-address" autoComplete="off" value={form.agentAddress} onChange={field(setForm, "agentAddress")} spellCheck={false} />
        </label>
        <label><span>Amount (USD)</span>
          <input name="transaction-amount" autoComplete="off" inputMode="decimal" value={form.amount} onChange={field(setForm, "amount")} />
        </label>
        <label><span>Score band</span>
          <select name="score-band" autoComplete="off" value={form.scoreBand} onChange={field(setForm, "scoreBand")}
            style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.3rem 0.5rem" }}>
            {SCORE_BANDS.map((b) => <option key={b}>{b}</option>)}
          </select>
        </label>
        <label><span>Category</span>
          <select name="transaction-category" autoComplete="off" value={form.category} onChange={field(setForm, "category")}
            style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.3rem 0.5rem" }}>
            {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label><span>Tenor</span>
          <select name="tenor-band" autoComplete="off" value={form.tenorBand} onChange={field(setForm, "tenorBand")}
            style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.3rem 0.5rem" }}>
            {TENOR_BANDS.map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label><span>Counterparty risk</span>
          <select name="counterparty-band" autoComplete="off" value={form.cptyBand} onChange={field(setForm, "cptyBand")}
            style={{ background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.3rem 0.5rem" }}>
            {CPTY_BANDS.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
      </div>

      <label className="checkbox-label" style={{ marginBottom: "0.75rem", marginTop: 0 }}>
        <input
          name="first-seen"
          type="checkbox"
          checked={form.firstSeen}
          onChange={(e) => setForm((f) => ({ ...f, firstSeen: e.target.checked }))}
        />
        <span>
          First-time counterparty <span className="muted">(novelty uplift)</span>
        </span>
      </label>

      <div style={{ marginBottom: "0.75rem" }}>
        <span className="eyebrow" style={{ display: "block", marginBottom: "0.4rem" }}>Cover lines</span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
          {COVER_LINES.map((line) => (
            <button key={line} type="button"
              onClick={() => toggleLine(line)}
              style={{
                padding: "0.2rem 0.6rem",
                fontSize: "0.78rem",
                borderRadius: 6,
                background: form.activeLines.includes(line) ? "var(--orange)" : "rgba(255,255,255,0.06)",
                color: form.activeLines.includes(line) ? "#000" : "var(--muted)",
                border: "1px solid var(--border)",
              }}
            >
              {line.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </div>

      <button className="primary-action" type="button" disabled={busy || form.activeLines.length === 0} onClick={() => void runQuote()}>
        {busy ? "Pricing…" : "Get Quote"}
      </button>

      {quote && (
        <div className="ars-tx-card" style={{ marginTop: "1rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
            <span className={`dashboard-status ${decisionClass(quote.decision)}`}>{quote.decision}</span>
            <strong>Premium: {money(quote.premium)} USD</strong>
            <span className="muted" style={{ fontSize: "0.78rem" }}>
              PD {(quote.pd * 100).toFixed(3)}% · cred {(quote.credibility * 100).toFixed(1)}%
            </span>
          </div>
          <p className="muted" style={{ margin: "0 0 0.4rem" }}>{quote.reason}</p>
          {Object.keys(quote.lines).length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", fontSize: "0.78rem", marginBottom: "0.4rem" }}>
              {Object.entries(quote.lines).map(([line, prem]) => (
                <span key={line} className="muted">
                  <strong>{line.replace(/_/g, " ")}:</strong> {money(prem)}
                </span>
              ))}
            </div>
          )}
          <p className="muted" style={{ fontSize: "0.7rem" }}>
            Receipt: {hashShort(quote.receiptHash)}
          </p>
          {quote.decision === "OFFER" && !bound && (
            <button className="primary-action" type="button" style={{ marginTop: "0.5rem" }}
              onClick={() => void bind()} disabled={binding}>
              {binding ? "Binding…" : "Bind & Pay Premium"}
            </button>
          )}
          {bound && (
            <p className="muted" style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>
              Bound — {money(bound.premiumAmount)} {bound.currency} ·{" "}
              {bound.txHash
                ? <a href={bound.explorerUrl ?? "#"} target="_blank" rel="noreferrer">{hashShort(bound.txHash)} ↗</a>
                : "simulated"
              }
            </p>
          )}
        </div>
      )}
    </section>
  );
}

// ── Agent Risk Panel ──────────────────────────────────────────────────────────

function AgentRiskPanel() {
  const [address, setAddress] = useState("rAGENT00000000000000000000000000");
  const [risk, setRisk] = useState<AgentRiskState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lookup = async () => {
    setBusy(true);
    setError(null);
    setRisk(null);
    try {
      setRisk(await api.getAgentRisk(address));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="queue ars-panel" aria-label="Agent risk state">
      <div className="section-heading">
        <span className="eyebrow">Bayesian risk model</span>
        <strong>Agent Risk State</strong>
      </div>
      <p className="muted" style={{ marginBottom: "1rem" }}>
        Look up the Beta-distribution parameters for any agent address.
        α and β track observed successes and defaults; credibility rises with experience.
      </p>
      {error && <p className="error">{error}</p>}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        <input name="risk-agent-address" autoComplete="off" value={address} onChange={(e) => setAddress(e.target.value)}
          placeholder="XRPL address"
          style={{ flex: 1, background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--text)", padding: "0.3rem 0.6rem", fontSize: "0.8rem" }}
        />
        <button className="primary-action" type="button" disabled={busy} onClick={() => void lookup()}>
          {busy ? "…" : "Lookup"}
        </button>
      </div>
      {risk && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "1.5rem" }}>
          {[
            ["Score band", risk.scoreBand],
            ["PD", `${(risk.pd * 100).toFixed(3)}%`],
            ["Credibility", `${(risk.credibility * 100).toFixed(1)}%`],
            ["α (successes)", risk.alpha.toFixed(3)],
            ["β (defaults)", risk.beta.toFixed(3)],
          ].map(([label, value]) => (
            <div key={label}>
              <span className="eyebrow">{label}</span>
              <p style={{ margin: "0.2rem 0 0", fontWeight: 700 }}>{value}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ── History Panel ─────────────────────────────────────────────────────────────

function HistoryPanel({ premiums, payouts }: { premiums: InsurancePremiumRecord[]; payouts: InsurancePayoutRecord[] }) {
  return (
    <div style={{ display: "grid", gap: "1.5rem" }}>
      <section className="queue ars-panel" aria-label="Premium history">
        <div className="section-heading">
          <span className="eyebrow">Premiums</span>
          <strong>Collected premiums ({premiums.length})</strong>
        </div>
        {premiums.length === 0 ? (
          <p className="muted">No premiums collected yet. Quote and bind a cover above.</p>
        ) : (
          <ul className="credential-log">
            {premiums.map((p) => (
              <li key={p.id} className="decision-row">
                <div style={{ flex: 1 }}>
                  <strong>{money(p.premiumAmount)} {p.currency}</strong>{" "}
                  <span className="muted">·</span>{" "}
                  <span className="muted">{p.scoreBand ?? "STANDARD"}</span>
                </div>
                <div className="muted" style={{ fontSize: "0.75rem" }}>
                  {p.txHash
                    ? <a href={p.explorerUrl ?? "#"} target="_blank" rel="noreferrer">{hashShort(p.txHash)} ↗</a>
                    : "simulated"
                  }
                  {" · "}{new Date(p.createdAt).toLocaleTimeString()}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="queue ars-panel" aria-label="Payout history">
        <div className="section-heading">
          <span className="eyebrow">Claims</span>
          <strong>Claim payouts ({payouts.length})</strong>
        </div>
        {payouts.length === 0 ? (
          <p className="muted">No claims settled yet.</p>
        ) : (
          <ul className="credential-log">
            {payouts.map((p) => (
              <li key={p.id} className="decision-row" style={{ flexWrap: "wrap" }}>
                <div style={{ flex: 1 }}>
                  <strong>{money(p.totalPaid)} {p.currency}</strong>{" "}
                  <span className="muted">slash {money(p.collateralSlashed)} · pool {money(p.poolDrawn)}</span>
                </div>
                <div className="muted" style={{ fontSize: "0.75rem" }}>
                  {p.reputationMptProtected ? "MPT protected" : "MPT burned"}
                  {" · "}{new Date(p.createdAt).toLocaleTimeString()}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

type Tab = "quote" | "risk" | "history";

export function InsurancePage() {
  const [pool, setPool] = useState<PoolStatus | null>(null);
  const [premiums, setPremiums] = useState<InsurancePremiumRecord[]>([]);
  const [payouts, setPayouts] = useState<InsurancePayoutRecord[]>([]);
  const [tab, setTab] = useState<Tab>("quote");

  const refresh = useCallback(async () => {
    const [p, pr, po] = await Promise.allSettled([
      api.getInsurancePool(),
      api.listPremiums(),
      api.listPayouts(),
    ]);
    if (p.status === "fulfilled") setPool(p.value);
    if (pr.status === "fulfilled") setPremiums(pr.value);
    if (po.status === "fulfilled") setPayouts(po.value);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const tabs: { id: Tab; label: string }[] = [
    { id: "quote", label: "Price a Cover" },
    { id: "risk", label: "Agent Risk" },
    { id: "history", label: `History (${premiums.length + payouts.length})` },
  ];

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <h2 style={{ marginBottom: "0.25rem" }}>Insurance Pricing &amp; Risk Engine</h2>
      <p className="muted" style={{ marginBottom: "1.5rem" }}>
        Actuarial cover for agent payments. Premiums are priced on a Bayesian PD model;
        claims are settled on-chain from agent collateral + vault pool.
      </p>

      <section className="queue ars-panel" style={{ marginBottom: "1.5rem" }} aria-label="Pool status">
        <div className="section-heading">
          <span className="eyebrow">Insurance Vault</span>
          <strong>Pool Status</strong>
        </div>
        <PoolPanel pool={pool} />
      </section>

      <div style={{ display: "flex", gap: "0.4rem", marginBottom: "1.25rem" }}>
        {tabs.map((t) => (
          <button key={t.id} type="button"
            onClick={() => setTab(t.id)}
            style={{
              padding: "0.3rem 0.85rem",
              borderRadius: 6,
              border: "1px solid var(--border)",
              background: tab === t.id ? "var(--orange)" : "rgba(255,255,255,0.04)",
              color: tab === t.id ? "#000" : "var(--muted)",
              fontWeight: tab === t.id ? 800 : 600,
              fontSize: "0.8rem",
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "quote" && <QuotePanel onBound={() => void refresh()} />}
      {tab === "risk" && <AgentRiskPanel />}
      {tab === "history" && <HistoryPanel premiums={premiums} payouts={payouts} />}
    </div>
  );
}
