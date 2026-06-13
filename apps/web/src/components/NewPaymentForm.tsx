import { useEffect, useMemo, useState } from "react";
import type { Payment, PaymentIntent, RouteQuote } from "@treasury/shared";

import { api } from "../lib/api.js";

interface Props {
  onSubmit: (intent: PaymentIntent) => Promise<Payment | null>;
  disabled: boolean;
}

const TREASURY = "rTREASURY00000000000000000000000000";
const QUOTE_REFRESH_MS = 15000;

const SENDERS = [
  { label: "Main Treasury", owner: "John Doe", country: "CH", account: TREASURY, balance: 184250 },
  { label: "Operating USD", owner: "Acme AG", country: "CH", account: "rOPERATING000000000000000000000000", balance: 52800 },
];

const RECIPIENTS = [
  { label: "Vendor Alpha", country: "US", entityType: "company" as const, account: "rVENDOR0000000000000000000000000000" },
  { label: "Supplier Zurich", country: "CH", entityType: "company" as const, account: "rSUPPLIER000000000000000000000000000" },
  { label: "Custom recipient", country: "GB", entityType: "company" as const, account: "rCUSTOM0000000000000000000000000000" },
];

const NUMPAD = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "backspace"];
const CURRENCIES = ["USD", "EUR", "XRP"];

function money(amount: number, currency: string) {
  if (currency === "XRP") {
    return `${new Intl.NumberFormat("en-US", {
      maximumFractionDigits: amount % 1 === 0 ? 0 : 6,
    }).format(amount)} XRP`;
  }

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
  const [, decimals] = next.split(".");
  if (decimals && decimals.length > 6) return current;
  return next;
}

function formatRate(route: RouteQuote | null, currency: string) {
  if (!route) return "Fetching live rate...";
  return `1 ${currency} = ${money(route.rate, "USD")}`;
}

