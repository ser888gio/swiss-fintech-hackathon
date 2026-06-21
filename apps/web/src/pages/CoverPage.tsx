import { useCallback, useEffect, useState } from "react";
import type { Agent, CoverPolicy, CoverPoolStatus, CoverPayout, CoverQuote } from "@treasury/shared";

import { api } from "../lib/api.js";

const PERIL_LABELS: Record<string, { title: string; description: string }> = {
  hallucination: {
    title: "Wrong-amount payment",
    description: "Agent pays an invoice with a wrong amount (hallucinated or miscalculated) — loss to your treasury or counterparty.",
  },
  non_delivery: {
    title: "Non-delivery / wrong recipient",
    description: "Agent sends funds to the wrong XRPL address, or the counterparty accepts payment but never delivers.",
  },
  fx_slippage: {
    title: "FX slippage",
    description: "Agent locks in a cross-currency route and the rate moves beyond tolerance before settlement — treasury absorbs the shortfall.",
  },
  mandate_breach: {
    title: "Mandate breach",
    description: "Agent exceeds its approved spending scope (over limit, blocked category, unauthorised counterparty) and the payment cannot be recalled.",
  },
  counterparty_default: {
    title: "Counterparty default",
    description: "Agent pays a merchant who subsequently defaults or becomes unreachable — goods or services are never delivered.",
  },
};

const ALL_LINES = ["hallucination", "non_delivery", "fx_slippage", "mandate_breach", "counterparty_default"] as const;

function money(value: string | number, currency = "RLUSD") {
  const amount = Number(value);
  return `${Number.isFinite(amount) ? amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : value} ${currency}`;
}

function pct(rate: string) {
  return `${(Number(rate) * 100).toFixed(2)} %`;
}

