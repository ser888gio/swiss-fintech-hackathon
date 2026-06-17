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

// Real funded Testnet counterparties (repo-root .env). The credential-issuing
// agent signs CredentialCreate with CREDENTIAL_ISSUER_SEED and CredentialAccept
// with CREDENTIAL_SUBJECT_SEED, so auto-accept works for the "NEW" subject whose
// seed is configured. The sanctioned entry is refused in code by NAME.
const SUBJECTS = [
  { label: "Acme Supplies AG — KYC present", name: "Acme Supplies AG", account: "rwjNyXSKQ5Rt6StJHHPzdHY5KA8UqYjBuC" },
  { label: "Globex Trading Ltd — triggers KYC gate", name: "Globex Trading Ltd", account: "rnt6pfdVx7cRsSrzm38783o7H4unfkpRqv" },
  { label: "Sanctioned party — issuance refused", name: "ACME Shell Co", account: "rDabdgRBdnms9zkbNtaLaVwqJuSbxjgroC" },
];

export function CredentialsPage() {
  const [records, setRecords] = useState<CredentialRecord[]>([]);
  const [subjectIndex, setSubjectIndex] = useState(1); // default: no-credential subject — shows the gate
  const [subject, setSubject] = useState(SUBJECTS[1].account);
  const [subjectName, setSubjectName] = useState(SUBJECTS[1].name);
  const [credentialType, setCredentialType] = useState("KYC");
  const [uri, setUri] = useState("https://kyc.example/vc/123");
  const [autoAccept, setAutoAccept] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedLogs, setExpandedLogs] = useState<Record<string, CredentialLogEntry[]>>({});

  const refresh = useCallback(async () => {
    try {
      setRecords(await api.listCredentials());
    } catch (cause) {
      setError(String(cause));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const selected = SUBJECTS[subjectIndex];
    setSubject(selected.account);
    setSubjectName(selected.name);
  }, [subjectIndex]);

  const submit = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const req: CredentialIssueRequest = {
        subject: subject.trim(),
        subjectName: subjectName.trim() || null,
        credentialType: credentialType.trim() || null,
        uri: uri.trim() || null,
        autoAccept,
      };
      await api.issueCredential(req);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }, [subject, subjectName, credentialType, uri, autoAccept, refresh]);

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
        <div className="send-topbar">
          <div>
            <span className="eyebrow">Credential agent · XLS-70</span>
            <h1>Issue XRPL credentials</h1>
          </div>
          <span className="policy-pill">code decides · LLM narrates</span>
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

        {error && <p className="error">{error}</p>}

        <section className="recipient-panel" aria-label="New credential">
          <div className="section-heading">
            <span className="eyebrow">New credential</span>
            <strong>Subject &amp; type</strong>
          </div>
          <label>
            <span>Saved subject</span>
            <select value={subjectIndex} onChange={(e) => setSubjectIndex(Number(e.target.value))} disabled={busy}>
              {SUBJECTS.map((option, index) => (
                <option key={option.account} value={index}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Subject name</span>
            <input value={subjectName} onChange={(e) => setSubjectName(e.target.value)} disabled={busy} />
          </label>
          <label>
            <span>Subject address</span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} disabled={busy} spellCheck={false} />
          </label>
          <div className="recipient-meta">
            <label>
              <span>Credential type</span>
              <input value={credentialType} onChange={(e) => setCredentialType(e.target.value)} disabled={busy} />
            </label>
            <label>
              <span>VC URI (off-chain)</span>
              <input value={uri} onChange={(e) => setUri(e.target.value)} disabled={busy} spellCheck={false} />
            </label>
          </div>
          <label className="checkbox-label">
            <input
              type="checkbox"
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
          {busy ? "Issuing..." : autoAccept ? "Issue & accept credential" : "Issue credential"}
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
                {(record.status === "issued" || record.status === "accepted") && (
                  <button
                    className="text-action"
                    type="button"
                    onClick={() => void act(() => api.acceptCredential(record.id))}
                  >
                    Accept (subject)
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
