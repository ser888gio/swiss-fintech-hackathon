import { useMemo, useState } from "react";
import type { Payment, PaymentIntent } from "@treasury/shared";

interface Props {
  onSubmit: (intent: PaymentIntent) => Promise<Payment | null>;
  disabled: boolean;
}

const TREASURY = "rTREASURY00000000000000000000000000";

const SENDERS = [
  { label: "Main Treasury", owner: "John Doe", account: TREASURY, balance: 184250 },
  { label: "Operating USD", owner: "Acme AG", account: "rOPERATING000000000000000000000000", balance: 52800 },
];

const RECIPIENTS = [
  { label: "Vendor Alpha", account: "rVENDOR0000000000000000000000000000" },
  { label: "Supplier Zurich", account: "rSUPPLIER000000000000000000000000000" },
  { label: "Custom recipient", account: "rCUSTOM0000000000000000000000000000" },
];

const NUMPAD = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "backspace"];

function money(amount: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: amount % 1 === 0 ? 0 : 2,
  }).format(amount);
}

function amountFromInput(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function appendDigit(current: string, digit: string) {
  if (digit === "backspace") {
    return current.length > 1 ? current.slice(0, -1) : "0";
  }

  if (digit === "." && current.includes(".")) return current;
  if (current === "0" && digit !== ".") return digit;

  const next = `${current}${digit}`;
  const [, cents] = next.split(".");
  if (cents && cents.length > 2) return current;
  return next;
}

export function NewPaymentForm({ onSubmit, disabled }: Props) {
  const [step, setStep] = useState<"input" | "review" | "verification" | "success" | "failure">("input");
  const [senderIndex, setSenderIndex] = useState(0);
  const [recipientIndex, setRecipientIndex] = useState(0);
  const [amountInput, setAmountInput] = useState("0");
  const [currency, setCurrency] = useState("USD");
  const [reference, setReference] = useState("Invoice #1042");
  const [lastPayment, setLastPayment] = useState<Payment | null>(null);
  const [failureReason, setFailureReason] = useState("");

  const amount = amountFromInput(amountInput);
  const sender = SENDERS[senderIndex];
  const recipient = RECIPIENTS[recipientIndex];
  const canReview = amount > 0 && reference.trim().length > 0 && !disabled;

  const intent = useMemo<PaymentIntent>(
    () => ({
      from: sender.account,
      to: recipient.account,
      amount,
      currency,
      reference: reference.trim(),
    }),
    [amount, currency, recipient.account, reference, sender.account],
  );

  async function sendPayment() {
    setFailureReason("");
    try {
      const payment = await onSubmit(intent);
      setLastPayment(payment);

      if (!payment) {
        setFailureReason("The payment could not be created.");
        setStep("failure");
        return;
      }

      if (payment.status === "pending_approval") {
        setStep("verification");
        return;
      }

      if (payment.status === "settled" || payment.status === "released") {
        setStep("success");
        return;
      }

      if (payment.status === "blocked" || payment.status === "failed") {
        setFailureReason(payment.policyDecision?.blockReason ?? payment.auditExplanation ?? "The transfer was rejected.");
        setStep("failure");
        return;
      }

      setStep("success");
    } catch (cause) {
      setFailureReason(cause instanceof Error ? cause.message : String(cause));
      setStep("failure");
    }
  }

  function resetFlow() {
    setStep("input");
    setAmountInput("0");
    setReference("Invoice #1042");
    setLastPayment(null);
    setFailureReason("");
  }

  return (
    <section className="send-flow" aria-label="Send payment">
      <div className="send-topbar">
        <div>
          <span className="eyebrow">Send payment</span>
          <h1>Move funds</h1>
        </div>
        <span className="policy-pill">Code-enforced policy</span>
      </div>

      <div className="account-row">
        <label>
          <span>From</span>
          <select value={senderIndex} onChange={(event) => setSenderIndex(Number(event.target.value))} disabled={disabled}>
            {SENDERS.map((option, index) => (
              <option key={option.account} value={index}>
                {option.label} - {option.owner}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>To</span>
          <select value={recipientIndex} onChange={(event) => setRecipientIndex(Number(event.target.value))} disabled={disabled}>
            {RECIPIENTS.map((option, index) => (
              <option key={option.account} value={index}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="amount-stage">
        <p className="balance">Available balance {money(sender.balance, currency)}</p>
        <div className="amount-display" aria-live="polite">
          {money(amount, currency)}
        </div>
        <div className="currency-switch" aria-label="Currency">
          {["USD", "EUR"].map((option) => (
            <button
              key={option}
              type="button"
              className={currency === option ? "active" : ""}
              onClick={() => setCurrency(option)}
              disabled={disabled}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      <label className="reference-field">
        <span>Reference</span>
        <input value={reference} onChange={(event) => setReference(event.target.value)} disabled={disabled} />
      </label>

      <button className="primary-action" type="button" disabled={!canReview} onClick={() => setStep("review")}>
        Review
      </button>

      <div className="numpad" aria-label="Amount keypad">
        {NUMPAD.map((key) => (
          <button key={key} type="button" disabled={disabled} onClick={() => setAmountInput((current) => appendDigit(current, key))}>
            {key === "backspace" ? "Del" : key}
          </button>
        ))}
      </div>

      {step === "review" && (
        <div className="sheet-backdrop" role="presentation">
          <div className="bottom-sheet" role="dialog" aria-modal="true" aria-label="Review payment">
            <div className="sheet-handle" />
            <h2>Review transfer</h2>
            <div className="summary-list">
              <div>
                <span>Amount</span>
                <strong>{money(amount, currency)}</strong>
              </div>
              <div>
                <span>From</span>
                <strong>{sender.label}</strong>
              </div>
              <div>
                <span>To</span>
                <strong>{recipient.label}</strong>
              </div>
              <div>
                <span>Estimated fee</span>
                <strong>Calculated by routing</strong>
              </div>
            </div>
            <button className="primary-action" type="button" disabled={disabled} onClick={() => void sendPayment()}>
              {disabled ? "Processing..." : `Send ${money(amount, currency)}`}
            </button>
            <button className="secondary-action" type="button" onClick={() => setStep("input")} disabled={disabled}>
              Back
            </button>
          </div>
        </div>
      )}

      {step === "verification" && lastPayment && (
        <div className="sheet-backdrop" role="presentation">
          <div className="verification-modal" role="dialog" aria-modal="true" aria-label="Verification required">
            <div className="security-pulse">FF</div>
            <h2>Verification required</h2>
            <p>Please confirm this transaction on your Firefly.app device. Funds are locked until the signed approval is verified.</p>
            <div className="progress-line" />
            <p className="muted">Waiting for Firefly.app confirmation in the payment queue...</p>
            <button className="primary-action" type="button" onClick={() => setStep("input")}>
              View queue
            </button>
            <button className="secondary-action" type="button">
              Didn't get a notification?
            </button>
          </div>
        </div>
      )}

      {step === "success" && lastPayment && (
        <div className="outcome success-outcome" role="status">
          <div className="outcome-mark">OK</div>
          <h2>Sent successfully</h2>
          <p>
            You sent {money(lastPayment.intent.amount, lastPayment.intent.currency)} to {recipient.label}.
          </p>
          <button className="primary-action" type="button" onClick={resetFlow}>
            Done
          </button>
        </div>
      )}

      {step === "failure" && (
        <div className="outcome failure-outcome" role="alert">
          <div className="outcome-mark">!</div>
          <h2>Transfer failed</h2>
          <div className="reason-box">{failureReason || "The transfer could not be completed."}</div>
          <button className="primary-action" type="button" onClick={() => setStep("review")}>
            Try again
          </button>
          <button className="secondary-action" type="button" onClick={resetFlow}>
            Cancel
          </button>
        </div>
      )}
    </section>
  );
}
