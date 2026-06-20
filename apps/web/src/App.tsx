import { useCallback, useEffect, useState } from "react";
import type { Payment, PaymentIntent } from "@treasury/shared";

import { api } from "./lib/api.js";
import { signOnFirefly } from "./lib/firefly.js";
import { ARSPage } from "./pages/ARSPage.js";
import { CredentialsPage } from "./pages/CredentialsPage.js";
import { DashboardPage } from "./pages/DashboardPage.js";
import { InsurancePage } from "./pages/InsurancePage.js";
import { TransferPage } from "./pages/TransferPage.js";
import { TreasuryPage } from "./pages/TreasuryPage.js";

type Route = "/" | "/transfer" | "/credentials" | "/treasury" | "/ars" | "/insurance";

function currentRoute(): Route {
  if (window.location.pathname === "/transfer") return "/transfer";
  if (window.location.pathname === "/credentials") return "/credentials";
  if (window.location.pathname === "/treasury") return "/treasury";
  if (window.location.pathname === "/ars") return "/ars";
  if (window.location.pathname === "/insurance") return "/insurance";
  return "/";
}

export function App() {
  const [route, setRoute] = useState<Route>(currentRoute);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [busy, setBusy] = useState(false);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [resolvingKycId, setResolvingKycId] = useState<string | null>(null);
  const [tamperedId, setTamperedId] = useState<string | null>(null);
  const [tamperError, setTamperError] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setPayments(await api.listPayments());
    } catch (cause) {
      setError(String(cause));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onPopState = () => setRoute(currentRoute());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((path: string) => {
    const nextRoute: Route =
      path === "/transfer" ? "/transfer"
      : path === "/credentials" ? "/credentials"
      : path === "/treasury" ? "/treasury"
      : path === "/ars" ? "/ars"
      : path === "/insurance" ? "/insurance"
      : "/";
    if (window.location.pathname !== nextRoute) {
      window.history.pushState({}, "", nextRoute);
    }
    setRoute(nextRoute);
  }, []);

  const submit = useCallback(
    async (intent: PaymentIntent) => {
      setBusy(true);
      setError(null);
      try {
        const payment = await api.createPayment(intent);
        await refresh();
        return payment;
      } catch (cause) {
        setError(String(cause));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  const approve = useCallback(
    async (payment: Payment) => {
      setApprovingId(payment.id);
      setError(null);
      try {
        // Fetch the challenge to get network + owner (treasury wallet address)
        // without hardcoding them in the client. The bridge re-derives the
        // digest from the human-readable fields — WYSIWYS — and binds it to the
        // exact on-chain escrow via the escrow fields.
        const challenge = await api.challenge(payment.id);
        const signed = await signOnFirefly({
          paymentId: payment.id,
          amount: payment.intent.amount,
          currency: payment.intent.currency,
          dest: payment.intent.to,
          reference: payment.intent.reference,
          network: challenge.network,
          owner: challenge.owner,
          escrowSequence: payment.escrowSequence!,
          escrowCreateTxHash: payment.escrowCreateTxHash!,
        });
        await api.release(payment.id, signed.signature);
        await refresh();
      } catch (cause) {
        setError(String(cause));
      } finally {
        setApprovingId(null);
      }
    },
    [refresh],
  );

  // Inline KYC gate: issue + accept an XLS-70 credential for the receiver, then
  // resubmit the same intent. Policy is re-evaluated deterministically — issuing
  // a credential only removes the KYC risk flag; a large amount still escalates.
  const resolveKyc = useCallback(
    async (payment: Payment) => {
      setResolvingKycId(payment.id);
      setError(null);
      try {
        const record = await api.issueCredential({
          subject: payment.intent.to,
          subjectName: payment.intent.receiverName,
          autoAccept: true,
        });
        if (record.status === "refused" || record.status === "failed") {
          setError(record.refusedReason ?? "Credential could not be issued.");
          return;
        }
        await api.createPayment(payment.intent);
        await refresh();
      } catch (cause) {
        setError(String(cause));
      } finally {
        setResolvingKycId(null);
      }
    },
    [refresh],
  );

  const tamperAndRetry = useCallback(async (payment: Payment) => {
    if (!payment.approvalSignature) return;
    setTamperedId(payment.id);
    setTamperError((prev) => ({ ...prev, [payment.id]: "" }));
    try {
      await api.releaseTampered(payment.id, payment.approvalSignature);
    } catch (cause) {
      const msg = cause instanceof Error ? cause.message : String(cause);
      setTamperError((prev) => ({
        ...prev,
        [payment.id]: msg.includes("403") ? "SIGNATURE REJECTED - payment details were altered" : msg,
      }));
    } finally {
      setTamperedId(null);
    }
  }, []);

  return (
    <main>
      <nav className="app-nav" aria-label="Primary">
        <button className="brand-mark" type="button" onClick={() => navigate("/")}>
          Treasury Agent
        </button>
        <div>
          <button className={route === "/" ? "active" : ""} type="button" onClick={() => navigate("/")}>
            Dashboard
          </button>
          <button className={route === "/transfer" ? "active" : ""} type="button" onClick={() => navigate("/transfer")}>
            Transfer
          </button>
          <button className={route === "/credentials" ? "active" : ""} type="button" onClick={() => navigate("/credentials")}>
            Credentials
          </button>
          <button className={route === "/treasury" ? "active" : ""} type="button" onClick={() => navigate("/treasury")}>
            Agent
          </button>
          <button className={route === "/ars" ? "active" : ""} type="button" onClick={() => navigate("/ars")}>
            ARS
          </button>
          <button className={route === "/insurance" ? "active" : ""} type="button" onClick={() => navigate("/insurance")}>
            Insurance
          </button>
        </div>
      </nav>
      <p className="tagline">Autonomous treasury on XRPL. The AI explains; deterministic code decides.</p>
      {error && <p className="error">{error}</p>}

      {route === "/" && (
        <DashboardPage
          payments={payments}
          approvingId={approvingId}
          resolvingKycId={resolvingKycId}
          onApprove={approve}
          onResolveKyc={resolveKyc}
          onNavigate={navigate}
        />
      )}
      {route === "/transfer" && (
        <TransferPage
          payments={payments}
          busy={busy}
          approvingId={approvingId}
          resolvingKycId={resolvingKycId}
          tamperedId={tamperedId}
          tamperError={tamperError}
          onSubmit={submit}
          onApprove={approve}
          onResolveKyc={resolveKyc}
          onTamperRetry={tamperAndRetry}
        />
      )}
      {route === "/credentials" && <CredentialsPage />}
      {route === "/treasury" && <TreasuryPage />}
      {route === "/ars" && <ARSPage />}
      {route === "/insurance" && <InsurancePage />}

      {approvingId && (
        <div className="firefly-overlay" role="status" aria-live="polite">
          <div className="verification-modal">
            <div className="security-pulse">FF</div>
            <h2>Confirm on Firefly.app</h2>
            <p>Check the payment details on the device and approve with the physical control.</p>
            <div className="progress-line" />
            <p className="muted">Waiting for signed approval...</p>
          </div>
        </div>
      )}
    </main>
  );
}
