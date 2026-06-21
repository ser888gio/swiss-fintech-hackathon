import { useCallback, useEffect, useState, type ChangeEvent, type CSSProperties } from "react";
import type {
  AgentRiskState,
  BindRequest,
  CoverLine,
  InsurancePackage,
  InsurancePayoutRecord,
  InsurancePremiumRecord,
  PoolStatus,
  PremiumQuote,
} from "@treasury/shared";
import { INSURANCE_PACKAGE_LINES } from "@treasury/shared";
import { api } from "../lib/api.js";
import { hashShort, money } from "../lib/utils.js";

// ── Static metadata ───────────────────────────────────────────────────────────

// Per-line max payout (sum insured) mirrors apps/api/app/insurance/tables.py
// LINE_PARAMS[*].limit — keep in sync by hand.
const LINE_META: Record<CoverLine, { label: string; desc: string; badge: string; limit: number }> = {
  merchant_default: {
    label: "Merchant Default",
    desc:
      "The agent pays a merchant up front and the goods or services are never delivered. " +
      "The pool reimburses the lost principal after agent collateral and any on-chain recovery are applied.",
    badge: "Core",
    limit: 100000,
  },
  fx_slippage: {
    label: "FX Slippage",
    desc:
      "On a cross-border payment the delivered amount lands below the intended amount beyond tolerance. " +
      "Fully parametric — the shortfall is read straight off the on-ledger delivered_amount vs the route quote and paid automatically, no claim form.",
    badge: "Parametric",
    limit: 10000,
  },
  mandate_breach: {
    label: "Mandate Breach",
    desc:
      "The agent sends to the wrong payee, overspends, or transacts outside its mandate. " +
      "Highest moral-hazard line, so it carries the largest loss-given-default and the strictest verification against the signed policy.",
    badge: "Policy",
    limit: 100000,
  },
  principal_score: {
    label: "Principal Score",
    desc:
      "A default that would otherwise burn the principal's on-chain reputation. " +
      "The pool absorbs the hit so the agent's ScoreBand is preserved and future premiums stay stable.",
    badge: "Reputation",
    limit: 25000,
  },
  lender_credit: {
    label: "Lender Credit",
    desc:
      "The agent draws working capital from a lender and fails to repay it. " +
      "Posted collateral is slashed first; the pool covers the residual shortfall up to the line limit.",
    badge: "Credit",
    limit: 250000,
  },
};

const PACKAGES: { id: InsurancePackage; tagline: string; eyebrow: string; color: string }[] = [
  { id: "Essential", eyebrow: "Core protection", tagline: "Merchant default protection for routine agent spend", color: "#2f8f62" },
  { id: "Standard", eyebrow: "Most selected", tagline: "Cross-border protection with FX and mandate cover", color: "#d1671f" },
  { id: "Full-Stack", eyebrow: "Maximum scope", tagline: "Every line, including credit and reputation risk", color: "#9b6fd6" },
];

const SCORE_BANDS = ["ELITE", "HIGH", "STANDARD", "HIGH_RISK"];
const CATEGORIES = [
  { value: "merchant_payment", label: "Merchant Payment" },
  { value: "supplier_payment", label: "Supplier Payment" },
  { value: "loan_repayment", label: "Loan Repayment" },
  { value: "service_payment", label: "Service Payment" },
  { value: "data_lookup", label: "Data Lookup" },
];
const TENOR_BANDS = [
  { value: "instant", label: "Instant (< 1 min)" },
  { value: "lt_30d", label: "< 30 days" },
  { value: "30_90d", label: "30–90 days" },
  { value: "gt_90d", label: "> 90 days" },
];
const CPTY_BANDS = [
  { value: "verified", label: "Verified (KYC)" },
  { value: "known", label: "Known" },
  { value: "new", label: "New" },
  { value: "unverified", label: "Unverified" },
];