export function CoverPage() {
  const [pool, setPool] = useState<CoverPoolStatus | null>(null);
  const [policies, setPolicies] = useState<CoverPolicy[]>([]);
  const [payouts, setPayouts] = useState<CoverPayout[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [selectedLines, setSelectedLines] = useState<Set<string>>(new Set(ALL_LINES));
  const [quote, setQuote] = useState<CoverQuote | null>(null);
  const [coverCap, setCoverCap] = useState("5000");
  const [perClaimLimit, setPerClaimLimit] = useState("500");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedAgent = agents.find((a) => a.id === selectedAgentId) ?? null;

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [nextPool, nextPolicies, nextPayouts, nextAgents] = await Promise.all([
        api.coverPool(),
        api.coverPolicies(),
        api.coverPayouts(),
        api.listAgents(),
      ]);
      setPool(nextPool);
      setPolicies(nextPolicies);
      setPayouts(nextPayouts);
      setAgents(nextAgents);
      if (!selectedAgentId && nextAgents.length > 0) {
        const first = nextAgents[0];
        setSelectedAgentId(first.id);
        setCoverCap(first.maxDailySpend || "5000");
        setPerClaimLimit(first.maxSinglePayment || "500");
      }
    } catch (cause) {
      setError(String(cause));
    }
  }, [selectedAgentId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const handleAgentChange = (agentId: string) => {
    setSelectedAgentId(agentId);
    setQuote(null);
    const agent = agents.find((a) => a.id === agentId);
    if (agent) {
      setCoverCap(agent.maxDailySpend || "5000");
      setPerClaimLimit(agent.maxSinglePayment || "500");
    }
  };

  const toggleLine = (line: string) => {
    setSelectedLines((prev) => {
      const next = new Set(prev);
      if (next.has(line)) {
        if (next.size > 1) next.delete(line); // at least one line required
      } else {
        next.add(line);
      }
      return next;
    });
    setQuote(null);
  };

  const activeLines = ALL_LINES.filter((l) => selectedLines.has(l)) as import("@treasury/shared").CoverLineKind[];

  const getQuote = async () => {
    setBusy(true);
    setError(null);
    try {
      setQuote(await api.coverQuote({
        agentAddress: selectedAgentId || "default",
        scoreBand: "STANDARD",
        coverCap,
        perClaimLimit,
        termDays: 365,
        lines: activeLines,
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
        agentAddress: selectedAgentId || "default",
        scoreBand: "STANDARD",
        coverCap,
        perClaimLimit,
        termDays: 365,
        lines: activeLines,
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

  // Build per-agent coverage lookup: agentId → active policy
  const policyByAgent = new Map<string, CoverPolicy>();
  for (const p of policies) {
    if (p.status === "active" && !policyByAgent.has(p.agentAddress)) {
      policyByAgent.set(p.agentAddress, p);
    }
  }

  const activePolicy = selectedAgent ? policyByAgent.get(selectedAgent.id) ?? null : null;

  return (
    <div className="cover-page">
      <div style={{ padding: "0.55rem 0.75rem", marginBottom: "1rem", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: "0.82rem", lineHeight: 1.5 }}>
        <strong style={{ color: "var(--paper)" }}>Agent Cover</strong> — professional liability insurance for autonomous agents. When an agent causes a payment loss, the cover backs it. One annual premium per agent; claims remain deterministic and auditable on XRPL.
      </div>

      <header className="cover-hero">
        <div>
          <span className="eyebrow">Agent risk infrastructure</span>
          <h1>Agent Cover</h1>
          <p>Annual professional liability for losses caused by autonomous payment errors. Each agent is insured individually; one premium per agent covers the period.</p>
        </div>
        <span className={`dashboard-status status-${policyByAgent.size > 0 ? "settled" : "routing"}`}>
          {policyByAgent.size > 0 ? `${policyByAgent.size} agent${policyByAgent.size > 1 ? "s" : ""} covered` : "No agents covered"}
        </span>
      </header>

      {error && <p className="error" role="alert">{error}</p>}

      {/* Pool capacity */}
      <section className="dashboard-panel">
        <div className="panel-heading"><div><span className="eyebrow">Captive pool</span><h2>Capacity</h2></div></div>
        {pool ? (
          <dl className="cover-metrics">
            <div><dt>First-loss capital</dt><dd>{money(pool.firstLoss, pool.currency)}</dd></div>
            <div><dt>Free capacity</dt><dd>{money(pool.freeCapacity, pool.currency)}</dd></div>
            <div><dt>Cover in force</dt><dd>{money(pool.coverInForce, pool.currency)}</dd></div>
            <div><dt>Claims paid</dt><dd>{money(pool.claimsPaid, pool.currency)}</dd></div>
          </dl>
        ) : <p className="muted">Loading pool status…</p>}
      </section>

      {/* Insured agents table */}
      <section className="dashboard-panel">
        <div className="panel-heading"><div><span className="eyebrow">Coverage overview</span><h2>Insured agents</h2></div></div>
        {agents.length === 0 ? (
          <p className="muted">No agents found. Create an agent first.</p>
        ) : (
          <div className="cover-agents-table-wrap">
            <table className="cover-agents-table">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Status</th>
                  <th>Cover cap / remaining</th>
                  <th>Per-claim limit</th>
                  <th>Premium paid</th>
                  <th>Expires</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((agent) => {
                  const policy = policyByAgent.get(agent.id);
                  return (
                    <tr key={agent.id}>
                      <td>
                        <strong style={{ color: "var(--paper)" }}>{agent.name}</strong>
                        <br /><span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>{agent.id}</span>
                      </td>
                      <td>
                        <span className={`dashboard-status status-${policy ? "settled" : "routing"}`} style={{ fontSize: "0.72rem" }}>
                          {policy ? "Active" : "Not covered"}
                        </span>
                      </td>
                      <td>
                        {policy ? (
                          <>
                            <span style={{ color: "var(--paper)" }}>{money(policy.coverCap)}</span>
                            <br /><span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>{money(policy.coverRemaining)} remaining</span>
                          </>
                        ) : <span className="muted">—</span>}
                      </td>
                      <td>{policy ? money(policy.perClaimLimit) : <span className="muted">—</span>}</td>
                      <td>{policy ? money(policy.premium) : <span className="muted">—</span>}</td>
                      <td>
                        {policy
                          ? <span style={{ fontSize: "0.82rem" }}>{new Date(policy.periodEnd).toLocaleDateString()}</span>
                          : <span className="muted">—</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Create / view policy per agent */}
      <section className="dashboard-panel">
        <div className="panel-heading"><div><span className="eyebrow">Annual policy</span><h2>{activePolicy ? "Current protection" : "Create protection"}</h2></div></div>

        <div className="cover-grid" style={{ marginBottom: activePolicy ? "0" : "0" }}>
          <div>
            <label className="cover-form" style={{ marginBottom: "16px" }}>
              <span style={{ color: "var(--muted)", fontSize: "0.75rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em" }}>Insured agent</span>
              <select
                value={selectedAgentId}
                onChange={(e) => handleAgentChange(e.target.value)}
                disabled={agents.length === 0}
                style={{ width: "100%", boxSizing: "border-box", padding: "11px 12px", color: "var(--paper)", background: "rgba(255,255,255,.05)", border: "1px solid var(--border)", borderRadius: "8px" }}
              >
                {agents.length === 0
                  ? <option value="">No agents — create one first</option>
                  : agents.map((a) => (
                      <option key={a.id} value={a.id}>{a.name} ({a.id})</option>
                    ))}
              </select>
            </label>

            {activePolicy ? (
              <>
                <dl className="cover-metrics">
                  <div><dt>Cover cap</dt><dd>{money(activePolicy.coverCap)}</dd></div>
                  <div><dt>Remaining</dt><dd>{money(activePolicy.coverRemaining)}</dd></div>
                  <div><dt>Per-claim limit</dt><dd>{money(activePolicy.perClaimLimit)}</dd></div>
                  <div><dt>Expires</dt><dd>{new Date(activePolicy.periodEnd).toLocaleDateString()}</dd></div>
                </dl>
              </>
            ) : (
              <div className="cover-form">
                {selectedAgent && (
                  <p style={{ margin: "0 0 4px", color: "var(--muted)", fontSize: "0.78rem", lineHeight: 1.4 }}>
                    Recommended limits based on this agent's authority — max single payment{" "}
                    <strong style={{ color: "var(--paper)" }}>{money(selectedAgent.maxSinglePayment, selectedAgent.currency ?? "RLUSD")}</strong>,
                    max daily spend{" "}
                    <strong style={{ color: "var(--paper)" }}>{money(selectedAgent.maxDailySpend, selectedAgent.currency ?? "RLUSD")}</strong>.
                  </p>
                )}
                <label>
                  Cover cap (RLUSD)
                  <input type="number" min="100" value={coverCap} onChange={(e) => setCoverCap(e.target.value)} />
                </label>
                <label>
                  Per-claim limit (RLUSD)
                  <input type="number" min="50" value={perClaimLimit} onChange={(e) => setPerClaimLimit(e.target.value)} />
                </label>
                <button
                  className="dashboard-primary"
                  type="button"
                  onClick={() => void getQuote()}
                  disabled={busy || !selectedAgentId}
                >
                  {busy ? "Pricing…" : "Get annual quote"}
                </button>
              </div>
            )}

            {quote && (
              <div className="cover-quote">
                <span className="eyebrow">{quote.decision}</span>
                <strong>{money(quote.premium)} / year</strong>
                {quote.reason && <p>{quote.reason}</p>}
                {Object.keys(quote.lineRates).length > 0 && (
                  <div style={{ marginTop: "8px" }}>
                    <span style={{ color: "var(--muted)", fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Premium breakdown</span>
                    {Object.entries(quote.lineRates).map(([line, rate]) => (
                      <div key={line} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,.07)", fontSize: "0.85rem" }}>
                        <span style={{ color: "var(--paper)" }}>{PERIL_LABELS[line]?.title ?? line}</span>
                        <span style={{ color: "var(--muted)" }}>{pct(rate)} / yr</span>
                      </div>
                    ))}
                  </div>
                )}
                {quote.decision === "OFFER" && (
                  <button className="dashboard-primary" type="button" onClick={() => void bindCover()} disabled={busy}>
                    Bind cover
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Perils covered */}
          <div>
            <span className="eyebrow" style={{ display: "block", marginBottom: "10px" }}>
              {activePolicy ? "Perils covered" : "Select perils to cover"}
            </span>
            {ALL_LINES.map((key) => {
              const peril = PERIL_LABELS[key];
              const inPolicy = activePolicy
                ? activePolicy.lines.includes(key as import("@treasury/shared").CoverLineKind)
                : selectedLines.has(key);
              return (
                <div
                  key={key}
                  className="cover-peril-row"
                  style={{ opacity: inPolicy ? 1 : 0.45, cursor: activePolicy ? "default" : "pointer" }}
                  onClick={() => { if (!activePolicy) toggleLine(key); }}
                >
                  <input
                    type="checkbox"
                    checked={inPolicy}
                    disabled={!!activePolicy || (inPolicy && selectedLines.size === 1)}
                    readOnly
                    onClick={(e) => { e.stopPropagation(); if (!activePolicy) toggleLine(key); }}
                    style={{ width: "15px", height: "15px", minHeight: "unset", margin: 0, accentColor: "var(--accent-strong)", cursor: activePolicy ? "default" : "pointer" }}
                  />
                  <div>
                    <strong>{peril.title}</strong>
                    <p>{peril.description}</p>
                  </div>
                  {activePolicy && inPolicy && (
                    <span className="cover-peril-limit">{money(activePolicy.perClaimLimit)} / claim</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* Claim payouts */}
      <section className="dashboard-panel">
        <div className="panel-heading"><div><span className="eyebrow">Verified history</span><h2>Claim payouts</h2></div></div>
        {payouts.length === 0 ? <p className="muted">No claims have been paid.</p> : (
          <div className="cover-payouts">
            {payouts.map((payout) => {
              const perilLabel = PERIL_LABELS[payout.line]?.title ?? payout.line;
              return (
                <article key={payout.id}>
                  <div>
                    <strong>{perilLabel}</strong>
                    <small>{payout.classification} · {new Date(payout.createdAt).toLocaleString()}</small>
                  </div>
                  <span>{money(payout.amountPaid)}</span>
                  {payout.explorerUrl
                    ? <a href={payout.explorerUrl} target="_blank" rel="noreferrer">Explorer ↗</a>
                    : <span className="muted">No ledger proof</span>}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
