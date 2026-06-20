# @treasury/insurance-sdk

A typed, **multi-party** client for the agent-default insurance protocol. One
client per party so integrations read like the protocol:

```ts
import { createInsuranceProtocol } from "@treasury/insurance-sdk";

const insurance = createInsuranceProtocol({ baseUrl: "http://localhost:8000" });

// ── Capital Provider (LP): seed the first-loss pool ──────────────────────────
await insurance.lp.depositCapital({ lpAddress: "rLP…", amount: "50000" });

// ── Agent: price and bind cover for a job ────────────────────────────────────
const quote = await insurance.agent.quoteCover({
  agentAddress: "rAGENT…",
  amount: "20000",
  scoreBand: "STANDARD",
  activeLines: ["merchant_default", "mandate_breach"],
});
if (quote.decision === "OFFER") {
  const premium = await insurance.agent.bindCover({
    agentAddress: "rAGENT…", jobId: "job-1", amount: "20000", scoreBand: "STANDARD",
  });
  console.log(premium.txHash, premium.guardrailTrail); // on-ledger + compliance trail
}

// ── Counterparty: mandate cover on a payment (pure) ──────────────────────────
const intent = insurance.merchant.requireCover(paymentIntent, { aboveUsd: 10000 });

// ── Insurer: settle a claim on a covered default ─────────────────────────────
const payout = await insurance.insurer.settleClaim({
  jobId: "job-1", agentAddress: "rAGENT…", merchant: "rMERCHANT…",
  line: "merchant_default", loss: "20000", collateral: "2000",
});

// ── Read models ──────────────────────────────────────────────────────────────
await insurance.insurer.pool();          // PoolStatus (first-loss, LP capital, flows)
await insurance.agent.getRisk("rAGENT…"); // AgentRiskState (PD, credibility)
```

## Parties → methods

| Party | Client | Methods |
|---|---|---|
| Agent | `insurance.agent` | `quoteCover`, `bindCover`, `getRisk` |
| Counterparty | `insurance.merchant` | `requireCover` (pure) |
| Capital Provider (LP) | `insurance.lp` | `depositCapital`, `withdrawCapital`, `positions` |
| Insurer (Pool) | `insurance.insurer` | `settleClaim`, `pool`, `premiums`, `payouts` |

Every settlement / claim / capital call returns a `guardrailTrail`
(`GuardrailResult[]`) recording the compliance checks (G1 KYA, G2 sanctions,
decide(PAYOUT), collusion). Non-2xx responses throw `InsuranceProtocolError`
with the HTTP status and server detail.

See [`docs/insurance-protocol.md`](../../docs/insurance-protocol.md) for the full
party model, gates, and sequence diagrams.
