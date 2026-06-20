import { useCallback, useEffect, useState } from "react";
import type {
  CoverPolicy,
  CoverPoolStatus,
  CoverPayout,
  CoverQuote,
} from "@treasury/shared";
import { api } from "../lib/api.js";

function fmt(v: string | number): string {
  const n = typeof v === "string" ? parseFloat(v) : v;
  return isNaN(n) ? String(v) : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(n: number): string {
  return (n * 100).toFixed(1) + "%";
}

function statusPill(s: string) {
  const cls =
    s === "active" ? "status-settled"
    : s === "expired" ? "status-blocked"
    : s === "exhausted" ? "status-blocked"
    : "status-routing";
  return <span className={`status-pill ${cls}`}>{s}</span>;
}

export function CoverPage() {
  const [pool, setPool] = useState<CoverPoolStatus | null>(null);
  const [policies, setPolicies] = useState<CoverPolicy[]>([]);
  const [payouts, setPayouts] = useState<CoverPayout[]>([]);
  const [quote, setQuote] = useState<CoverQuote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demoResult, setDemoResult] = useState<{ description: string; narration: string | null; amountPaid: string } | null>(null);

  const [coverCap, setCoverCap] = useState("5000");
  const [perClaim, setPerClaim] = useState("500");
  const [termDays, setTermDays] = useState("365");

  const refresh = useCallback(async () => {
    try {
      const [p, po, pay] = await Promise.all([
        api.coverPool(),
        api.coverPolicies(),
        api.coverPayouts(),
      ]);
      setPool(p);
      setPolicies(po);
      setPayouts(pay);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const getQuote = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      const q = await api.coverQuote({
        agentAddress: "",           // backend uses treasury wallet
        scoreBand: "STANDARD",
        coverCap,
        perClaimLimit: perClaim,
        termDays: parseInt(termDays, 10),
      });
      setQuote(q);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [coverCap, perClaim, termDays]);

  const buyPolicy = useCallback(async () => {
    if (!quote || quote.decision !== "OFFER") return;
    setError(null);
    setBusy(true);
    try {
      await api.coverBind({
        agentAddress: "",
        scoreBand: "STANDARD",
        coverCap,
        perClaimLimit: perClaim,
        termDays: parseInt(termDays, 10),
        quote,
      });
      setQuote(null);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [quote, coverCap, perClaim, termDays, refresh]);

  const runDemo41 = useCallback(async () => {
    setError(null);
    setDemoResult(null);
    setBusy(true);
    try {
      const r = await api.coverRunDemo41();
      setDemoResult({
        description: r.description,
        narration: r.narration,
        amountPaid: r.payout.amountPaid,
      });
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const activePolicy = policies.find((p) => p.status === "active");
  const usedPct = activePolicy
    ? Math.min(100, (parseFloat(activePolicy.coverUsed) / parseFloat(activePolicy.coverCap)) * 100)
    : 0;

  return (
    <div className="ars-panel-grid">
      <h1 className="section-title">Agent Cover</h1>
      <p className="muted" style={{ marginBottom: "1.5rem" }}>
        Annual captive risk pool — one premium from the shared treasury wallet covers hallucination losses
        for the period. No per-transaction fees.
      </p>

      {error && <p className="error">{error}</p>}

      {/* Pool status */}
      <section className="ars-panel">
        <h2 className="panel-title eyebrow">Pool status</h2>
        {pool ? (
          <div className="stats-grid">
            <div className="stat-cell">
              <span className="stat-label">First-loss capital</span>
              <span className="stat-value">{fmt(pool.firstLoss)} {pool.currency}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Reserved (active policies)</span>
              <span className="stat-value">{fmt(pool.reserved)} {pool.currency}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Free capacity</span>
              <span className="stat-value">{fmt(pool.freeCapacity)} {pool.currency}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Premiums collected</span>
              <span className="stat-value">{fmt(pool.premiumsCollected)} {pool.currency}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Claims paid</span>
              <span className="stat-value">{fmt(pool.claimsPaid)} {pool.currency}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Capacity ratio</span>
              <span className="stat-value">{pct(pool.capacityRatio)}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Active policies</span>
              <span className="stat-value">{pool.policiesActive}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Cover in force</span>
              <span className="stat-value">{fmt(pool.coverInForce)} {pool.currency}</span>
            </div>
          </div>
        ) : (
          <p className="muted">Loading pool status…</p>
        )}
      </section>

      {/* Active policy */}
      {activePolicy && (
        <section className="ars-panel">
          <h2 className="panel-title eyebrow">Active policy</h2>
          <div className="stats-grid">
            <div className="stat-cell">
              <span className="stat-label">Score band</span>
              <span className="stat-value">{activePolicy.scoreBand}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Cover cap</span>
              <span className="stat-value">{fmt(activePolicy.coverCap)}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Per-claim limit</span>
              <span className="stat-value">{fmt(activePolicy.perClaimLimit)}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Premium paid</span>
              <span className="stat-value">{fmt(activePolicy.premium)}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Status</span>
              <span className="stat-value">{statusPill(activePolicy.status)}</span>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Expires</span>
              <span className="stat-value">{new Date(activePolicy.periodEnd).toLocaleDateString()}</span>
            </div>
          </div>
          <div style={{ margin: "1rem 0" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", marginBottom: "0.25rem" }}>
              <span className="muted">Cover used: {fmt(activePolicy.coverUsed)}</span>
              <span className="muted">Remaining: {fmt(activePolicy.coverRemaining)}</span>
            </div>
            <div style={{ background: "#e5e7eb", borderRadius: "4px", height: "8px", overflow: "hidden" }}>
              <div style={{ width: `${usedPct}%`, background: usedPct > 80 ? "#ef4444" : "#22c55e", height: "100%", transition: "width 0.3s" }} />
            </div>
          </div>
          {activePolicy.premiumTxHash && (
            <p className="muted" style={{ fontSize: "0.75rem" }}>
              Premium tx: <code>{activePolicy.premiumTxHash.slice(0, 16)}…</code>
            </p>
          )}
        </section>
      )}

      {/* Buy policy */}
      {!activePolicy && (
        <section className="ars-panel">
          <h2 className="panel-title eyebrow">Buy annual cover</h2>
          <div className="form-row" style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginBottom: "1rem" }}>
            <label className="field-label">
              Cover cap (RLUSD)
              <input className="field-input" type="number" value={coverCap} onChange={(e) => setCoverCap(e.target.value)} min="100" max="500000" />
            </label>
            <label className="field-label">
              Per-claim limit (RLUSD)
              <input className="field-input" type="number" value={perClaim} onChange={(e) => setPerClaim(e.target.value)} min="50" max="50000" />
            </label>
            <label className="field-label">
              Term (days)
              <input className="field-input" type="number" value={termDays} onChange={(e) => setTermDays(e.target.value)} min="30" max="365" />
            </label>
          </div>
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button className="btn btn-secondary" type="button" onClick={getQuote} disabled={busy}>
              Get quote
            </button>
            {quote && quote.decision === "OFFER" && (
              <button className="btn btn-primary" type="button" onClick={buyPolicy} disabled={busy}>
                Buy — {fmt(quote.premium)} RLUSD
              </button>
            )}
          </div>
          {quote && (
            <div className="ars-log-panel" style={{ marginTop: "1rem", padding: "0.75rem" }}>
              <p className="muted" style={{ marginBottom: "0.5rem" }}>
                Decision: <strong>{quote.decision}</strong>
                {quote.reason ? ` — ${quote.reason}` : ""}
              </p>
              <p className="muted">
                Premium: <strong>{fmt(quote.premium)} RLUSD</strong> for {quote.termDays} days
              </p>
              <p className="muted">
                Cover: {fmt(quote.coverCap)} cap · {fmt(quote.perClaimLimit)} per claim
              </p>
              <p className="muted" style={{ fontSize: "0.7rem" }}>
                Lines: {Object.entries(quote.lineRates).map(([k, v]) => `${k} @ ${(parseFloat(v) * 100).toFixed(2)}% p.a.`).join(", ")}
              </p>
            </div>
          )}
        </section>
      )}

      {/* Demo 4.1 */}
      <section className="ars-panel">
        <h2 className="panel-title eyebrow">Demo 4.1 — Underpayment hallucination</h2>
        <p className="muted" style={{ marginBottom: "1rem" }}>
          Sends a $480 payment against a $500 invoice (below the $500 Firefly threshold — no hardware needed).
          The reconciler detects the $20 shortfall and the pool tops up the merchant automatically.
        </p>
        <button className="btn btn-primary" type="button" onClick={runDemo41} disabled={busy}>
          {busy ? "Running…" : "Run demo 4.1"}
        </button>
        {demoResult && (
          <div className="ars-log-panel" style={{ marginTop: "1rem", padding: "0.75rem" }}>
            <p style={{ marginBottom: "0.5rem" }}>{demoResult.description}</p>
            <p className="muted" style={{ marginBottom: "0.5rem" }}>Amount paid to merchant: <strong>{fmt(demoResult.amountPaid)} RLUSD</strong></p>
            {demoResult.narration && (
              <blockquote style={{ borderLeft: "2px solid #6366f1", paddingLeft: "0.75rem", margin: "0.5rem 0", fontStyle: "italic", fontSize: "0.85rem" }}>
                {demoResult.narration}
              </blockquote>
            )}
          </div>
        )}
      </section>

      {/* Payouts history */}
      {payouts.length > 0 && (
        <section className="ars-panel">
          <h2 className="panel-title eyebrow">Payouts</h2>
          <div className="ars-log-panel">
            {payouts.map((p) => (
              <div key={p.id} style={{ padding: "0.5rem 0", borderBottom: "1px solid #f3f4f6" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem" }}>
                  <span><strong>{p.classification}</strong> · {p.line}</span>
                  <span>{fmt(p.amountPaid)} RLUSD → {p.lossBearerKind}</span>
                </div>
                {p.narration && <p className="muted" style={{ fontSize: "0.75rem", marginTop: "0.25rem" }}>{p.narration}</p>}
                {p.txHash && (
                  <p className="muted" style={{ fontSize: "0.7rem" }}>
                    tx: <code>{p.txHash.slice(0, 20)}…</code>
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* All policies */}
      {policies.length > 0 && (
        <section className="ars-panel">
          <h2 className="panel-title eyebrow">All policies</h2>
          <table style={{ width: "100%", fontSize: "0.8rem", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e5e7eb" }}>
                <th style={{ textAlign: "left", padding: "0.4rem" }}>Status</th>
                <th style={{ textAlign: "left", padding: "0.4rem" }}>Cap</th>
                <th style={{ textAlign: "left", padding: "0.4rem" }}>Used</th>
                <th style={{ textAlign: "left", padding: "0.4rem" }}>Remaining</th>
                <th style={{ textAlign: "left", padding: "0.4rem" }}>Expires</th>
              </tr>
            </thead>
            <tbody>
              {policies.map((p) => (
                <tr key={p.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "0.4rem" }}>{statusPill(p.status)}</td>
                  <td style={{ padding: "0.4rem" }}>{fmt(p.coverCap)}</td>
                  <td style={{ padding: "0.4rem" }}>{fmt(p.coverUsed)}</td>
                  <td style={{ padding: "0.4rem" }}>{fmt(p.coverRemaining)}</td>
                  <td style={{ padding: "0.4rem" }}>{new Date(p.periodEnd).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
