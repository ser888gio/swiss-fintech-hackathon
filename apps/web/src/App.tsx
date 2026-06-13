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
        const challenge = await api.getChallenge(payment.id);
        const signed = await signOnFirefly({ paymentId: payment.id, digest: challenge.digest });
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
          />
        ))}
      </section>
    </main>
  );
}