function field<T extends object>(setState: (fn: (p: T) => T) => void, key: keyof T) {
  return (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setState((p) => ({ ...p, [key]: e.target.value }));
}

function decisionClass(d: string) {
  if (d === "OFFER") return "status-settled";
  if (d === "REVIEW") return "status-routing";
  return "status-blocked";
}

// ── Pool Status ───────────────────────────────────────────────────────────────

function PoolPanel({ pool }: { pool: PoolStatus | null }) {
  if (!pool) return <div className="insurance-pool-loading" role="status">Loading vault telemetry…</div>;

  const capPct = Math.min(100, pool.capacityRatio * 100);
  const capColor = capPct > 70 ? "#2a9d5c" : capPct > 35 ? "#d1671f" : "#c0392b";

  return (
    <div className="insurance-pool-content">
      <div className="insurance-pool-metrics">
        {[
          ["First-loss capital", `${money(pool.firstLoss)} ${pool.currency}`],
          ["LP capital", `${money(pool.lpCapital)} ${pool.currency}`],
          ["Premiums in", `${money(pool.premiumsCollected)} ${pool.currency}`],
          ["Payouts out", `${money(pool.payoutsMade)} ${pool.currency}`],
          ["Vault balance", `${money(pool.vaultBalance)} ${pool.currency}`],
        ].map(([label, value]) => (
          <div className="insurance-pool-metric" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <div className="insurance-capacity">
        <div className="insurance-capacity-copy">
          <div>
            <span className="eyebrow">Available capacity</span>
            <strong>{capPct.toFixed(1)}%</strong>
          </div>
          <span className="insurance-capacity-state" style={{ color: capColor }}>
            <i style={{ background: capColor }} /> {capPct > 70 ? "Healthy" : capPct > 35 ? "Watch" : "Constrained"}
          </span>
        </div>
        <div className="insurance-capacity-track" aria-label={`${capPct.toFixed(1)}% pool capacity`}>
          <div style={{ width: `${capPct}%`, background: capColor }} />
        </div>
      </div>
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
  selectedPackage: InsurancePackage | null;
}

const DEFAULT_FORM: QuoteForm = {
  agentAddress: "rAGENT00000000000000000000000000",
  scoreBand: "STANDARD",
  category: "merchant_payment",
  tenorBand: "lt_30d",
  cptyBand: "known",
  firstSeen: false,
  amount: "5000",
  activeLines: ["merchant_default"],
  selectedPackage: "Essential",
};

function QuotePanel({ onBound }: { onBound: () => void }) {
  const [form, setForm] = useState<QuoteForm>(DEFAULT_FORM);
  const [quote, setQuote] = useState<PremiumQuote | null>(null);
  const [busy, setBusy] = useState(false);
  const [binding, setBinding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bound, setBound] = useState<InsurancePremiumRecord | null>(null);

  const selectPackage = (pkg: InsurancePackage) => {
    setForm((f) => ({ ...f, selectedPackage: pkg, activeLines: INSURANCE_PACKAGE_LINES[pkg] }));
    setQuote(null);
    setBound(null);
  };

  const toggleLine = (line: CoverLine) => {
    setForm((f) => {
      const next = f.activeLines.includes(line)
        ? f.activeLines.filter((l) => l !== line)
        : [...f.activeLines, line];
      return { ...f, activeLines: next, selectedPackage: null };
    });
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
          package: form.selectedPackage ?? undefined,
        },
      });
      setQuote(q);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const bindCover = async () => {
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

  const allLines = Object.keys(LINE_META) as CoverLine[];

  return (
    <div style={{ display: "grid", gap: "1.5rem" }}>
      {/* Package tier picker */}
      <section className="queue ars-panel" aria-label="Package tiers">
        <div className="section-heading" style={{ marginBottom: "0.75rem" }}>
          <span className="eyebrow">Step 1 — Choose a package</span>
          <strong>Cover packages</strong>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.75rem", marginBottom: "0.75rem" }}>
          {PACKAGES.map(({ id, eyebrow, tagline, color }) => {
            const active = form.selectedPackage === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => selectPackage(id)}
                className={`insurance-package${active ? " is-active" : ""}`}
                style={{ "--package-color": color } as CSSProperties}
                aria-pressed={active}
              >
                <div className="insurance-package-topline"><span>{eyebrow}</span><i>{active ? "Selected" : "Select"}</i></div>
                <strong>{id}</strong>
                <p>{tagline}</p>
                <div className="insurance-package-lines">
                  {INSURANCE_PACKAGE_LINES[id].map((l) => (
                    <span key={l}>
                      {LINE_META[l].badge}
                    </span>
                  ))}
                </div>
              </button>
            );
          })}
        </div>
        <p className="muted" style={{ fontSize: "0.75rem" }}>Or select individual lines below to build a custom cover.</p>
      </section>

      {/* Cover lines detail */}
      <section className="queue ars-panel" aria-label="Cover lines">
        <div className="section-heading" style={{ marginBottom: "0.75rem" }}>
          <span className="eyebrow">Step 2 — Review lines</span>
          <strong>Cover lines</strong>
          {form.selectedPackage && (
            <span className="dashboard-status status-settled" style={{ marginLeft: "auto", fontSize: "0.72rem" }}>
              {form.selectedPackage}
            </span>
          )}
        </div>
        <div style={{ display: "grid", gap: "0.5rem" }}>
          {allLines.map((line) => {
            const meta = LINE_META[line];
            const active = form.activeLines.includes(line);
            return (
              <label key={line} className={`cover-line${active ? " is-active" : ""}`}>
                <input type="checkbox" checked={active} onChange={() => toggleLine(line)} />
                <div>
                  <div className="cover-line-head">
                    <span className="cover-line-title">{meta.label}</span>
                    <span className="cover-line-badge">{meta.badge}</span>
                    <span className="cover-line-limit" title="Maximum payout the pool will make on this line">
                      up to {money(String(meta.limit))} USD
                    </span>
                  </div>
                  <span className="cover-line-desc">{meta.desc}</span>
                </div>
              </label>
            );
          })}
        </div>
      </section>

      {/* Transaction context */}
      <section className="queue ars-panel" aria-label="Transaction context">
        <div className="section-heading" style={{ marginBottom: "0.75rem" }}>
          <span className="eyebrow">Step 3 — Transaction context</span>
          <strong>Payment details</strong>
        </div>
        <div className="ars-form-grid">
          <label>
            <span>Agent address</span>
            <input name="agent-address" autoComplete="off" value={form.agentAddress} onChange={field(setForm, "agentAddress")} spellCheck={false} style={{ fontFamily: "monospace", fontSize: "0.78rem" }} />
          </label>
          <label>
            <span>Amount (USD)</span>
            <input name="transaction-amount" autoComplete="off" inputMode="decimal" value={form.amount} onChange={field(setForm, "amount")} />
          </label>
          <label>
            <span>Score band</span>
            <select name="score-band" autoComplete="off" value={form.scoreBand} onChange={field(setForm, "scoreBand")}>
              {SCORE_BANDS.map((b) => <option key={b}>{b}</option>)}
            </select>
          </label>
          <label>
            <span>Payment category</span>
            <select name="transaction-category" autoComplete="off" value={form.category} onChange={field(setForm, "category")}>
              {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
          <label>
            <span>Settlement tenor</span>
            <select name="tenor-band" autoComplete="off" value={form.tenorBand} onChange={field(setForm, "tenorBand")}>
              {TENOR_BANDS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </label>
          <label>
            <span>Counterparty risk</span>
            <select name="counterparty-band" autoComplete="off" value={form.cptyBand} onChange={field(setForm, "cptyBand")}>
              {CPTY_BANDS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
        </div>
        <label className="checkbox-label" style={{ marginTop: "0.75rem" }}>
          <input
            name="first-seen"
            type="checkbox"
            checked={form.firstSeen}
            onChange={(e) => setForm((f) => ({ ...f, firstSeen: e.target.checked }))}
          />
          <span>First-time counterparty <span className="muted">(adds novelty uplift to PD)</span></span>
        </label>
      </section>

      {/* Quote result */}
      <section className="queue ars-panel" aria-label="Quote result">
        <div className="section-heading" style={{ marginBottom: "0.75rem" }}>
          <span className="eyebrow">Step 4 — Get quote &amp; bind</span>
          <strong>Premium</strong>
        </div>

        {error && <p className="error" style={{ marginBottom: "0.75rem" }}>{error}</p>}

        <button
          className="primary-action"
          type="button"
          disabled={busy || form.activeLines.length === 0}
          onClick={() => void runQuote()}
          style={{ marginBottom: "1rem" }}
        >
          {busy ? "Pricing…" : "Get Quote"}
        </button>

        {quote && (
          <div style={{
            padding: "1rem",
            borderRadius: 8,
            border: `1px solid ${quote.decision === "OFFER" ? "#2a9d5c" : quote.decision === "REVIEW" ? "var(--orange)" : "#c0392b"}`,
            background: quote.decision === "OFFER" ? "rgba(42,157,92,0.06)" : quote.decision === "REVIEW" ? "rgba(209,103,31,0.06)" : "rgba(192,57,43,0.06)",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.75rem", flexWrap: "wrap" }}>
              <span className={`dashboard-status ${decisionClass(quote.decision)}`} style={{ fontSize: "0.8rem", fontWeight: 800 }}>{quote.decision}</span>
              <span style={{ fontWeight: 800, fontSize: "1.1rem" }}>{money(quote.premium)} USD</span>
              <span className="muted" style={{ fontSize: "0.75rem" }}>
                PD {(quote.pd * 100).toFixed(3)}% · cred {(quote.credibility * 100).toFixed(1)}%
              </span>
            </div>
            <p className="muted" style={{ fontSize: "0.8rem", marginBottom: "0.6rem" }}>{quote.reason}</p>

            {Object.keys(quote.lines).length > 0 && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "0.4rem", marginBottom: "0.75rem" }}>
                {Object.entries(quote.lines).map(([line, prem]) => (
                  <div key={line} style={{
                    padding: "0.4rem 0.6rem", borderRadius: 6,
                    background: "rgba(255,255,255,0.05)",
                    border: "1px solid var(--border)",
                  }}>
                    <div style={{ fontSize: "0.68rem", color: "var(--muted)", marginBottom: "0.1rem" }}>
                      {LINE_META[line as CoverLine]?.label ?? line.replace(/_/g, " ")}
                    </div>
                    <div style={{ fontWeight: 700, fontSize: "0.85rem" }}>{money(prem)} USD</div>
                  </div>
                ))}
              </div>
            )}

            <p className="muted" style={{ fontSize: "0.68rem", marginBottom: "0.75rem" }}>
              Receipt hash: <code style={{ fontSize: "0.68rem" }}>{hashShort(quote.receiptHash)}</code>
              {" "}· Reproducible: SHA-256 of quote inputs/outputs
            </p>

            {quote.decision === "OFFER" && !bound && (
              <button className="primary-action" type="button" onClick={() => void bindCover()} disabled={binding}>
                {binding ? "Collecting premium on-chain…" : "Bind Cover & Pay Premium"}
              </button>
            )}
            {quote.decision === "REVIEW" && (
              <p className="muted" style={{ fontSize: "0.78rem" }}>
                Pool capacity insufficient for this exposure — quote escalated. Increase LP capital or reduce cover amount.
              </p>
            )}
            {quote.decision === "DECLINE" && (
              <p className="muted" style={{ fontSize: "0.78rem" }}>
                Agent or transaction ineligible. Check eligibility and score band.
              </p>
            )}
            {bound && (
              <div style={{
                marginTop: "0.75rem", padding: "0.6rem 0.75rem", borderRadius: 6,
                background: "rgba(42,157,92,0.1)", border: "1px solid #2a9d5c",
              }}>
                <div style={{ fontWeight: 700, fontSize: "0.85rem", color: "#2a9d5c", marginBottom: "0.2rem" }}>
                  Cover bound — {money(bound.premiumAmount)} {bound.currency} collected
                </div>
                {bound.txHash
                  ? <a href={bound.explorerUrl ?? "#"} target="_blank" rel="noreferrer" style={{ color: "var(--orange)", fontSize: "0.75rem" }}>
                      {hashShort(bound.txHash)} — view on explorer ↗
                    </a>
                  : <span className="muted" style={{ fontSize: "0.75rem" }}>Simulated (mock mode)</span>
                }
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

// ── Agent Risk Panel ──────────────────────────────────────────────────────────

const BAND_COLORS: Record<string, string> = {
  ELITE: "#2a9d5c",
  HIGH: "#4a9fd1",
  STANDARD: "var(--muted)",
  HIGH_RISK: "#c0392b",
};

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

  const bandColor = risk ? (BAND_COLORS[risk.scoreBand ?? "STANDARD"] ?? "var(--muted)") : "var(--muted)";
  const credPct = risk ? risk.credibility * 100 : 0;

  return (
    <section className="queue ars-panel" aria-label="Agent risk state">
      <div className="section-heading" style={{ marginBottom: "0.75rem" }}>
        <span className="eyebrow">Bayesian risk model</span>
        <strong>Agent Risk State</strong>
      </div>
      <p className="muted" style={{ marginBottom: "1rem", fontSize: "0.8rem" }}>
        Each agent's default probability is a Beta(α, β) posterior. α tracks observed defaults,
        β tracks successes. As credibility rises toward 100%, the agent's own track record
        overtakes the band prior — a clean history lowers premiums.
      </p>
      {error && <p className="error" style={{ marginBottom: "0.5rem" }}>{error}</p>}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.25rem" }}>
        <input
          name="risk-agent-address"
          autoComplete="off"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="XRPL address"
          style={{ flex: 1, background: "rgba(255,255,255,0.05)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--paper)", padding: "0.35rem 0.6rem", fontSize: "0.8rem", fontFamily: "monospace" }}
        />
        <button className="primary-action" type="button" disabled={busy} onClick={() => void lookup()}>
          {busy ? "…" : "Lookup"}
        </button>
      </div>

      {risk && (
        <div style={{ display: "grid", gap: "1rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
            <div>
              <span className="eyebrow" style={{ fontSize: "0.68rem" }}>Score band</span>
              <p style={{ margin: "0.15rem 0 0", fontWeight: 800, fontSize: "1.1rem", color: bandColor }}>{risk.scoreBand}</p>
            </div>
            <div>
              <span className="eyebrow" style={{ fontSize: "0.68rem" }}>Probability of default</span>
              <p style={{ margin: "0.15rem 0 0", fontWeight: 800, fontSize: "1.1rem", color: risk.pd > 0.05 ? "#c0392b" : "#2a9d5c" }}>
                {(risk.pd * 100).toFixed(3)}%
              </p>
            </div>
          </div>

          <div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.25rem" }}>
              <span className="muted" style={{ fontSize: "0.72rem" }}>Credibility (own history vs band prior)</span>
              <span style={{ fontSize: "0.72rem", fontWeight: 700, color: credPct > 60 ? "#2a9d5c" : "var(--muted)" }}>{credPct.toFixed(1)}%</span>
            </div>
            <div style={{ background: "rgba(255,255,255,0.08)", borderRadius: 4, height: 6 }}>
              <div style={{ width: `${credPct}%`, background: credPct > 60 ? "#2a9d5c" : "var(--orange)", borderRadius: 4, height: "100%", transition: "width 0.4s" }} />
            </div>
          </div>

          <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap" }}>
            {[
              ["α — observed defaults", risk.alpha.toFixed(3)],
              ["β — observed successes", risk.beta.toFixed(3)],
            ].map(([label, value]) => (
              <div key={label}>
                <span className="eyebrow" style={{ fontSize: "0.68rem" }}>{label}</span>
                <p style={{ margin: "0.15rem 0 0", fontWeight: 700, fontFamily: "monospace" }}>{value}</p>
              </div>
            ))}
          </div>

          <p className="muted" style={{ fontSize: "0.72rem" }}>
            Premium for this agent is a credibility-weighted blend of the {risk.scoreBand} band prior and
            the agent's own observed default rate. A default event moves α up and raises future premiums;
            a clean settlement moves β up and lowers them.
          </p>
        </div>
      )}
    </section>
  );
}

// ── History Panel ─────────────────────────────────────────────────────────────

function HistoryPanel({ premiums, payouts }: { premiums: InsurancePremiumRecord[]; payouts: InsurancePayoutRecord[] }) {
  const totalPremiums = premiums.reduce((s, p) => s + parseFloat(p.premiumAmount), 0);
  const totalPayouts = payouts.reduce((s, p) => s + parseFloat(p.totalPaid), 0);
  const lossRatio = totalPremiums > 0 ? (totalPayouts / totalPremiums) * 100 : 0;

  return (
    <div style={{ display: "grid", gap: "1.5rem" }}>
      {/* Summary metrics */}
      <section className="queue ars-panel" aria-label="Portfolio summary">
        <div className="section-heading" style={{ marginBottom: "0.75rem" }}>
          <span className="eyebrow">Portfolio</span>
          <strong>Insurance economics</strong>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "2rem" }}>
          {[
            ["Gross written premium", `${money(String(totalPremiums))} USD`],
            ["Total payouts", `${money(String(totalPayouts))} USD`],
            ["Loss ratio", `${lossRatio.toFixed(1)}%`],
            ["Premiums collected", String(premiums.length)],
            ["Claims settled", String(payouts.length)],
          ].map(([label, value]) => (
            <div key={label}>
              <span className="eyebrow" style={{ fontSize: "0.68rem" }}>{label}</span>
              <p style={{ margin: "0.15rem 0 0", fontWeight: 700, fontSize: "0.95rem" }}>{value}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Premiums */}
      <section className="queue ars-panel" aria-label="Premium history">
        <div className="section-heading" style={{ marginBottom: "0.75rem" }}>
          <span className="eyebrow">Premiums collected</span>
          <strong>{premiums.length} premiums · {money(String(totalPremiums))} USD total</strong>
        </div>
        {premiums.length === 0 ? (
          <p className="muted" style={{ fontSize: "0.82rem" }}>No premiums collected yet. Quote and bind a cover to see it here.</p>
        ) : (
          <ul className="credential-log">
            {premiums.map((p) => (
              <li key={p.id} className="decision-row">
                <div style={{ flex: 1, display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
                  <strong style={{ fontSize: "0.88rem" }}>{money(p.premiumAmount)} {p.currency}</strong>
                  <span className="dashboard-status status-settled" style={{ fontSize: "0.68rem" }}>{p.scoreBand ?? "STANDARD"}</span>
                  <span className="muted" style={{ fontSize: "0.72rem", fontFamily: "monospace" }}>
                    {p.agentAddress ? p.agentAddress.slice(0, 10) + "…" : ""}
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.1rem" }}>
                  {p.txHash
                    ? <a href={p.explorerUrl ?? "#"} target="_blank" rel="noreferrer" style={{ color: "var(--orange)", fontSize: "0.72rem" }}>{hashShort(p.txHash)} ↗</a>
                    : <span className="muted" style={{ fontSize: "0.72rem" }}>simulated</span>
                  }
                  <span className="muted" style={{ fontSize: "0.68rem" }}>{new Date(p.createdAt).toLocaleString()}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Claims */}
      <section className="queue ars-panel" aria-label="Claim history">
        <div className="section-heading" style={{ marginBottom: "0.75rem" }}>
          <span className="eyebrow">Claims settled</span>
          <strong>{payouts.length} claims · {money(String(totalPayouts))} USD paid</strong>
        </div>
        {payouts.length === 0 ? (
          <p className="muted" style={{ fontSize: "0.82rem" }}>No claims settled yet.</p>
        ) : (
          <ul className="credential-log">
            {payouts.map((p) => (
              <li key={p.id} className="decision-row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
                <div style={{ flex: 1, display: "grid", gap: "0.2rem" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <strong style={{ fontSize: "0.88rem" }}>{money(p.totalPaid)} {p.currency} paid</strong>
                    {p.reputationMptProtected && (
                      <span className="dashboard-status status-settled" style={{ fontSize: "0.68rem" }}>Rep protected</span>
                    )}
                  </div>
                  <div className="muted" style={{ fontSize: "0.72rem" }}>
                    Collateral slashed: {money(p.collateralSlashed)} · Pool drawn: {money(p.poolDrawn)}
                  </div>
                  <div className="muted" style={{ fontSize: "0.68rem", fontFamily: "monospace" }}>
                    {p.merchant ? `→ ${p.merchant.slice(0, 14)}…` : ""}
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.1rem" }}>
                  {p.poolDrawTxHash
                    ? <a href={`#tx-${p.poolDrawTxHash}`} target="_blank" rel="noreferrer" style={{ color: "var(--orange)", fontSize: "0.72rem" }}>{hashShort(p.poolDrawTxHash)} ↗</a>
                    : <span className="muted" style={{ fontSize: "0.72rem" }}>simulated</span>
                  }
                  <span className="muted" style={{ fontSize: "0.68rem" }}>{new Date(p.createdAt).toLocaleString()}</span>
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
    { id: "quote", label: "Quote & Bind" },
    { id: "risk", label: "Agent Risk" },
    { id: "history", label: `Portfolio (${premiums.length + payouts.length})` },
  ];

  const capPct = pool ? Math.min(100, pool.capacityRatio * 100) : null;
  const portfolioEvents = premiums.length + payouts.length;

  return (
    <div className="insurance-page">
      <header className="insurance-hero">
        <div className="insurance-hero-copy">
          <div className="insurance-live-pill"><span /> Insurance protocol live</div>
          <p className="insurance-kicker">Autonomous risk infrastructure</p>
          <h1>Put every agent payment<br /><em>inside a safety net.</em></h1>
          <p className="insurance-intro">
            Deterministic underwriting for autonomous commerce. Price risk, bind cover, and settle
            verified claims against an auditable XRPL trail.
          </p>
          <div className="insurance-trust-row" aria-label="Protocol safeguards">
            <span><b>01</b> Code-priced</span>
            <span><b>02</b> Vault-backed</span>
            <span><b>03</b> Ledger-verifiable</span>
          </div>
        </div>
        <div className="insurance-hero-stats" aria-label="Insurance overview">
          <div className="insurance-hero-stat insurance-hero-stat-primary">
            <span>Vault balance</span>
            <strong>{pool ? money(pool.vaultBalance) : "—"}</strong>
            <small>{pool?.currency ?? "USD"} backing active cover</small>
          </div>
          <div className="insurance-hero-stat">
            <span>Capacity</span>
            <strong>{capPct === null ? "—" : `${capPct.toFixed(1)}%`}</strong>
            <small>available for new exposure</small>
          </div>
          <div className="insurance-hero-stat">
            <span>Ledger events</span>
            <strong>{portfolioEvents}</strong>
            <small>premiums and settled claims</small>
          </div>
        </div>
      </header>

      <section className="insurance-pool" aria-label="Pool status">
        <div className="insurance-section-title">
          <div><span className="eyebrow">Insurance Vault · XLS-65</span><h2>Capital health</h2></div>
          <span className="insurance-proof-pill">On-ledger accounting</span>
        </div>
        <PoolPanel pool={pool} />
      </section>

      <nav className="insurance-tabs" aria-label="Insurance workspace">
        {tabs.map((t) => (
          <button key={t.id} type="button"
            onClick={() => setTab(t.id)}
            className={tab === t.id ? "is-active" : ""}
            aria-current={tab === t.id ? "page" : undefined}
          >
            <span>{String(tabs.indexOf(t) + 1).padStart(2, "0")}</span>
            {t.label}
          </button>
        ))}
      </nav>

      <div className="insurance-workspace">
        {tab === "quote" && <QuotePanel onBound={() => void refresh()} />}
        {tab === "risk" && <AgentRiskPanel />}
        {tab === "history" && <HistoryPanel premiums={premiums} payouts={payouts} />}
      </div>
    </div>
  );
}
