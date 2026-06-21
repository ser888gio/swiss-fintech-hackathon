import { useCallback, useEffect, useState } from "react";
import type { CredentialLogEntry, CredentialIssueRequest, CredentialRecord } from "@treasury/shared";

import { api } from "../lib/api.js";

const STATUS_LABEL: Record<CredentialRecord["status"], string> = {
  issued: "Issued · awaiting accept",
  accepted: "Accepted",
  verified: "Verified on-ledger",
  refused: "Refused in code",
  failed: "Failed",
};

// The credential-issuing agent signs CredentialCreate with CREDENTIAL_ISSUER_SEED
// and CredentialAccept with CREDENTIAL_SUBJECT_SEED — so auto-accept only works
// for the subject whose seed is configured. The first entry is that subject (the
// funded Devnet account) so issue+accept completes on-ledger. The sanctioned
// entry is refused in code by NAME.
const ACCEPTING_SUBJECT = import.meta.env.VITE_TREASURY_WALLET_ADDRESS ?? "rn71NnspjRQTneQuXbxCo54JFTPTW3U5iV";

const SUBJECTS = [
  { label: "Configured subject wallet — accepts on-ledger", name: "Credentialed User", account: ACCEPTING_SUBJECT },
  { label: "Globex Trading Ltd — triggers KYC gate", name: "Globex Trading Ltd", account: "rnt6pfdVx7cRsSrzm38783o7H4unfkpRqv" },
  { label: "Sanctioned party — issuance refused", name: "ACME Shell Co", account: "rDabdgRBdnms9zkbNtaLaVwqJuSbxjgroC" },
];

