# Agent-Default Insurance — Multi-Party Protocol

This defines the **protocol** the insurance engine implements: the parties, what
each is allowed to do, the compliance gate each must pass, and the end-to-end
message/transaction sequence. It turns the pricing engine
([`insurance-engine-architecture.md`](./insurance-engine-architecture.md)) into a
well-defined, multi-party system that integrators can build against via the
[`@treasury/insurance-sdk`](../packages/insurance-sdk/README.md).

---

## 1. Parties (actor model)

| Party | Who | Does | Holds / receives |
|---|---|---|---|
| **Principal** | The human/org that owns an agent | Delegates a budget; relies on cover to protect its reputation | A portable `ScoreBand` (reputation) — *preserved* when an insured sub-agent defaults |
| **Agent** | An autonomous sub-agent that transacts | Submits payments through deterministic policy | Active cover for a job; a default-propensity posterior that reprices it |
| **Counterparty** | Merchant or lender on the other side | May **mandate** cover as a condition; is the **beneficiary** of a payout | Payout on a covered default (net of recovery) |
| **Insurer (Pool)** | The protocol itself | Prices, binds, gates and pays claims; runs the waterfall | The `InsuranceVault` first-loss capital |
| **Operator** | The deployment running this service | Holds the signing wallet; enforces the deterministic boundary | — |

> The **Operator** is infrastructure, not a market party. In production each
> market party signs its own transactions; in this build the Operator's wallet
> stands in so the full flow is demonstrable end-to-end on one deployment.

---

## 2. Obligations & compliance gate per party

Every party action passes a deterministic gate **before** any capital moves. The
checks reuse the ARS guardrail vocabulary (G1 KYA, G2 sanctions, G4 scope, …) and
the policy kernel; the LLM never decides any of them.

| Action (party) | Gate | Enforcement |
|---|---|---|
| **Payment workflow binds cover** | **G1 KYA** (agent holds an accepted KYC credential) · **G2 sanctions** (agent not listed) | G2 hard-blocks; G1 is enforced when `INSURANCE_ENFORCE_KYA=true`, else surfaced advisory |
| **Counterparty mandates cover** | **G2 sanctions** (counterparty screened) | Surfaced on the quote/bind trail |
| **Insurer settles claim** | **decide(PAYOUT)**: policy limit + AML · **collusion guard** (repeat agent↔counterparty payouts) | Hard gate — refuses before any draw |

Each action returns a **guardrail trail** (`GuardrailResult[]`) recording exactly
which checks ran and their outcome, so every decision is auditable.

---

## 3. Protocol lifecycle

Before pricing, pure code resolves the treasury-wide auto-insure defaults with
the agent's optional override. Cover is required by the first matching rule:
agent opt-out, counterparty mandate, new/unverified counterparty risk, or amount
threshold. The resulting authority is persisted as `coverage.requiredBy`.

### 3.1 Happy path (covered job completes cleanly)

```
 Agent          Payment policy       Insurer (Pool)         XRPL
 │ submit intent ─────▶│ threshold/mandate gate                  │
 │                     │ quote internally ─▶ PremiumQuote        │
 │                     │ bind internally ──▶ premium settles ───▶ tx
 │                     │ settle payment only after binding       │
```

### 3.2 Default path (covered job defaults)

```
 Agent          Counterparty        Insurer (Pool)                            XRPL
   │ (defaults)        │ fileClaim ──▶│ decide(PAYOUT) + collusion gate
   │                   │              │ waterfall:
   │                   │              │   collateral recovery
   │                   │◀── payout ───│   first-loss pool draw ───────────────────▶ tx
   │ posterior ▲ (reprice)            │   principal score PRESERVED
```

The price moves with the agent because the posterior moves with the agent; the
principal's `ScoreBand` survives because the **pool**, not the principal, ate the
loss.

---

## 4. Data contracts (per interaction)

All money is a decimal **string**; all responses carry a `guardrailTrail`.

| Interaction | Request | Response |
|---|---|---|
| internal quote → bind | payment facts + deterministic policy result | persisted `PaymentCoverage { status, requiredBy, quote, premium }` |
| `requireCover` | a `PaymentIntent` with `coverRequired` / `coverRequiredAboveUsd` | the gate auto-binds before settlement |
| `fileClaim` / `settleClaim` | `ClaimRequest { jobId, agentAddress, merchant, line, loss, collateral }` | `InsurancePayoutRecord { collateralSlashed, poolDrawn, totalPaid, txHash, explorerUrl, guardrailTrail }` |

Read models: `GET /pool` → `PoolStatus`, `GET /agents/{a}/risk` → `AgentRiskState`.

---

## 5. Endpoint ⇄ SDK ⇄ party map

| Party | SDK method | HTTP |
|---|---|---|
| Counterparty | `merchant.requireCover(intent)` | builds the `coverRequired` payment intent |
| Insurer | `insurer.settleClaim()` | `POST /treasury/insurance/claim` |
| Insurer | `insurer.pool()` / `insurer.premiums()` / `insurer.payouts()` | `GET /treasury/insurance/{pool,premiums,payouts}` |

---

## 6. Invariants

1. **Deterministic boundary** — pricing, gating and the waterfall are pure/code;
   the LLM only narrates.
2. **Reproducible quotes** — every quote carries a `receiptHash` over its inputs.
3. **Capital is first-loss** — operator-funded pool capital absorbs losses before
   the principal's reputation; the principal's `ScoreBand` is preserved.
4. **Auditable** — every party action returns a guardrail trail and (in real
   mode) an on-ledger transaction with an explorer link.
5. **Solvency-aware** — a quote is `REVIEW` (not `OFFER`) when exposure exceeds
   pool capacity.

---

## 7. Production gaps (intentional, see architecture §9)

- Each market party should sign its own transactions (today the Operator wallet
  stands in for all signers).
- `decide(PAYOUT)` is a policy-kernel + collusion heuristic; the full ARS
  `ConstraintEngine` (G1–G7) is the documented next step.
- LP shares are pro-rata accounting; junior/senior tranche subordination and
  on-ledger share tokens (MPT) are future work.
