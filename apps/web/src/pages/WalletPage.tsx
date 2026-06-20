import { useCallback, useEffect, useState } from "react";
import type { WalletNetworkSnapshot, WalletOverview, WalletTransaction } from "@treasury/shared";

import { api } from "../lib/api.js";

function compact(value: string, left = 8, right = 6) {
  return value.length > left + right + 3 ? `${value.slice(0, left)}…${value.slice(-right)}` : value;
}

function displayNumber(value: string, maximumFractionDigits = 6) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits }).format(numeric);
}

function txAmount(transaction: WalletTransaction) {
  if (!transaction.amount) return "—";
  return `${displayNumber(transaction.amount.value)} ${transaction.amount.currency}`;
}

function NetworkPanel({ snapshot }: { snapshot: WalletNetworkSnapshot }) {
  return (
    <article className="wallet-network-card">
      <header className="wallet-network-header">
        <div>
          <span className="eyebrow">XRPL {snapshot.network}</span>
          <h2>{snapshot.network === "testnet" ? "Testnet" : "Devnet"}</h2>
        </div>
        <span className={`wallet-status ${snapshot.active ? "online" : "offline"}`}>
          {snapshot.active ? "Funded" : "Inactive"}
        </span>
      </header>

      {snapshot.error && <p className="wallet-notice">{snapshot.error}</p>}

      <div className="wallet-balance-grid">
        <div className="wallet-main-balance">
          <span>XRP balance</span>
          <strong>{displayNumber(snapshot.xrpBalance)} <small>XRP</small></strong>
        </div>
        <div className="wallet-ledger-stat">
          <span>Ledger</span>
          <strong>{snapshot.ledgerIndex?.toLocaleString() ?? "—"}</strong>
        </div>
        <div className="wallet-ledger-stat">
          <span>Owned objects</span>
          <strong>{snapshot.ownerCount ?? "—"}</strong>
        </div>
      </div>

      {snapshot.tokenBalances.length > 0 && (
        <div className="wallet-token-list" aria-label={`${snapshot.network} token balances`}>
          {snapshot.tokenBalances.map((balance, index) => (
            <div key={`${balance.currency}-${balance.issuer}-${index}`}>
              <span>{balance.currency}</span>
              <strong>{displayNumber(balance.value)}</strong>
              <code title={balance.issuer ?? undefined}>{balance.issuer ? compact(balance.issuer) : ""}</code>
            </div>
          ))}
        </div>
      )}

      <div className="wallet-table-heading">
        <div>
          <span className="eyebrow">Validated ledger activity</span>
          <h2>Recent transactions</h2>
        </div>
        <a href={snapshot.accountExplorerUrl} target="_blank" rel="noreferrer">Open account ↗</a>
      </div>

      <div className="wallet-table-wrap">
        <table className="wallet-table">
          <thead><tr><th>Transaction</th><th>Direction</th><th>Amount</th><th>Result</th><th>Time</th></tr></thead>
          <tbody>
            {snapshot.transactions.map((transaction) => (
              <tr key={transaction.hash}>
                <td><a href={transaction.explorerUrl} target="_blank" rel="noreferrer" title={transaction.hash}>{transaction.transactionType}<small>{compact(transaction.hash, 7, 5)}</small></a></td>
                <td><span className={`wallet-direction ${transaction.direction}`}>{transaction.direction}</span></td>
                <td>{txAmount(transaction)}</td>
                <td>{transaction.result ?? "—"}</td>
                <td>{transaction.timestamp ? new Date(transaction.timestamp).toLocaleString() : "—"}</td>
              </tr>
            ))}
            {snapshot.transactions.length === 0 && (
              <tr><td className="wallet-empty" colSpan={5}>No validated transactions found on this network.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </article>
  );
}

export function WalletPage() {
  const [wallet, setWallet] = useState<WalletOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try { setWallet(await api.getWallet()); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <section className="wallet-page" aria-label="Shared treasury wallet">
      <header className="wallet-hero">
        <div>
          <span className="eyebrow">Connected shared wallet</span>
          <h1>One address.<br />Two test ledgers.</h1>
          <p>Balances and validated activity are read directly by the Python API. Signing keys never reach this page.</p>
        </div>
        <button className="dashboard-primary" type="button" onClick={() => void refresh()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh ledgers"}
        </button>
      </header>

      {error && <p className="error">{error}</p>}
      {wallet && (
        <>
          <div className="wallet-address-bar">
            <div><span>Public XRPL address</span><code>{wallet.address}</code></div>
            <span>Updated {new Date(wallet.fetchedAt).toLocaleTimeString()}</span>
          </div>
          <div className="wallet-networks">
            {wallet.networks.map((snapshot) => <NetworkPanel key={snapshot.network} snapshot={snapshot} />)}
          </div>
        </>
      )}
    </section>
  );
}