export function CredentialsPage() {
  const [records, setRecords] = useState<CredentialRecord[]>([]);
  const [subject, setSubject] = useState(SUBJECTS[0].account);
  const [subjectName, setSubjectName] = useState(SUBJECTS[0].name);
  const [userId, setUserId] = useState("");
  const [subjectCountry, setSubjectCountry] = useState("CH");
  const [subjectEntityType, setSubjectEntityType] = useState<"company" | "individual">("company");
  const [credentialType, setCredentialType] = useState("KYC");
  const [autoAccept, setAutoAccept] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedLogs, setExpandedLogs] = useState<Record<string, CredentialLogEntry[]>>({});
  const subjectMismatch = subject.trim().length > 0 && subject.trim() !== ACCEPTING_SUBJECT;

  const refresh = useCallback(async () => {
    try {
      const nextRecords = await api.listCredentials();
      setRecords(nextRecords);
      // Expanded log state is ephemeral React state. Rehydrate every record's
      // audit log so a browser refresh does not make the creation trail vanish.
      const logPairs = await Promise.all(
        nextRecords.map(async (record) => {
          try {
            return [record.id, await api.getCredentialLogs(record.id)] as const;
          } catch {
            return [record.id, []] as const;
          }
        }),
      );
      setExpandedLogs(Object.fromEntries(logPairs));
    } catch (cause) {
      setError(String(cause));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const submit = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const req: CredentialIssueRequest = {
        subject: subject.trim(),
        userId: userId.trim() || null,
        subjectName: subjectName.trim() || null,
        subjectCountry: subjectCountry.trim().toUpperCase() || null,
        subjectEntityType,
        credentialType: credentialType.trim() || null,
        uri: null,
        autoAccept,
      };
      await api.issueCredential(req);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }, [subject, subjectName, subjectCountry, subjectEntityType, userId, credentialType, autoAccept, refresh]);

  const act = useCallback(
    async (action: () => Promise<CredentialRecord>) => {
      setError(null);
      try {
        await action();
        await refresh();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    },
    [refresh],
  );

  const toggleLogs = useCallback(async (record: CredentialRecord) => {
    if (expandedLogs[record.id]) {
      setExpandedLogs((prev) => { const next = { ...prev }; delete next[record.id]; return next; });
      return;
    }
    try {
      const logs = await api.getCredentialLogs(record.id);
      setExpandedLogs((prev) => ({ ...prev, [record.id]: logs }));
    } catch {
      // best-effort
    }
  }, [expandedLogs]);

  return (
    <section className="send-flow" aria-label="Credential issuing agent">
      <div className="send-left">
        <div style={{ padding: "0.55rem 0.75rem", marginBottom: "1rem", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: "0.82rem", lineHeight: 1.5 }}>
          <strong style={{ color: "var(--paper)" }}>Credentials (XLS-70)</strong> — issue and manage XRPL verifiable credentials (KYC attestations) for counterparties. Payments to addresses without a valid credential trigger a compliance AML flag that locks the payment until the credential is accepted on-ledger. This page lets you issue credentials, accept them as the subject, and verify them — removing the compliance gate and allowing the payment to proceed or scale normally (still subject to policy thresholds and <a href="https://firefly.app/" target="_blank" rel="noreferrer" style={{ color: "var(--orange)", textDecoration: "none" }}>Firefly</a> approval if needed).
        </div>
        <div className="send-topbar">
          <div>
            <span className="eyebrow">Credential agent · XLS-70</span>
            <h1>Issue XRPL credentials</h1>
          </div>
        </div>

        {/* KYC gate scenario callout */}
        <div className="gate-scenario">
          <strong>How the gate works</strong>
          <ol>
            <li>Send a payment to <code>rUNVERIFIED…</code> — the compliance screen raises the AML score above the flag threshold because no KYC credential exists. The payment is locked on-chain for Firefly approval.</li>
            <li>Issue + accept a KYC credential here (use <em>Auto-accept</em> for a one-click demo, or accept manually to show the two-step XLS-70 lifecycle).</li>
            <li>Retry the same payment — AML score drops, policy auto-settles it. A large payment still escalates: the credential removes the KYC flag, but not the amount threshold.</li>
          </ol>
          <p className="muted">Deterministic code decides. The LLM only narrates the outcome.</p>
        </div>

        {error && <p className="error" role="alert">{error}</p>}

        <section className="recipient-panel" aria-label="New credential">
          <div className="section-heading">
            <span className="eyebrow">New credential</span>
            <strong>Subject &amp; type</strong>
          </div>
          <label>
            <span>Subject name</span>
            <input name="subject-name" autoComplete="off" value={subjectName} onChange={(e) => setSubjectName(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>User ID (off-ledger)</span>
            <input name="user-id" autoComplete="off" value={userId} onChange={(e) => setUserId(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>Subject address</span>
            <input name="subject-address" autoComplete="off" value={subject} onChange={(e) => setSubject(e.target.value)} disabled={busy} spellCheck={false} />
          </label>
          {subjectMismatch && (
            <p className="credential-warning" role="status">
              This demo can only auto-accept credentials for <code>{ACCEPTING_SUBJECT}</code>. A different subject can still be issued a credential, but acceptance must happen from that subject wallet.
            </p>
          )}
          <div className="recipient-meta">
            <label>
              <span>Country</span>
              <input name="subject-country" autoComplete="country" value={subjectCountry} onChange={(e) => setSubjectCountry(e.target.value)} disabled={busy} maxLength={2} />
            </label>
            <label>
              <span>Type</span>
              <select name="subject-entity-type" value={subjectEntityType} onChange={(e) => setSubjectEntityType(e.target.value as "company" | "individual")} disabled={busy}>
                <option value="company">Company</option>
                <option value="individual">Individual</option>
              </select>
            </label>
            <label>
              <span>Credential type</span>
              <input name="credential-type" autoComplete="off" value={credentialType} onChange={(e) => setCredentialType(e.target.value)} disabled={busy} />
            </label>
          </div>
          <label className="checkbox-label">
            <input
              type="checkbox"
              name="auto-accept"
              checked={autoAccept}
              onChange={(e) => setAutoAccept(e.target.checked)}
              disabled={busy}
            />
            <span>
              Auto-accept (one-step demo){" "}
              <span className="muted">— uncheck to show the two-step issue→accept lifecycle</span>
            </span>
          </label>
        </section>

        <button
          className="primary-action"
          type="button"
          disabled={busy || subject.trim().length === 0}
          onClick={() => void submit()}
        >
          {busy ? "Issuing…" : autoAccept && subjectMismatch ? "Issue Credential (accept blocked)" : autoAccept ? "Issue & Accept Credential" : "Issue Credential"}
        </button>

        <section className="queue">
          <h2>Issued credentials</h2>
          {records.length === 0 && <p className="muted">No credentials issued yet.</p>}
          {records.map((record) => (
            <article className="decision-row" key={record.id}>
              <div>
                <strong>
                  {record.credentialType} for {record.subjectName ?? record.subject}
                </strong>
                {record.userId && <p className="muted">User: <code>{record.userId}</code></p>}
                {record.subjectCountry && <p className="muted">{record.subjectCountry} · {record.subjectEntityType ?? "company"}</p>}
                <p className="muted">Subject wallet: <code>{record.subject}</code></p>
                {record.subject !== ACCEPTING_SUBJECT && (
                  <p className="credential-warning" role="status">
                    This credential belongs to a different wallet than the demo signer. Use that subject wallet to accept it, or reissue it to <code>{ACCEPTING_SUBJECT}</code> for the one-click path.
                  </p>
                )}
                <p>
                  <span className={`dashboard-status status-${record.status}`}>
                    {STATUS_LABEL[record.status]}
                  </span>{" "}
                  {record.auditExplanation ?? record.refusedReason ?? ""}
                </p>
                <code>{record.subject.slice(0, 20)}…</code>
                {record.txHash && <code> · create {record.txHash.slice(0, 12)}…</code>}
                {record.acceptTxHash && <code> · accept {record.acceptTxHash.slice(0, 12)}…</code>}

                {expandedLogs[record.id] && (
                  <ul className="credential-log">
                    {expandedLogs[record.id].map((entry, i) => (
                      <li key={i} className="muted">
                        <code>{entry.timestamp.slice(11, 19)}</code> {entry.message}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="decision-actions">
                {record.explorerUrl && (
                  <a href={record.explorerUrl} target="_blank" rel="noreferrer">
                    testnet.xrpl.org
                  </a>
                )}
                {record.acceptExplorerUrl && (
                  <a href={record.acceptExplorerUrl} target="_blank" rel="noreferrer">
                    accept tx
                  </a>
                )}
                <button className="text-action" type="button" onClick={() => void toggleLogs(record)}>
                  {expandedLogs[record.id] ? "Hide log" : "Log"}
                </button>
                {record.status === "issued" && (
                  <button
                    className="text-action"
                    type="button"
                    disabled={record.subject !== ACCEPTING_SUBJECT}
                    title={record.subject !== ACCEPTING_SUBJECT ? "Only the subject wallet can accept this credential in the current demo" : undefined}
                    onClick={() => void act(async () => {
                      await api.acceptCredential(record.id);
                      return api.verifyCredential(record.id);
                    })}
                  >
                    Accept &amp; verify on-ledger
                  </button>
                )}
                {record.status !== "refused" && record.status !== "failed" && (
                  <button
                    className="text-action"
                    type="button"
                    onClick={() => void act(() => api.verifyCredential(record.id))}
                  >
                    Verify on-ledger
                  </button>
                )}
              </div>
            </article>
          ))}
        </section>
      </div>
    </section>
  );
}
