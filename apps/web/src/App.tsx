import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import type { MouseEvent } from "react";
import type { Payment, PaymentIntent } from "@treasury/shared";

import { api } from "./lib/api.js";
import { signOnFirefly } from "./lib/firefly.js";
import { DashboardPage } from "./pages/DashboardPage.js";

//const ARSPage = lazy(() => import("./pages/ARSPage.js").then((module) => ({ default: module.ARSPage })));
const CoverPage = lazy(() => import("./pages/CoverPage.js").then((module) => ({ default: module.CoverPage })));
const CredentialsPage = lazy(() => import("./pages/CredentialsPage.js").then((module) => ({ default: module.CredentialsPage })));
const TransferPage = lazy(() => import("./pages/TransferPage.js").then((module) => ({ default: module.TransferPage })));
const TreasuryPage = lazy(() => import("./pages/TreasuryPage.js").then((module) => ({ default: module.TreasuryPage })));
const WalletPage = lazy(() => import("./pages/WalletPage.js").then((module) => ({ default: module.WalletPage })));
const DemoLabPage = lazy(() => import("./pages/DemoLabPage.js").then((module) => ({ default: module.DemoLabPage })));
const SanctionsPage = lazy(() => import("./pages/SanctionsPage.js").then((module) => ({ default: module.SanctionsPage })));

type Route = "/" | "/transfer" | "/credentials" | "/treasury" | "/wallet" | "/cover" | "/demo" | "/sanctions";

function currentRoute(): Route {
  if (window.location.pathname === "/transfer") return "/transfer";
  if (window.location.pathname === "/credentials") return "/credentials";
  if (window.location.pathname === "/treasury") return "/treasury";
  //if (window.location.pathname === "/ars") return "/ars";
  if (window.location.pathname === "/wallet") return "/wallet";
  if (window.location.pathname === "/cover") return "/cover";
  if (window.location.pathname === "/demo") return "/demo";
  if (window.location.pathname === "/sanctions") return "/sanctions";
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
      //: path === "/ars" ? "/ars"
      : path === "/wallet" ? "/wallet"
      : path === "/cover" ? "/cover"
      : path === "/demo" ? "/demo"
      : path === "/sanctions" ? "/sanctions"
      : "/";
    if (window.location.pathname !== nextRoute) {
      window.history.pushState({}, "", nextRoute);
    }
    setRoute(nextRoute);
  }, []);

  const followLink = useCallback((event: MouseEvent<HTMLAnchorElement>, path: string) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(path);
  }, [navigate]);

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
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to Main Content</a>
      <aside className="app-sidebar">
        <nav className="app-nav" aria-label="Primary">
          <div className="brand-mark">
            <span className="brand-kicker">XRPL Treasury System</span>
            <a className="brand-title" href="/" onClick={(event) => followLink(event, "/")}>
              Treasury Agent
            </a>
            <p className="brand-copy">Deterministic payment controls with an AI orchestration layer.</p>
          </div>
          <div className="app-nav-links">
            <a className={route === "/demo" ? "active" : ""} href="/demo" aria-current={route === "/demo" ? "page" : undefined} onClick={(event) => followLink(event, "/demo")}>
              Demo Lab
            </a>
            <a className={route === "/" ? "active" : ""} href="/" aria-current={route === "/" ? "page" : undefined} onClick={(event) => followLink(event, "/")}>
              Dashboard
            </a>
            <a className={route === "/treasury" ? "active" : ""} href="/treasury" aria-current={route === "/treasury" ? "page" : undefined} onClick={(event) => followLink(event, "/treasury")}>
              Agent
            </a>
            <a className={route === "/wallet" ? "active" : ""} href="/wallet" aria-current={route === "/wallet" ? "page" : undefined} onClick={(event) => followLink(event, "/wallet")}>
              Shared wallet
            </a>
            <a className={route === "/cover" ? "active" : ""} href="/cover" aria-current={route === "/cover" ? "page" : undefined} onClick={(event) => followLink(event, "/cover")}>
              Agent Cover
            </a>
            {/* <a className={route === "/ars" ? "active" : ""} href="/ars" aria-current={route === "/ars" ? "page" : undefined} onClick={(event) => followLink(event, "/ars")}>
              ARS
            </a> */}
            <a className={route === "/credentials" ? "active" : ""} href="/credentials" aria-current={route === "/credentials" ? "page" : undefined} onClick={(event) => followLink(event, "/credentials")}>
              Credentials
            </a>
            <a className={route === "/sanctions" ? "active" : ""} href="/sanctions" aria-current={route === "/sanctions" ? "page" : undefined} onClick={(event) => followLink(event, "/sanctions")}>
              Sanctions
            </a>
            <a className={route === "/transfer" ? "active" : ""} href="/transfer" aria-current={route === "/transfer" ? "page" : undefined} onClick={(event) => followLink(event, "/transfer")}>
              Transfer
            </a>
          </div>
        </nav>
      </aside>

      <main className="app-content" id="main-content" tabIndex={-1}>
        <p className="tagline">Autonomous treasury on XRPL. The AI explains; deterministic code decides.</p>
        {error && <p className="error" role="alert" aria-live="polite">{error}</p>}

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
        <Suspense fallback={<p className="route-loading" role="status">Loading workspace…</p>}>
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
          {/* {route === "/ars" && <ARSPage />} */}
          {route === "/cover" && <CoverPage />}
          {route === "/wallet" && <WalletPage />}
          {route === "/demo" && <DemoLabPage />}
          {route === "/sanctions" && <SanctionsPage />}
        </Suspense>
      </main>

      {approvingId && (
        <div className="firefly-overlay" role="status" aria-live="polite">
          <div className="verification-modal">
            <div className="security-pulse">FF</div>
            <h2>Confirm on Firefly.app</h2>
            <p>Check the payment details on the device and approve with the physical control.</p>
            <div className="progress-line" />
            <p className="muted">Waiting for signed approval…</p>
          </div>
        </div>
      )}
    </div>
  );
}
