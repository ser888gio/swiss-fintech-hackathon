import { useCallback, useEffect, useState } from "react";
import type { Payment, PaymentIntent } from "@treasury/shared";

import { api } from "./lib/api.js";
import { signOnFirefly } from "./lib/firefly.js";
import { NewPaymentForm } from "./components/NewPaymentForm.js";
import { PaymentCard } from "./components/PaymentCard.js";

export function App() {
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

  const submit = useCallback(
    async (intent: PaymentIntent) => {
      setBusy(true);
      setError(null);
      try {
        await api.createPayment(intent);
        await refresh();
      } catch (cause) {
        setError(String(cause));
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
        // display and sign them — not a server-derived hash.
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

  const tamperAndRetry = useCallback(
    async (payment: Payment) => {
      if (!payment.approvalSignature) return;
      setTamperedId(payment.id);
      setTamperError((prev) => ({ ...prev, [payment.id]: "" }));
      try {
        await api.releaseTampered(payment.id, payment.approvalSignature);
      } catch (cause) {
        const msg = cause instanceof Error ? cause.message : String(cause);
        setTamperError((prev) => ({
          ...prev,
          [payment.id]: msg.includes("403") ? "SIGNATURE REJECTED — payment details were altered" : msg,
        }));
      } finally {
        setTamperedId(null);
      }
    },
    [],
  );

  return (
    <main>
      <h1>Treasury Agent · XRPL</h1>
      <p className="tagline">The agent handles the routine. The human controls what matters.</p>
      {error && <p className="error">{error}</p>}

      <NewPaymentForm onSubmit={submit} disabled={busy} />

      <section className="queue">
        <h2>Payments</h2>
        {payments.length === 0 && <p className="muted">No payments yet.</p>}
        {payments.map((payment) => (
          <PaymentCard
            key={payment.id}
            payment={payment}
            onApprove={approve}
            approving={approvingId === payment.id}
            onTamperRetry={tamperAndRetry}
            tampering={tamperedId === payment.id}
            tamperError={tamperError[payment.id]}
          />
        ))}
      </section>
    </main>
  );
}
