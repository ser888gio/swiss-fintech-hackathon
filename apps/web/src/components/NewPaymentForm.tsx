import { useState } from "react";
import type { PaymentIntent } from "@treasury/shared";

interface Props {
  onSubmit: (intent: PaymentIntent) => void;
  disabled: boolean;
}

const TREASURY = "rTREASURY00000000000000000000000000";

const PRESETS: Array<{ label: string; intent: PaymentIntent }> = [
  {
    label: "$500 vendor invoice (auto-settles)",
    intent: { from: TREASURY, to: "rVENDOR0000000000000000000000000000", amount: 500, currency: "USD", reference: "Invoice #1042" },
  },
  {
    label: "$50,000 invoice (needs approval)",
    intent: { from: TREASURY, to: "rSUPPLIER000000000000000000000000000", amount: 50000, currency: "USD", reference: "Invoice #1043" },
  },
];

export function NewPaymentForm({ onSubmit, disabled }: Props) {
  const [reference, setReference] = useState("");

  return (
    <section className="card">
      <h2>New payment</h2>
      <div className="presets">
        {PRESETS.map((preset) => (
          <button key={preset.label} disabled={disabled} onClick={() => onSubmit(preset.intent)}>
            {preset.label}
          </button>
        ))}
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!reference) return;
          onSubmit({
            from: TREASURY,
            to: "rCUSTOM0000000000000000000000000000",
            amount: 5000,
            currency: "USD",
            reference,
          });
          setReference("");
        }}
      >
        <input
          placeholder="Custom $5,000 payment reference…"
          value={reference}
          onChange={(event) => setReference(event.target.value)}
          disabled={disabled}
        />
        <button type="submit" disabled={disabled || !reference}>
          Send
        </button>
      </form>
    </section>
  );
}
