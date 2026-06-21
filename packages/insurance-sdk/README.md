# @treasury/insurance-sdk

A typed client for the agent-default insurance protocol. Quote and bind are
internal deterministic steps in payment processing; callers may mandate cover
and insurers may monitor or settle verified claims:

```ts
import { createInsuranceProtocol } from "@treasury/insurance-sdk";

const insurance = createInsuranceProtocol({ baseUrl: "http://localhost:8000" });

// ── Counterparty: mandate cover on a payment (pure) ──────────────────────────
const intent = insurance.merchant.requireCover(paymentIntent, { aboveUsd: 10000 });

// ── Insurer: settle a claim on a covered default ─────────────────────────────
const payout = await insurance.insurer.settleClaim({
  jobId: "job-1", agentAddress: "rAGENT…", merchant: "rMERCHANT…",
  line: "merchant_default", loss: "20000", collateral: "2000",
});

// ── Read models ──────────────────────────────────────────────────────────────
await insurance.insurer.pool();          // operator first-loss capital + flows
```

## Parties → methods

| Party | Client | Methods |
|---|---|---|
| Counterparty | `insurance.merchant` | `requireCover` (pure) |
| Insurer (Pool) | `insurance.insurer` | `settleClaim`, `pool`, `premiums`, `payouts` |

Every settlement or claim returns a `guardrailTrail`
(`GuardrailResult[]`) recording the compliance checks (G1 KYA, G2 sanctions,
decide(PAYOUT), collusion). Non-2xx responses throw `InsuranceProtocolError`
with the HTTP status and server detail.

See [`docs/insurance-protocol.md`](../../docs/insurance-protocol.md) for the full
party model, gates, and sequence diagrams.
