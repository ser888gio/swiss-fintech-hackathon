import { useCallback, useEffect, useState } from "react";
import type { CoverPolicy, CoverPoolStatus, CoverPayout, CoverQuote } from "@treasury/shared";

import { api } from "../lib/api.js";

function money(value: string | number, currency = "RLUSD") {
  const amount = Number(value);
  return `${Number.isFinite(amount) ? amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : value} ${currency}`;
}

export function CoverPage() {
  const [pool, setPool] = useState<CoverPoolStatus | null>(null);
  const [policies, setPolicies] = useState<CoverPolicy[]>([]);
  const [payouts, setPayouts] = useState<CoverPayout[]>([]);
  const [quote, setQuote] = useState<CoverQuote | null>(null);
  const [coverCap, setCoverCap] = useState("5000");
  const [perClaimLimit, setPerClaimLimit] = useState("500");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [nextPool, nextPolicies, nextPayouts] = await Promise.all([
        api.coverPool(),
        api.coverPolicies(),
        api.coverPayouts(),
      ]);
      setPool(nextPool);
      setPolicies(nextPolicies);
      setPayouts(nextPayouts);
    } catch (cause) {
      setError(String(cause));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const getQuote = async () => {
    setBusy(true);
    setError(null);
    try {
      setQuote(await api.coverQuote({
        agentAddress: "",
        scoreBand: "STANDARD",
        coverCap,
        perClaimLimit,
        termDays: 365,
      }));
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  };

  const bindCover = async () => {
    if (!quote || quote.decision !== "OFFER") return;
    setBusy(true);
    setError(null);
    try {
      await api.coverBind({
        agentAddress: "",
        scoreBand: "STANDARD",
        coverCap,
        perClaimLimit,
        termDays: 365,
        quote,
      });
      setQuote(null);
      await refresh();
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  };

  const activePolicy = policies.find((policy) => policy.status === "active");

  return (
    <div className="cover-page">
      <header className="cover-hero">
        <div>
          <span className="eyebrow">Agent risk infrastructure</span>
          <h1>Agent Cover</h1>
          <p>Annual captive protection for losses caused by autonomous payment errors. One premium covers the period; claims remain deterministic and auditable.</p>
        </div>
        <span className={`dashboard-status status-${activePolicy ? "settled" : "routing"}`}>
          {activePolicy ? "Cover active" : "Not covered"}
        </span>
      </header>

      {error && <p className="error" role="alert">{error}</p>}

      <section className="cover-grid" aria-label="Cover overview">
        <article className="dashboard-panel">
          <div className="panel-heading"><div><span className="eyebrow">Captive pool</span><h2>Capacity</h2></div></div>
          {pool ? (
            <dl className="cover-metrics">
              <div><dt>First-loss capital</dt><dd>{money(pool.firstLoss, pool.currency)}</dd></div>
              <div><dt>Free capacity</dt><dd>{money(pool.freeCapacity, pool.currency)}</dd></div>
              <div><dt>Cover in force</dt><dd>{money(pool.coverInForce, pool.currency)}</dd></div>
              <div><dt>Claims paid</dt><dd>{money(pool.claimsPaid, pool.currency)}</dd></div>
            </dl>
          ) : <p className="muted">Loading pool status…</p>}
        </article>

        <article className="dashboard-panel">
          <div className="panel-heading"><div><span className="eyebrow">Annual policy</span><h2>{activePolicy ? "Current protection" : "Create protection"}</h2></div></div>
          {activePolicy ? (
            <dl className="cover-metrics">
              <div><dt>Cover cap</dt><dd>{money(activePolicy.coverCap)}</dd></div>
              <div><dt>Remaining</dt><dd>{money(activePolicy.coverRemaining)}</dd></div>
              <div><dt>Per-claim limit</dt><dd>{money(activePolicy.perClaimLimit)}</dd></div>
              <div><dt>Expires</dt><dd>{new Date(activePolicy.periodEnd).toLocaleDateString()}</dd></div>
            </dl>
          ) : (
            <div className="cover-form">
              <label>Cover cap (RLUSD)<input type="number" min="100" value={coverCap} onChange={(event) => setCoverCap(event.target.value)} /></label>
              <label>Per-claim limit (RLUSD)<input type="number" min="50" value={perClaimLimit} onChange={(event) => setPerClaimLimit(event.target.value)} /></label>
              <button className="dashboard-primary" type="button" onClick={() => void getQuote()} disabled={busy}>{busy ? "Pricing…" : "Get annual quote"}</button>
            </div>
          )}
          {quote && (
            <div className="cover-quote">
              <span className="eyebrow">{quote.decision}</span>
              <strong>{money(quote.premium)} / year</strong>
              <p>{quote.reason ?? `${money(quote.coverCap)} total cover with a ${money(quote.perClaimLimit)} per-claim limit.`}</p>
              {quote.decision === "OFFER" && <button className="dashboard-primary" type="button" onClick={() => void bindCover()} disabled={busy}>Bind cover</button>}
            </div>
          )}
        </article>
      </section>

      <section className="dashboard-panel">
        <div className="panel-heading"><div><span className="eyebrow">Verified history</span><h2>Claim payouts</h2></div></div>
        {payouts.length === 0 ? <p className="muted">No claims have been paid.</p> : (
          <div className="cover-payouts">
            {payouts.map((payout) => (
              <article key={payout.id}>
                <div><strong>{payout.classification}</strong><small>{new Date(payout.createdAt).toLocaleString()}</small></div>
                <span>{money(payout.amountPaid)}</span>
                {payout.explorerUrl ? <a href={payout.explorerUrl} target="_blank" rel="noreferrer">Explorer ↗</a> : <span className="muted">No ledger proof</span>}
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
