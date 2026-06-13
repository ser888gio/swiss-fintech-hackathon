import { useCallback, useEffect, useState } from "react";
import type { Payment, PaymentIntent } from "@treasury/shared";

import { api } from "./lib/api.js";
import { signOnFirefly } from "./lib/firefly.js";
import { DashboardPage } from "./pages/DashboardPage.js";
import { TransferPage } from "./pages/TransferPage.js";

type Route = "/" | "/transfer";

function currentRoute(): Route {
  return window.location.pathname === "/transfer" ? "/transfer" : "/";
}

export function App() {
  const [route, setRoute] = useState<Route>(currentRoute);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [busy, setBusy] = useState(false);
  const [approvingId, setApprovingId] = useState<string | null>(null);
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
    const nextRoute: Route = path === "/transfer" ? "/transfer" : "/";
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
        // WYSIWYS: send the actual payment fields to the bridge so it can
        // display and sign them, not a server-derived hash.
        const signed = await signOnFirefly({
          paymentId: payment.id,
          amount: payment.intent.amount,
          currency: payment.intent.currency,
          dest: payment.intent.to,
          reference: payment.intent.reference,
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
        </div>
      </nav>
      <p className="tagline">Autonomous treasury on XRPL. The AI explains; deterministic code decides.</p>
      {error && <p className="error">{error}</p>}

      {route === "/" ? (
        <DashboardPage payments={payments} approvingId={approvingId} onApprove={approve} onNavigate={navigate} />
      ) : (
        <TransferPage
          payments={payments}
          busy={busy}
          approvingId={approvingId}
          tamperedId={tamperedId}
          tamperError={tamperError}
          onSubmit={submit}
          onApprove={approve}
          onTamperRetry={tamperAndRetry}
        />
      )}

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