function quoteAge(updatedAt: Date | null) {
  if (!updatedAt) return "Waiting for first update";
  return `Updated ${updatedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
}

export function NewPaymentForm({ onSubmit, disabled }: Props) {
  const [step, setStep] = useState<"input" | "review" | "verification" | "success" | "failure">("input");
  const [senderIndex, setSenderIndex] = useState(0);
  const [recipientIndex, setRecipientIndex] = useState(0);
  const [recipientName, setRecipientName] = useState(RECIPIENTS[0].label);
  const [recipientWallet, setRecipientWallet] = useState(RECIPIENTS[0].account);
  const [recipientCountry, setRecipientCountry] = useState(RECIPIENTS[0].country);
  const [recipientEntityType, setRecipientEntityType] = useState<"company" | "individual">(RECIPIENTS[0].entityType);
  const [amountInput, setAmountInput] = useState("0");
  const [currency, setCurrency] = useState("USD");
  const [purpose, setPurpose] = useState("supplier_payment");
  const [reference, setReference] = useState("Invoice #1042");
  const [routeQuote, setRouteQuote] = useState<RouteQuote | null>(null);
  const [quoteUpdatedAt, setQuoteUpdatedAt] = useState<Date | null>(null);
  const [quoteError, setQuoteError] = useState("");
  const [lastPayment, setLastPayment] = useState<Payment | null>(null);
  const [failureReason, setFailureReason] = useState("");

  const amount = amountFromInput(amountInput);
  const sender = SENDERS[senderIndex];
  const networkFee = Math.max((routeQuote?.destAmount ?? amount) * 0.001, currency === "XRP" ? 0.000012 : 1.21);
  const receiveAmount = routeQuote?.destAmount ?? amount;
  const recipientSummary = `${recipientCountry} - ${recipientEntityType} - ${recipientWallet.slice(0, 14)}...`;
  const canReview = amount > 0 && reference.trim().length > 0 && recipientName.trim().length > 0 && recipientWallet.trim().length > 0 && !disabled;

  useEffect(() => {
    const selected = RECIPIENTS[recipientIndex];
    setRecipientName(selected.label);
    setRecipientWallet(selected.account);
    setRecipientCountry(selected.country);
    setRecipientEntityType(selected.entityType);
  }, [recipientIndex]);

  useEffect(() => {
    let cancelled = false;

    async function refreshQuote() {
      if (amount <= 0) {
        setRouteQuote(null);
        setQuoteUpdatedAt(null);
        setQuoteError("");
        return;
      }

      try {
        const quote = await api.quotePayment({ amount, currency });
        if (cancelled) return;
        setRouteQuote(quote);
        setQuoteUpdatedAt(new Date());
        setQuoteError("");
      } catch (cause) {
        if (cancelled) return;
        setRouteQuote(null);
        setQuoteUpdatedAt(null);
        setQuoteError(cause instanceof Error ? cause.message : String(cause));
      }
    }

    void refreshQuote();
    const timer = window.setInterval(() => void refreshQuote(), QUOTE_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [amount, currency]);

  const intent = useMemo<PaymentIntent>(
    () => ({
      from: sender.account,
      to: recipientWallet.trim(),
      senderName: sender.owner,
      senderCountry: sender.country,
      receiverName: recipientName.trim(),
      receiverCountry: recipientCountry.trim().toUpperCase(),
      receiverEntityType: recipientEntityType,
      purpose,
      amount,
      currency,
      reference: reference.trim(),
    }),
    [amount, currency, purpose, recipientCountry, recipientEntityType, recipientName, recipientWallet, reference, sender.account, sender.country, sender.owner],
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
        <span className="policy-pill">Live XRPL quote</span>
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
          <span>Saved recipient</span>
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
          {CURRENCIES.map((option) => (
            <button
              key={option}
              type="button"
              className={currency === option ? "active" : ""}
              onClick={() => setCurrency(option)}
              disabled={disabled}
            >
              {option === "XRP" ? "Ripple" : option}
            </button>
          ))}
        </div>
      </div>

      <section className="recipient-panel" aria-label="Recipient details">
        <div className="section-heading">
          <span className="eyebrow">Receive method</span>
          <strong>Wallet destination</strong>
        </div>
        <label>
          <span>Recipient name</span>
          <input value={recipientName} onChange={(event) => setRecipientName(event.target.value)} disabled={disabled} />
        </label>
        <label>
          <span>Wallet address</span>
          <input value={recipientWallet} onChange={(event) => setRecipientWallet(event.target.value)} disabled={disabled} spellCheck={false} />
        </label>
        <div className="recipient-meta">
          <label>
            <span>Country</span>
            <input value={recipientCountry} onChange={(event) => setRecipientCountry(event.target.value)} disabled={disabled} maxLength={2} />
          </label>
          <label>
            <span>Type</span>
            <select value={recipientEntityType} onChange={(event) => setRecipientEntityType(event.target.value as "company" | "individual")} disabled={disabled}>
              <option value="company">Company</option>
              <option value="individual">Individual</option>
            </select>
          </label>
        </div>
      </section>

      <label className="reference-field">
        <span>Reference</span>
        <input value={reference} onChange={(event) => setReference(event.target.value)} disabled={disabled} />
      </label>

      <label className="reference-field">
        <span>Purpose</span>
        <select value={purpose} onChange={(event) => setPurpose(event.target.value)} disabled={disabled}>
          <option value="supplier_payment">Supplier payment</option>
          <option value="vendor_invoice">Vendor invoice</option>
          <option value="treasury_transfer">Treasury transfer</option>
          <option value="payroll">Payroll</option>
        </select>
      </label>

      <section className="transaction-summary" aria-label="Transaction summary">
        <div className="section-heading">
          <span className="eyebrow">Transaction summary</span>
          <strong>{quoteAge(quoteUpdatedAt)}</strong>
        </div>
        <div className="summary-list">
          <div>
            <span>Exchange rate</span>
            <strong>{formatRate(routeQuote, currency)}</strong>
          </div>
          <div>
            <span>Estimated network fee</span>
            <strong>{money(networkFee, "USD")}</strong>
          </div>
          <div>
            <span>Recipient gets after routing</span>
            <strong>{money(receiveAmount, "USD")}</strong>
          </div>
          <div>
            <span>Wallet</span>
            <strong>{recipientWallet ? recipientWallet.slice(0, 18) : "Missing"}...</strong>
          </div>
        </div>
        {quoteError && <p className="quote-error">Live rate unavailable. The payment will retry the quote on submit.</p>}
      </section>

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
          <div className="confirmation-panel" role="dialog" aria-modal="true" aria-label="Payment confirmation">
            <header className="confirmation-header">
              <button className="back-action" type="button" onClick={() => setStep("input")} disabled={disabled}>
                Back
              </button>
              <h2>Confirmation</h2>
              <span className="confirmation-status">Ready</span>
            </header>

            <div className="confirmation-grid">
              <section className="confirmation-main">
                <div className="confirmation-row">
                  <span>From card</span>
                  <div>
                    <strong>Card for payments</strong>
                    <p>
                      {sender.owner} - {sender.country} - **** 1942
                    </p>
                  </div>
                </div>

                <div className="confirmation-row">
                  <span>Recipient</span>
                  <div>
                    <strong>{recipientName.toUpperCase()}</strong>
                    <p>{recipientSummary}</p>
                  </div>
                </div>

                <div className="fee-card">
                  <div>
                    <span>You pay</span>
                    <strong>{money(amount, currency)}</strong>
                  </div>
                  <div>
                    <span>Exchange rate</span>
                    <strong>{formatRate(routeQuote, currency)}</strong>
                  </div>
                  <div>
                    <span>Routing fee</span>
                    <strong>{money(networkFee, "USD")}</strong>
                  </div>
                  <div className="total-row">
                    <span>Recipient receives estimate</span>
                    <strong>{money(receiveAmount, "USD")}</strong>
                  </div>
                </div>
              </section>

              <aside className="confirmation-aside">
                <p className="eyebrow">Policy check</p>
                <h3>Code decides whether Firefly approval is required.</h3>
                <p className="muted">
                  Purpose: {purpose.replaceAll("_", " ")}. Reference: {reference}.
                </p>
                <button className="send-money-action" type="button" disabled={disabled} onClick={() => void sendPayment()}>
                  {disabled ? "Processing..." : "Send money"}
                </button>
              </aside>
            </div>
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
            You sent {money(lastPayment.intent.amount, lastPayment.intent.currency)} to {lastPayment.intent.receiverName}.
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
