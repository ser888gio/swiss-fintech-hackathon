import { useCallback, useEffect, useState, type ChangeEvent } from "react";
import type { MPTStatus, TreasuryAgentRun, TreasuryGoal, TreasuryGoalCreate, VaultStatus } from "@treasury/shared";

import { api } from "../lib/api.js";

const CURRENCIES = ["USD", "EUR", "CHF", "GBP"];
type BusyKey = "goal" | "run" | "vault" | "mpt";

const DEFAULT_GOAL: TreasuryGoalCreate = {
  name: "Monthly supplier payment",
  beneficiaryName: "Acme Supplies AG",
  beneficiaryAddress: "rwjNyXSKQ5Rt6StJHHPzdHY5KA8UqYjBuC", // funded Testnet counterparty (holds KYC → auto-settles)
  beneficiaryCountry: "US",
  receiverEntityType: "company",
  amount: 1000,
  currency: "USD",
  reference: "INV-AUTO-001",
  purpose: "supplier_payment",
  triggerIntervalHours: 0.001, // ~3.6 s — fires immediately for demo
};

export function TreasuryPage() {
  const [goals, setGoals] = useState<TreasuryGoal[]>([]);
  const [runs, setRuns] = useState<TreasuryAgentRun[]>([]);
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
      const [g, r, v, m] = await Promise.all([
        api.listTreasuryGoals(),
        api.listTreasuryRuns(),
        api.getVaultStatus().catch(() => null),
        api.getMptStatus().catch(() => null),
      ]);
      setGoals(g);
      setRuns(r);
      setVault(v);
      setMpt(m);
    } catch (cause) {
      setError(String(cause));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const runAction = useCallback(async (key: BusyKey, action: () => Promise<unknown>) => {
    setBusy((prev) => ({ ...prev, [key]: true }));
    setError(null);
    try {
      await action();
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy((prev) => ({ ...prev, [key]: false }));
    }
  }, [refresh]);

  const addGoal = useCallback(
    () => runAction("goal", () => api.createTreasuryGoal(form)),
    [form, runAction],
  );

  const deleteGoal = useCallback(
    (id: string) => runAction("goal", () => api.deleteTreasuryGoal(id)),
    [runAction],
  );

  const triggerRun = useCallback(
    () => runAction("run", () => api.triggerTreasuryRun()),
    [runAction],
  );

  const vaultAction = useCallback(
    (action: () => Promise<unknown>) => runAction("vault", action),
    [runAction],
  );

  const mptAction = useCallback(
    (action: () => Promise<unknown>) => runAction("mpt", action),
    [runAction],
  );

  const field = (key: keyof TreasuryGoalCreate) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((prev) => ({ ...prev, [key]: e.target.type === "number" ? Number(e.target.value) : e.target.value }));

  return (
    <section className="send-flow" aria-label="Autonomous treasury agent">
      <div className="send-left">
        <div className="send-topbar">
          <div>
            <span className="eyebrow">Autonomous agent · Phase 2.3</span>
            <h1>Treasury payment goals</h1>
          </div>
          <span className="policy-pill">code decides · LLM narrates</span>
        </div>

        <p className="tagline">
          The agent evaluates goals on each cycle and fires those whose deterministic trigger condition
          is met. The <strong>only actuator</strong> is <code>orchestrator.process_payment</code> — the
          full compliance screen and Firefly hardware veto still apply. Large payments triggered by the
          agent are still locked on-chain.
        </p>

        {error && <p className="error">{error}</p>}

        {/* Add goal form */}
        <section className="recipient-panel" aria-label="New goal">
          <div className="section-heading">
            <span className="eyebrow">New goal</span>
            <strong>Payment target &amp; trigger</strong>
          </div>
          <label><span>Goal name</span>
            <input value={form.name} onChange={field("name")} disabled={busy.goal} />
          </label>
          <label><span>Beneficiary name</span>
            <input value={form.beneficiaryName} onChange={field("beneficiaryName")} disabled={busy.goal} />
          </label>
          <label><span>Beneficiary XRPL address</span>
            <input value={form.beneficiaryAddress} onChange={field("beneficiaryAddress")} disabled={busy.goal} spellCheck={false} />
          </label>
          <div className="recipient-meta">
            <label><span>Country</span>
              <input value={form.beneficiaryCountry} onChange={field("beneficiaryCountry")} disabled={busy.goal} />
            </label>
            <label><span>Currency</span>
              <select value={form.currency} onChange={field("currency")} disabled={busy.goal}>
                {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
              </select>
            </label>
          </div>
          <div className="recipient-meta">
            <label><span>Amount</span>
              <input type="number" value={form.amount} onChange={field("amount")} disabled={busy.goal} min={0} />
            </label>
            <label><span>Trigger interval (hours)</span>
              <input type="number" value={form.triggerIntervalHours} onChange={field("triggerIntervalHours")} disabled={busy.goal} min={0} step={0.001} />
            </label>
          </div>
          <label><span>Reference</span>
            <input value={form.reference} onChange={field("reference")} disabled={busy.goal} />
          </label>
          <label><span>Purpose</span>
            <input value={form.purpose} onChange={field("purpose")} disabled={busy.goal} />
          </label>
        </section>

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <button className="primary-action" type="button" disabled={busy.goal} onClick={() => void addGoal()}>
            {busy.goal ? "Adding..." : "Add goal"}
          </button>
          <button className="primary-action" type="button" disabled={busy.run || goals.length === 0} onClick={() => void triggerRun()}>
            {busy.run ? "Running..." : "Run agent cycle now"}
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
          <p className="muted" style={{ marginBottom: "1rem" }}>
            Every auto-settled payment mints 1 soulbound COMPLY token to the recipient as an
            on-chain compliance proof. The issuance has no transfer flag — badges cannot
            be traded away. <strong>Network: {mpt?.network ?? "…"}</strong>
          </p>

          {mpt && (
            <div className="decision-row" style={{ flexWrap: "wrap", gap: "0.5rem", marginBottom: "1rem" }}>
              <div>
                <p className="muted">Issuance ID</p>
                <code style={{ fontSize: "0.75rem" }}>
                  {mpt.issuanceId ? `${mpt.issuanceId.slice(0, 16)}…` : "none"}
                </code>
              </div>
              <div>
                <p className="muted">Metadata</p>
                <code style={{ fontSize: "0.75rem" }}>{mpt.metadataHex}</code>
              </div>
              <div>
                <p className="muted">Total minted</p>
                <strong>{mpt.totalMinted}</strong>
              </div>
              <div>
                <p className="muted">Authorized holders</p>
                <strong>{mpt.authorizedCount}</strong>
              </div>
            </div>
          )}

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-end", marginBottom: "0.75rem" }}>
            <button
              className="primary-action"
              type="button"
              disabled={busy.mpt || Boolean(mpt?.issuanceId)}
              onClick={() => void mptAction(() => api.createMptIssuance())}
            >
              {busy.mpt ? "Working…" : "Create issuance (MPTokenIssuanceCreate)"}
            </button>
            <button
              className="primary-action"
              type="button"
              disabled={busy.mpt || !mpt?.issuanceId}
              onClick={() => void mptAction(() => api.mintMptAttestation())}
            >
              Mint attestation
            </button>
          </div>

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-end", marginBottom: "1rem" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
              <span className="muted" style={{ fontSize: "0.75rem" }}>Holder address</span>
              <input
                value={mptHolder}
                onChange={(e) => setMptHolder(e.target.value)}
                disabled={busy.mpt}
                placeholder="rHolder…"
                style={{ width: "18rem" }}
                spellCheck={false}
              />
            </label>
            <button
              className="primary-action"
              type="button"
              disabled={busy.mpt || !mpt?.issuanceId || !mptHolder}
              onClick={() => void mptAction(() => api.authorizeMptHolder({ holder: mptHolder }))}
            >
              Authorize (MPTokenAuthorize)
            </button>
          </div>

          {mpt && mpt.recentAttestations.length > 0 && (
            <ul className="credential-log">
              {mpt.recentAttestations.map((att) => (
                <li key={att.id} className="muted">
                  <code>{att.timestamp.slice(11, 19)}</code>{" "}
                  <strong>COMPLY</strong> → {att.recipient.slice(0, 16)}…{" "}
                  {att.amountSettled > 0 && <>({att.amountSettled.toLocaleString()} settled) </>}
                  <code style={{ fontSize: "0.7rem" }}>{att.txHash.slice(0, 12)}…</code>
                  {att.explorerUrl && (
                    <> · <a href={att.explorerUrl} target="_blank" rel="noreferrer">explorer</a></>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* XLS-65 Vault */}
        <section className="queue" aria-label="XLS-65 vault">
          <div className="section-heading" style={{ marginBottom: "0.75rem" }}>
            <span className="eyebrow">XLS-65 · XLS-66</span>
            <strong>Single Asset Vault — idle-treasury yield</strong>
          </div>
          <p className="muted" style={{ marginBottom: "1rem" }}>
            Idle RLUSD earns XLS-66 lending yield inside a vault. The agent sweeps excess above the
            threshold on each cycle and recalls funds when the wallet balance drops. Deterministic
            code decides; the LLM only narrates.{" "}
            <strong>Network: {vault?.network ?? "…"}</strong>
            {vault?.network === "devnet" && (
              <span className="muted"> (XLS-65 amendment — Devnet only today)</span>
            )}
          </p>

          {vault && (
            <div className="decision-row" style={{ flexWrap: "wrap", gap: "0.5rem", marginBottom: "1rem" }}>
              <div>
                <p className="muted">Vault ID</p>
                <code style={{ fontSize: "0.75rem" }}>{vault.vaultId ? `${vault.vaultId.slice(0, 16)}…` : "none"}</code>
              </div>
              <div>
                <p className="muted">Deposited</p>
                <strong>{vault.deposited.toLocaleString()} {vault.assetCurrency}</strong>
              </div>
              <div>
                <p className="muted">Shares</p>
                <strong>{vault.shares.toFixed(2)}</strong>
              </div>
              <div>
                <p className="muted">Hot wallet</p>
                <strong>{vault.walletBalance.toLocaleString()} {vault.assetCurrency}</strong>
              </div>
              <div>
                <p className="muted">Sweep ↑ / Recall ↓</p>
                <span className="muted">
                  {vault.sweepThresholdUsd.toLocaleString()} / {vault.recallThresholdUsd.toLocaleString()} USD
                </span>
              </div>
            </div>
          )}

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-end", marginBottom: "1rem" }}>
            <button
              className="primary-action"
              type="button"
              disabled={busy.vault || Boolean(vault?.vaultId)}
              onClick={() => void vaultAction(() => api.createVault())}
            >
              {busy.vault ? "Working…" : "Create vault (VaultCreate)"}
            </button>
            <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
              <span className="muted" style={{ fontSize: "0.75rem" }}>Amount</span>
              <input
                type="number"
                value={vaultAmount}
                onChange={(e) => setVaultAmount(Number(e.target.value))}
                disabled={busy.vault}
                min={0}
                style={{ width: "8rem" }}
              />
            </label>
            <button
              className="primary-action"
              type="button"
              disabled={busy.vault || !vault?.vaultId}
              onClick={() => void vaultAction(() => api.depositToVault(vaultAmount))}
            >
              Deposit (VaultDeposit)
            </button>
            <button
              className="primary-action"
              type="button"
              disabled={busy.vault || !vault?.vaultId}
              onClick={() => void vaultAction(() => api.withdrawFromVault(vaultAmount))}
            >
              Withdraw (VaultWithdraw)
            </button>
          </div>

          {vault && vault.recentOperations.length > 0 && (
            <ul className="credential-log">
              {vault.recentOperations.map((op) => (
                <li key={op.id} className="muted">
                  <code>{op.timestamp.slice(11, 19)}</code>{" "}
                  <strong>{op.operation}</strong>{" "}
                  {op.amount > 0 && <>{op.amount.toLocaleString()} {vault.assetCurrency} · </>}
                  <code style={{ fontSize: "0.7rem" }}>{op.txHash.slice(0, 12)}…</code>
                  {op.explorerUrl && (
                    <> · <a href={op.explorerUrl} target="_blank" rel="noreferrer">explorer</a></>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </section>
  );
}
