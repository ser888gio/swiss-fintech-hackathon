import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import type {
  AgentRiskState,
  CoverLine,
  DelegationGrant,
  DelegationGrantCreate,
  GuardrailResult,
  InsurancePremiumRecord,
  LpPosition,
  PoolStatus,
  PremiumQuote,
  Receivable,
  ReceivableCreate,
  X402Settlement,
} from "@treasury/shared";
import { api } from "../lib/api.js";

// ── Types ─────────────────────────────────────────────────────────────────────

interface LogLine {
  ts: string;
  kind: "info" | "success" | "error" | "guardrail";
  text: string;
  txHash?: string;
  explorerUrl?: string;
  guardrailTrail?: GuardrailResult[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function hashShort(hash: string): string {
  return `${hash.slice(0, 10)}…`;
}

function statusColor(status: string): string {
  switch (status) {
    case "closed": return "status-settled";
    case "awaiting_maturity": return "status-routing";
    case "supplier_paid": return "status-routing";
    case "registered": return "status-routing";
    case "needs_recovery": return "status-blocked";
    default: return "status-routing";
  }
}

// ── Payment Log panel ─────────────────────────────────────────────────────────

function PaymentLog({ lines }: { lines: LogLine[] }) {
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  return (
    <div className="ars-log-panel">
      <div className="ars-log-header">
        <span className="eyebrow">Live payment log</span>
        <span className="muted" style={{ fontSize: "0.7rem" }}>{lines.length} events</span>
      </div>
      <div className="ars-log-body">
        {lines.length === 0 && (
          <p className="muted ars-log-empty">No transactions yet. Trigger an action on the left.</p>
        )}
        {lines.map((l, i) => (
          <div key={i} className={`ars-log-line ars-log-${l.kind}`}>
            <span className="ars-log-ts">{l.ts}</span>
            <span className="ars-log-text">{l.text}</span>
            {l.txHash && l.explorerUrl && (
              <a
                href={l.explorerUrl}
                target="_blank"
                rel="noreferrer"
                className="ars-log-link"
              >
                {hashShort(l.txHash)} ↗
              </a>
            )}
            {l.txHash && !l.explorerUrl && (
              <code className="ars-log-link" title="No on-ledger explorer proof was returned">
                {hashShort(l.txHash)} · simulated
              </code>
            )}
            {l.guardrailTrail && l.guardrailTrail.length > 0 && (
              <div className="ars-guardrail-trail">
                {l.guardrailTrail.map((g) => (
                  <span
                    key={g.name}
                    className={`ars-guardrail-badge ${g.passed ? "ars-g-pass" : "ars-g-fail"}`}
                    title={g.reason ?? g.ruleFired ?? ""}
                  >
                    {g.passed ? "✓" : "✗"} {g.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={bottom} />
      </div>
    </div>
  );
}

// ── Trade Finance panel ────────────────────────────────────────────────────────

const DEFAULT_RECEIVABLE: ReceivableCreate = {
  invoiceId: "INV-TF-001",
  buyer: "rJw33SjizSjbJiKB9PVmrgdWN3MAAUwr7v",
  supplier: "rJw33SjizSjbJiKB9PVmrgdWN3MAAUwr7v",
  amount: "5000.000000",
  discountRate: "0.020000",
  dueDate: new Date(Date.now() + 90 * 86400 * 1000).toISOString(),
};

function TradeFinancePanel({ onLog }: { onLog: (l: LogLine) => void }) {
  const [receivables, setReceivables] = useState<Receivable[]>([]);
  const [form, setForm] = useState<ReceivableCreate>(DEFAULT_RECEIVABLE);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  const log = useCallback((l: LogLine) => onLog(l), [onLog]);
  const now = () => new Date().toISOString().slice(11, 19);

  const refresh = useCallback(async () => {
    try {
      setReceivables(await api.listReceivables());
    } catch {
      /* silently ignore on disabled feature */
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const setBusyKey = (key: string, val: boolean) =>
    setBusy((p) => ({ ...p, [key]: val }));

  const register = async () => {
    setBusyKey("register", true);
    setError(null);
    log({ ts: now(), kind: "info", text: `Registering receivable ${form.invoiceId}…` });
    try {
      const rec = await api.registerReceivable(form);
      log({ ts: now(), kind: "success", text: `Receivable ${rec.invoiceId} registered — status: ${rec.status}` });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      log({ ts: now(), kind: "error", text: `Register failed: ${msg}` });
    } finally {
      setBusyKey("register", false);
    }
  };

  const payEarly = async (invoiceId: string) => {
    setBusyKey(invoiceId, true);
    log({ ts: now(), kind: "info", text: `Paying supplier early for ${invoiceId}…` });
    try {
      const rec = await api.paySupplierEarly(invoiceId);
      const txHash = rec.paymentTxHash ?? rec.drawTxHash ?? "";
      const explorerUrl = rec.paymentExplorerUrl ?? rec.drawExplorerUrl ?? undefined;
      log({
        ts: now(),
        kind: "success",
        text: `Supplier paid — ${rec.amount} @ ${(Number(rec.discountRate) * 100).toFixed(1)}% discount → ${(Number(rec.amount) * (1 - Number(rec.discountRate))).toLocaleString()} delivered`,
        txHash: txHash || undefined,
        explorerUrl,
        guardrailTrail: rec.guardrailTrail,
      });
      if (rec.loanId) {
        log({ ts: now(), kind: "info", text: `XLS-66 LoanCreate → loan ${rec.loanId.slice(0, 12)}…` });
      }
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("Requires hardware approval")) {
        log({
          ts: now(),
          kind: "guardrail",
          text: "Early payment not executed — G6 threshold requires Firefly hardware approval.",
        });
      } else {
        log({ ts: now(), kind: "error", text: `Early payment failed: ${msg}` });
      }
    } finally {
      setBusyKey(invoiceId, false);
    }
  };

  const collect = async (invoiceId: string) => {
    setBusyKey(`collect_${invoiceId}`, true);
    log({ ts: now(), kind: "info", text: `Collecting repayment for ${invoiceId}…` });
    try {
      const rec = await api.collectRepayment(invoiceId);
      const txHash = rec.settleTxHash ?? rec.repaymentTxHash ?? "";
      log({
        ts: now(),
        kind: "success",
        text: `Repayment collected — receivable ${rec.status}. Vault replenished.`,
        txHash: txHash || undefined,
        explorerUrl: undefined,
      });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      log({ ts: now(), kind: "error", text: `Collect failed: ${msg}` });
    } finally {
      setBusyKey(`collect_${invoiceId}`, false);
    }
  };

  const field = (key: keyof ReceivableCreate) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((p) => ({ ...p, [key]: e.target.value }));

  return (
    <section className="queue ars-panel" aria-label="Trade Finance">
      <div className="section-heading">
        <span className="eyebrow">XLS-65 + XLS-66 · Devnet</span>
        <strong>Trade Finance — early supplier payment</strong>
      </div>
      <p className="muted" style={{ marginBottom: "1rem" }}>
        Register a 90-day invoice. The agent pays the supplier today from the vault pool at a
        discount. At maturity the buyer repays and the vault is replenished. XLS-66 LoanCreate
        fires automatically when <code>lending_enabled=True</code>.
      </p>

      {error && <p className="error">{error}</p>}

      <div className="ars-form-grid">
        <label><span>Invoice ID</span>
          <input name="invoice-id" autoComplete="off" value={form.invoiceId} onChange={field("invoiceId")} spellCheck={false} />
        </label>
        <label><span>Face amount (RLUSD)</span>
          <input name="receivable-amount" autoComplete="off" inputMode="decimal" value={form.amount} onChange={field("amount")} />
        </label>
        <label><span>Discount rate</span>
          <input name="discount-rate" autoComplete="off" inputMode="decimal" value={form.discountRate} onChange={field("discountRate")} placeholder="e.g. 0.020000…" />
        </label>
        <label><span>Buyer address</span>
          <input name="buyer-address" autoComplete="off" value={form.buyer} onChange={field("buyer")} spellCheck={false} />
        </label>
        <label><span>Supplier address</span>
          <input name="supplier-address" autoComplete="off" value={form.supplier} onChange={field("supplier")} spellCheck={false} />
        </label>
        <label><span>Due date (ISO)</span>
          <input name="due-date" autoComplete="off" value={form.dueDate.slice(0, 10)} onChange={(e) => setForm((p) => ({ ...p, dueDate: `${e.target.value}T00:00:00Z` }))} type="date" />
        </label>
      </div>

      <button className="primary-action" type="button" disabled={busy.register} onClick={() => void register()}>
        {busy.register ? "Registering…" : "Register receivable"}
      </button>

      {receivables.length > 0 && (
        <ul className="credential-log" style={{ marginTop: "1rem" }}>
          {receivables.map((rec) => (
            <li key={rec.id} className="decision-row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <strong>{rec.invoiceId}</strong>{" "}
                <span className={`dashboard-status ${statusColor(rec.status)}`}>{rec.status}</span>
                <p className="muted" style={{ margin: "0.2rem 0" }}>
                  {Number(rec.amount).toLocaleString()} RLUSD · {(Number(rec.discountRate) * 100).toFixed(1)}% discount
                </p>
                {rec.paymentTxHash && rec.paymentExplorerUrl && (
                  <p className="muted" style={{ fontSize: "0.72rem" }}>
                    Pay tx:{" "}
                    <a href={rec.paymentExplorerUrl} target="_blank" rel="noreferrer">
                      {hashShort(rec.paymentTxHash)} ↗
                    </a>
                  </p>
                )}
                {rec.paymentTxHash && !rec.paymentExplorerUrl && (
                  <p className="muted" style={{ fontSize: "0.72rem" }}>
                    Pay tx: <code>{hashShort(rec.paymentTxHash)} · simulated</code>
                  </p>
                )}
                {rec.settleTxHash && (
                  <p className="muted" style={{ fontSize: "0.72rem" }}>
                    Settle tx: <code>{hashShort(rec.settleTxHash)} · no explorer proof</code>
                  </p>
                )}
                {rec.loanId && (
                  <p className="muted" style={{ fontSize: "0.72rem" }}>XLS-66 loan: {rec.loanId.slice(0, 16)}…</p>
                )}
              </div>
              <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                {(rec.status === "registered" || rec.status === "funds_reserved") && (
                  <button className="primary-action" type="button" disabled={busy[rec.invoiceId]}
                    onClick={() => void payEarly(rec.invoiceId)}>
                    {busy[rec.invoiceId] ? "Paying…" : "Pay early"}
                  </button>
                )}
                {rec.status === "awaiting_maturity" && (
                  <button className="primary-action" type="button" disabled={busy[`collect_${rec.invoiceId}`]}
                    onClick={() => void collect(rec.invoiceId)}>
                    {busy[`collect_${rec.invoiceId}`] ? "Collecting…" : "Collect repayment"}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── x402 Service Payment panel ─────────────────────────────────────────────────

function X402Panel({ onLog }: { onLog: (l: LogLine) => void }) {
  const [serviceUrl, setServiceUrl] = useState(
    import.meta.env.VITE_X402_SERVICE_URL ?? "/treasury/x402/demo-resource",
  );
  const [serviceType, setServiceType] = useState("data_lookup");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<X402Settlement | null>(null);
  const now = () => new Date().toISOString().slice(11, 19);

  const pay = async () => {
    if (!serviceUrl.trim()) {
      onLog({ ts: now(), kind: "error", text: "Enter an x402-protected service URL first." });
      return;
    }
    setBusy(true);
    onLog({ ts: now(), kind: "info", text: `x402 → ${serviceUrl}` });
    try {
      const result = await api.triggerServicePayment(serviceUrl, serviceType);
      setLast(result);
      onLog({
        ts: now(),
        kind: "success",
        text: `x402 ${result.explorerUrl ? "paid" : "simulated"} — ${result.amount} ${result.currency} · invoice ${result.invoiceId.slice(0, 12)}…`,
        txHash: result.txHash,
        explorerUrl: result.explorerUrl ?? undefined,
        guardrailTrail: result.guardrailTrail,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      onLog({ ts: now(), kind: "error", text: `x402 failed: ${msg}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="queue ars-panel" aria-label="x402 service payment">
      <div className="section-heading">
        <span className="eyebrow">x402 · configured XRPL asset</span>
        <strong>Pay-at-need — agent pays for a service per request</strong>
      </div>
      <p className="muted" style={{ marginBottom: "1rem" }}>
        Agent hits a paid endpoint → 402 → G1+G4 guardrails screen the spend →
        RLUSD Payment via the t54 facilitator → retries with proof.
      </p>

      <label><span>Service URL</span>
        <input name="service-url" type="text" autoComplete="off" value={serviceUrl} onChange={(e) => setServiceUrl(e.target.value)} spellCheck={false}
          style={{ width: "100%" }} disabled={busy} />
      </label>
      <label style={{ marginTop: "0.5rem" }}><span>Service type</span>
        <input name="service-type" autoComplete="off" value={serviceType} onChange={(e) => setServiceType(e.target.value)} disabled={busy} />
      </label>

      <button className="primary-action" type="button" disabled={busy} style={{ marginTop: "0.75rem" }}
        onClick={() => void pay()}>
        {busy ? "Paying…" : "Trigger x402 payment"}
      </button>

      {last && (
        <div className="ars-tx-card" style={{ marginTop: "1rem" }}>
          <p className="muted" style={{ fontSize: "0.75rem", margin: 0 }}>Last settlement</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", marginTop: "0.4rem" }}>
            <div><p className="muted">Amount</p><strong>{last.amount} {last.currency}</strong></div>
            <div><p className="muted">Invoice</p><code style={{ fontSize: "0.72rem" }}>{last.invoiceId.slice(0, 16)}…</code></div>
            <div>
              <p className="muted">Tx hash</p>
              {last.explorerUrl ? (
                <a href={last.explorerUrl} target="_blank" rel="noreferrer" style={{ fontSize: "0.75rem" }}>
                  {hashShort(last.txHash)} ↗
                </a>
              ) : (
                <code style={{ fontSize: "0.72rem" }}>{hashShort(last.txHash)} · simulated</code>
              )}
            </div>
            <div><p className="muted">Proof header</p><code style={{ fontSize: "0.68rem" }}>{last.proofHeader.slice(0, 20)}…</code></div>
          </div>
        </div>
      )}
    </section>
  );
}

// ── Delegation panel ───────────────────────────────────────────────────────────

const DEFAULT_GRANT: DelegationGrantCreate = {
  parentAddress: "",
  childAddress: "rJw33SjizSjbJiKB9PVmrgdWN3MAAUwr7v",
  maxTotal: "500.000000",
  maxPerTx: "50.000000",
  maxPerDay: "200.000000",
  currency: "USD",
};

function DelegationPanel({ onLog }: { onLog: (l: LogLine) => void }) {
  const [grants, setGrants] = useState<DelegationGrant[]>([]);
  const [form, setForm] = useState<DelegationGrantCreate>(DEFAULT_GRANT);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const now = () => new Date().toISOString().slice(11, 19);

  const refresh = useCallback(async () => {
    try { setGrants(await api.listDelegations()); } catch { /* feature may be disabled */ }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    void api.getWallet().then((wallet) => {
      setForm((current) => ({ ...current, parentAddress: wallet.address }));
    }).catch(() => { /* wallet setup error is surfaced when the form is submitted */ });
  }, []);

  const setBusyKey = (key: string, val: boolean) =>
    setBusy((p) => ({ ...p, [key]: val }));

  const create = async () => {
    setError(null);
    if (!form.parentAddress.trim() || !form.childAddress.trim()) {
      setError("Parent and child addresses are required.");
      return;
    }
    setBusyKey("create", true);
    onLog({ ts: now(), kind: "info", text: `Granting ${form.maxTotal} ${form.currency} to ${form.childAddress.slice(0, 12)}…` });
    try {
      const grant = await api.createDelegation(form);
      onLog({
        ts: now(), kind: "success",
        text: `Delegation created — child: ${grant.childAddress.slice(0, 12)}… max: ${grant.maxTotal}`,
        txHash: grant.fundTxHash ?? undefined,
        explorerUrl: grant.fundExplorerUrl ?? undefined,
      });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      onLog({ ts: now(), kind: "error", text: `Delegation failed: ${msg}` });
    } finally {
      setBusyKey("create", false);
    }
  };

  const revoke = async (grantId: string) => {
    setBusyKey(grantId, true);
    try {
      await api.revokeDelegation(grantId);
      onLog({ ts: now(), kind: "info", text: `Grant ${grantId.slice(0, 8)}… revoked` });
      await refresh();
    } catch (e) {
      onLog({ ts: now(), kind: "error", text: `Revoke failed: ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setBusyKey(grantId, false);
    }
  };

  const field = (key: keyof DelegationGrantCreate) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((p) => ({ ...p, [key]: e.target.value }));

  return (
    <section className="queue ars-panel" aria-label="Agent delegation">
      <div className="section-heading">
        <span className="eyebrow">G5 · Agent-to-Agent</span>
        <strong>Delegation — scoped sub-agent budget</strong>
      </div>
      <p className="muted" style={{ marginBottom: "1rem" }}>
        A parent agent grants a sub-agent wallet a delegated budget. The sub-agent can only
        spend within the delegated limits (per-tx, per-day, lifetime total).
      </p>

      {error && <p className="error">{error}</p>}

      <div className="ars-form-grid">
        <label><span>Parent address</span>
          <input name="parent-address" autoComplete="off" value={form.parentAddress} onChange={field("parentAddress")} spellCheck={false} />
        </label>
        <label><span>Child (sub-agent) address</span>
          <input name="child-address" autoComplete="off" value={form.childAddress} onChange={field("childAddress")} spellCheck={false} />
        </label>
        <label><span>Max total</span>
          <input name="max-total" autoComplete="off" inputMode="decimal" value={form.maxTotal} onChange={field("maxTotal")} />
        </label>
        <label><span>Max per tx</span>
          <input name="max-per-transaction" autoComplete="off" inputMode="decimal" value={form.maxPerTx} onChange={field("maxPerTx")} />
        </label>
        <label><span>Max per day</span>
          <input name="max-per-day" autoComplete="off" inputMode="decimal" value={form.maxPerDay} onChange={field("maxPerDay")} />
        </label>
      </div>

      <button className="primary-action" type="button" disabled={busy.create} onClick={() => void create()}>
        {busy.create ? "Granting…" : "Grant delegation"}
      </button>

      {grants.length > 0 && (
        <ul className="credential-log" style={{ marginTop: "1rem" }}>
          {grants.map((g) => (
            <li key={g.id} className="decision-row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <strong>{g.childAddress.slice(0, 16)}…</strong>{" "}
                <span className={`dashboard-status ${g.revoked ? "status-blocked" : "status-settled"}`}>
                  {g.revoked ? "revoked" : "active"}
                </span>
                <p className="muted" style={{ margin: "0.2rem 0", fontSize: "0.75rem" }}>
                  max: {g.maxTotal} · per-tx: {g.maxPerTx} · per-day: {g.maxPerDay} {g.currency}
                </p>
                {g.fundTxHash && g.fundExplorerUrl && (
                  <p className="muted" style={{ fontSize: "0.72rem" }}>
                    Fund tx:{" "}
                    <a href={g.fundExplorerUrl} target="_blank" rel="noreferrer">
                      {hashShort(g.fundTxHash)} ↗
                    </a>
                  </p>
                )}
                {g.fundTxHash && !g.fundExplorerUrl && (
                  <p className="muted" style={{ fontSize: "0.72rem" }}>
                    Fund tx: <code>{hashShort(g.fundTxHash)} · simulated</code>
                  </p>
                )}
              </div>
              {!g.revoked && (
                <button className="text-action" type="button" disabled={busy[g.id]}
                  onClick={() => void revoke(g.id)}>
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── Insurance panel (Pillar 3) ─────────────────────────────────────────────────

const ALL_LINES: CoverLine[] = ["merchant_default", "lender_credit", "principal_score", "mandate_breach"];
const SCORE_BANDS = ["ELITE", "HIGH", "STANDARD", "HIGH_RISK"];

function decisionClass(decision: string): string {
  if (decision === "OFFER") return "status-settled";
  if (decision === "REVIEW") return "status-routing";
  return "status-blocked";
}

function InsurancePanel({ onLog }: { onLog: (l: LogLine) => void }) {
  const [agent, setAgent] = useState("rAGENT0000000000000000000000000000");
  const [amount, setAmount] = useState("20000");
  const [scoreBand, setScoreBand] = useState("STANDARD");
  const [category, setCategory] = useState("merchant_payment");
  // Payout beneficiary — in live (non-mock) mode this must be an activated account.
  const [merchant, setMerchant] = useState("rBBHb3oX4JxoGRU28X94iDRiZUPU8Xu7ur");
  const [lines, setLines] = useState<CoverLine[]>(["merchant_default"]);
  const [quote, setQuote] = useState<PremiumQuote | null>(null);
  const [premiums, setPremiums] = useState<InsurancePremiumRecord[]>([]);
  const [pool, setPool] = useState<PoolStatus | null>(null);
  const [riskState, setRiskState] = useState<AgentRiskState | null>(null);
  // First-loss capital providers (LPs).
  const [lpPositions, setLpPositions] = useState<LpPosition[]>([]);
  const [lpAddress, setLpAddress] = useState("rLP0000000000000000000000000000001");
  const [lpAmount, setLpAmount] = useState("50000");
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const now = () => new Date().toISOString().slice(11, 19);
  const setBusyKey = (k: string, v: boolean) => setBusy((p) => ({ ...p, [k]: v }));

  const refresh = useCallback(async () => {
    try {
      const [pr, pl, lp] = await Promise.all([
        api.listInsurancePremiums(),
        api.getInsurancePool(),
        api.listInsuranceCapital(),
      ]);
      setPremiums(pr);
      setPool(pl);
      setLpPositions(lp);
    } catch {
      /* feature may be disabled */
    }
  }, []);

  const refreshRisk = useCallback(async (address: string) => {
    try {
      setRiskState(await api.getAgentRisk(address));
    } catch {
      setRiskState(null);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const toggleLine = (line: CoverLine) =>
    setLines((p) => (p.includes(line) ? p.filter((l) => l !== line) : [...p, line]));

  const getQuote = async () => {
    setBusyKey("quote", true);
    setError(null);
    onLog({ ts: now(), kind: "info", text: `Quoting cover for ${agent.slice(0, 10)}… on ${amount} (${scoreBand})` });
    try {
      const q = await api.quoteInsurance({
        agentAddress: agent,
        scoreBand,
        txnContext: {
          category,
          tenorBand: "lt_30d",
          cptyBand: "known",
          amount,
          activeLines: lines,
        },
      });
      setQuote(q);
      onLog({
        ts: now(),
        kind: q.decision === "OFFER" ? "success" : "error",
        text: `Quote ${q.decision} — premium ${q.premium} ${pool?.currency ?? "USD"} · PD ${(q.pd * 100).toFixed(2)}% · Z ${(q.credibility * 100).toFixed(0)}%`,
        txHash: q.receiptHash,
      });
      await refreshRisk(agent);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      onLog({ ts: now(), kind: "error", text: `Quote failed: ${msg}` });
    } finally {
      setBusyKey("quote", false);
    }
  };

  const bind = async () => {
    if (!quote || quote.decision !== "OFFER") return;
    setBusyKey("bind", true);
    const jobId = `job-${Date.now()}`;
    try {
      const rec = await api.bindInsurance({
        agentAddress: agent,
        jobId,
        scoreBand,
        currency: pool?.currency ?? "USD",
        quote,
      });
      onLog({
        ts: now(),
        kind: "success",
        text: `Premium bound — ${rec.premiumAmount} ${rec.currency} → Insurance Vault (job ${jobId.slice(-6)})`,
        txHash: rec.txHash ?? undefined,
        explorerUrl: rec.explorerUrl ?? undefined,
        guardrailTrail: rec.guardrailTrail,
      });
      await refresh();
    } catch (e) {
      onLog({ ts: now(), kind: "error", text: `Bind failed: ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setBusyKey("bind", false);
    }
  };

  const simulateClaim = async () => {
    setBusyKey("claim", true);
    const jobId = `claim-${Date.now()}`;
    onLog({ ts: now(), kind: "info", text: `Simulating a covered default for ${agent.slice(0, 10)}…` });
    try {
      const payout = await api.claimInsurance({
        jobId,
        agentAddress: agent,
        merchant,
        scoreBand,
        currency: pool?.currency ?? "USD",
        claimAmount: amount,
        collateralAvailable: "0",
        receiptHash: quote?.receiptHash,
      });
      onLog({
        ts: now(),
        kind: "success",
        text: `Payout — pool drew ${payout.poolDrawn} ${payout.currency}, merchant paid ${payout.totalPaid}. Principal score protected.`,
        txHash: payout.poolDrawTxHash ?? undefined,
        guardrailTrail: payout.guardrailTrail,
      });
      await Promise.all([refresh(), refreshRisk(agent)]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      onLog({ ts: now(), kind: "error", text: `Claim refused: ${msg}` });
    } finally {
      setBusyKey("claim", false);
    }
  };

  const depositCapital = async () => {
    setBusyKey("lpDeposit", true);
    setError(null);
    onLog({ ts: now(), kind: "info", text: `LP ${lpAddress.slice(0, 10)}… depositing ${lpAmount} first-loss capital` });
    try {
      const pos = await api.depositInsuranceCapital({ lpAddress, amount: lpAmount });
      onLog({
        ts: now(),
        kind: "success",
        text: `Capital in — ${pos.capital} ${pos.currency} (${(pos.sharePct * 100).toFixed(1)}% of LP pool)`,
        txHash: pos.txHash ?? undefined,
        explorerUrl: pos.explorerUrl ?? undefined,
        guardrailTrail: pos.guardrailTrail,
      });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      onLog({ ts: now(), kind: "error", text: `Capital deposit refused: ${msg}` });
    } finally {
      setBusyKey("lpDeposit", false);
    }
  };

  const withdrawCapital = async () => {
    setBusyKey("lpWithdraw", true);
    setError(null);
    onLog({ ts: now(), kind: "info", text: `LP ${lpAddress.slice(0, 10)}… recalling ${lpAmount} capital` });
    try {
      const pos = await api.withdrawInsuranceCapital({ lpAddress, amount: lpAmount });
      onLog({
        ts: now(),
        kind: "success",
        text: `Capital out — remaining ${pos.capital} ${pos.currency} (${(pos.sharePct * 100).toFixed(1)}% of LP pool)`,
        txHash: pos.txHash ?? undefined,
        explorerUrl: pos.explorerUrl ?? undefined,
      });
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      onLog({ ts: now(), kind: "error", text: `Capital withdraw refused: ${msg}` });
    } finally {
      setBusyKey("lpWithdraw", false);
    }
  };

  return (
    <section className="queue ars-panel" aria-label="Insurance pricing & risk engine">
      <div className="section-heading">
        <span className="eyebrow">Pillar 3 · Agent-default insurance</span>
        <strong>Pricing & Risk Engine — dynamic premium for agent-default cover</strong>
      </div>
      <p className="muted" style={{ marginBottom: "1rem" }}>
        A statistical core (Beta-posterior PD × relative-risk table) prices the risk; a deterministic,
        signed envelope bounds, loads and receipts the premium. The price moves with the agent because
        the posterior does — a default reprices every future quote.
      </p>

      {error && <p className="error">{error}</p>}

      <div className="ars-form-grid">
        <label><span>Agent address</span>
          <input name="insured-agent-address" autoComplete="off" value={agent} onChange={(e) => setAgent(e.target.value)} spellCheck={false} />
        </label>
        <label><span>Transaction amount</span>
          <input name="insured-transaction-amount" autoComplete="off" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label><span>Score band</span>
          <select name="insurance-score-band" autoComplete="off" value={scoreBand} onChange={(e) => setScoreBand(e.target.value)}>
            {SCORE_BANDS.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </label>
        <label><span>Category</span>
          <select name="insurance-category" autoComplete="off" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="merchant_payment">merchant_payment</option>
            <option value="supplier_payment">supplier_payment</option>
            <option value="loan_repayment">loan_repayment</option>
          </select>
        </label>
        <label><span>Merchant (payout beneficiary)</span>
          <input name="merchant-address" autoComplete="off" value={merchant} onChange={(e) => setMerchant(e.target.value)} spellCheck={false} />
        </label>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", margin: "0.5rem 0 1rem" }}>
        {ALL_LINES.map((line) => (
          <label key={line} style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.8rem" }}>
            <input name="cover-lines" value={line} type="checkbox" checked={lines.includes(line)} onChange={() => toggleLine(line)} />
            {line}
          </label>
        ))}
      </div>

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <button className="primary-action" type="button" disabled={busy.quote || lines.length === 0} onClick={() => void getQuote()}>
          {busy.quote ? "Pricing…" : "Get quote"}
        </button>
        {quote?.decision === "OFFER" && (
          <button className="primary-action" type="button" disabled={busy.bind} onClick={() => void bind()}>
            {busy.bind ? "Binding…" : "Bind premium"}
          </button>
        )}
        <button className="text-action" type="button" disabled={busy.claim} onClick={() => void simulateClaim()}>
          {busy.claim ? "Settling…" : "Simulate default → claim"}
        </button>
      </div>

      {quote && (
        <div className="ars-tx-card" style={{ marginTop: "1rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span className={`dashboard-status ${decisionClass(quote.decision)}`}>{quote.decision}</span>
            <strong>{quote.premium} {pool?.currency ?? "USD"}</strong>
            {quote.reason && <span className="muted" style={{ fontSize: "0.75rem" }}>· {quote.reason}</span>}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", marginTop: "0.5rem" }}>
            <div><p className="muted">PD</p><strong>{(quote.pd * 100).toFixed(2)}%</strong></div>
            <div><p className="muted">Credibility Z</p><strong>{(quote.credibility * 100).toFixed(0)}%</strong></div>
            <div><p className="muted">Band</p><strong>{scoreBand}</strong></div>
          </div>
          <div style={{ marginTop: "0.5rem" }}>
            {Object.entries(quote.lines).map(([line, prem]) => (
              <p key={line} className="muted" style={{ margin: "0.15rem 0", fontSize: "0.74rem" }}>
                {line}: <strong>{prem}</strong>
              </p>
            ))}
          </div>
          <p className="muted" style={{ fontSize: "0.68rem", marginTop: "0.4rem" }}>
            receipt {quote.receiptHash.slice(0, 16)}…
          </p>
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: "1.25rem", marginTop: "1rem" }}>
        {pool && (
          <div>
            <p className="muted" style={{ fontSize: "0.72rem", margin: 0 }}>Pool first-loss capital</p>
            <strong>{Number(pool.firstLoss).toLocaleString()} {pool.currency}</strong>
            <p className="muted" style={{ fontSize: "0.7rem", margin: "0.2rem 0 0" }}>
              +{Number(pool.premiumsCollected).toLocaleString()} premiums · −{Number(pool.payoutsMade).toLocaleString()} payouts
            </p>
            <p className="muted" style={{ fontSize: "0.7rem", margin: "0.1rem 0 0" }}>
              XLS-65 vault balance: {Number(pool.vaultBalance).toLocaleString()} {pool.currency}
            </p>
            <p className="muted" style={{ fontSize: "0.7rem", margin: "0.1rem 0 0" }}>
              LP first-loss capital: {Number(pool.lpCapital).toLocaleString()} {pool.currency}
            </p>
          </div>
        )}
        {riskState && (
          <div>
            <p className="muted" style={{ fontSize: "0.72rem", margin: 0 }}>Agent posterior ({riskState.scoreBand ?? "—"})</p>
            <strong>PD {(riskState.pd * 100).toFixed(2)}%</strong>
            <p className="muted" style={{ fontSize: "0.7rem", margin: "0.2rem 0 0" }}>
              Z {(riskState.credibility * 100).toFixed(0)}% · α {riskState.alpha.toFixed(2)} / β {riskState.beta.toFixed(2)}
            </p>
          </div>
        )}
      </div>

      {premiums.length > 0 && (
        <ul className="credential-log" style={{ marginTop: "1rem" }}>
          {premiums.slice(0, 6).map((p) => (
            <li key={p.id} className="decision-row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <strong>{p.premiumAmount} {p.currency}</strong>{" "}
                <span className="muted" style={{ fontSize: "0.72rem" }}>· {p.scoreBand ?? "—"} · job {p.jobId.slice(-8)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* First-loss capital providers (LPs) — fund the pool that backs payouts. */}
      <div className="section-heading" style={{ marginTop: "1.5rem" }}>
        <span className="eyebrow">Capital providers · first-loss pool</span>
        <strong>Back the pool — deposit/recall first-loss capital (G1 KYA → G2 sanctions gated)</strong>
      </div>
      <div className="ars-form-grid">
        <label><span>LP address</span>
          <input name="lp-address" autoComplete="off" value={lpAddress} onChange={(e) => setLpAddress(e.target.value)} spellCheck={false} />
        </label>
        <label><span>Amount</span>
          <input name="lp-amount" autoComplete="off" inputMode="decimal" value={lpAmount} onChange={(e) => setLpAmount(e.target.value)} />
        </label>
      </div>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
        <button className="primary-action" type="button" disabled={busy.lpDeposit} onClick={() => void depositCapital()}>
          {busy.lpDeposit ? "Depositing…" : "Deposit capital"}
        </button>
        <button className="text-action" type="button" disabled={busy.lpWithdraw} onClick={() => void withdrawCapital()}>
          {busy.lpWithdraw ? "Recalling…" : "Withdraw capital"}
        </button>
      </div>

      {lpPositions.length > 0 && (
        <ul className="credential-log" style={{ marginTop: "1rem" }}>
          {lpPositions.map((lp) => (
            <li key={lp.lpAddress} className="decision-row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <strong>{Number(lp.capital).toLocaleString()} {lp.currency}</strong>{" "}
                <span className="muted" style={{ fontSize: "0.72rem" }}>
                  · {(lp.sharePct * 100).toFixed(1)}% of LP pool · {lp.lpAddress.slice(0, 12)}…
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function ARSPage() {
  const [lines, setLines] = useState<LogLine[]>([]);

  const addLog = useCallback((l: LogLine) => {
    setLines((prev) => [...prev, l]);
  }, []);

  return (
    <div className="ars-root">
      <div className="ars-left">
        <div style={{ padding: "0.55rem 0.75rem", marginBottom: "1rem", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: "0.82rem", lineHeight: 1.5 }}>
          <strong style={{ color: "var(--paper)" }}>Agentic Payment Infrastructure (ARS)</strong> — four advanced payment primitives in one view: trade-finance early-supplier payment (XLS-65/66), Bayesian insurance pricing, x402 pay-per-request service calls, and agent-to-agent budget delegation. All paths share the same six-guardrail chain (KYA → sanctions → scope → delegation → threshold → <a href="https://firefly.app/" target="_blank" rel="noreferrer" style={{ color: "var(--orange)", textDecoration: "none" }}>Firefly</a>); deterministic code enforces every rule. Every on-chain event appears in the live log on the right.
        </div>
        <div className="send-topbar" style={{ marginBottom: "1.5rem" }}>
          <div>
            <span className="eyebrow">ARS · Agentic Risk Standard</span>
            <h1>Agentic Payment Infrastructure</h1>
          </div>
        </div>
        <p className="tagline" style={{ marginBottom: "1.5rem" }}>
          All three paths share the same guardrail spine (G1 KYA → G2 sanctions → G4 scope → G5
          delegation → G6 threshold → G7 Firefly). Every transaction links to the{" "}
          <a href="https://testnet.xrpl.org" target="_blank" rel="noreferrer">Testnet explorer</a>.
        </p>

        <TradeFinancePanel onLog={addLog} />
        <InsurancePanel onLog={addLog} />
        <X402Panel onLog={addLog} />
        <DelegationPanel onLog={addLog} />
      </div>

      <div className="ars-right">
        <PaymentLog lines={lines} />
      </div>
    </div>
  );
}
