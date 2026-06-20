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
| **Agent** | An autonomous sub-agent that transacts | Requests a quote, **binds** cover (pays the premium) | Active cover for a job; a default-propensity posterior that reprices it |
| **Counterparty** | Merchant or lender on the other side | May **mandate** cover as a condition; is the **beneficiary** of a payout | Payout on a covered default (net of recovery) |
| **Capital Provider (LP)** | Liquidity provider | **Deposits** first-loss capital, **withdraws** it; earns premium | A pool **share**; pro-rata premium income; absorbs losses first |
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
| **Agent binds cover** | **G1 KYA** (agent holds an accepted KYC credential) · **G2 sanctions** (agent not listed) | G2 hard-blocks; G1 is enforced when `INSURANCE_ENFORCE_KYA=true`, else surfaced advisory |
| **Counterparty mandates cover** | **G2 sanctions** (counterparty screened) | Surfaced on the quote/bind trail |
| **LP deposits capital** | **G1 KYA** · **G2 sanctions** (LP screened) | G2 hard-blocks a sanctioned LP |
| **Insurer settles claim** | **decide(PAYOUT)**: policy limit + AML · **collusion guard** (repeat agent↔counterparty payouts) | Hard gate — refuses before any draw |

Each action returns a **guardrail trail** (`GuardrailResult[]`) recording exactly
which checks ran and their outcome, so every decision is auditable.

---

## 3. Protocol lifecycle

### 3.1 Happy path (covered job completes cleanly)

```
 LP            Agent          Counterparty        Insurer (Pool)         XRPL
 │ depositCapital ─────────────────────────────────▶│  G1+G2 → Payment→pool   ──▶ tx
 │                │ requireCover(txn) ───────────────▶│                          (cover_required)
 │                │ quoteCover ──────────────────────▶│  price()  → PremiumQuote (OFFER)
 │                │ bindCover ───────────────────────▶│  G1+G2 → premium settles ──▶ tx
 │                │ …job settles (payment)…           │  posterior nudges DOWN
 │ earns premium ◀────────────── pool grows ──────────│
```

### 3.2 Default path (covered job defaults)

```
 Agent          Counterparty        Insurer (Pool)              LP            XRPL
   │ (defaults)        │ fileClaim ──▶│ decide(PAYOUT) + collusion gate
   │                   │              │ waterfall:
   │                   │              │   collateral recovery
   │                   │◀── payout ───│   first-loss pool draw ───────────────────▶ tx
   │ posterior ▲ (reprice)            │   principal score PRESERVED
   │                   │              │   LP capital absorbs the loss ◀── share ▼ ──│
```

The price moves with the agent because the posterior moves with the agent; the
principal's `ScoreBand` survives because the **pool**, not the principal, ate the
loss.

---

## 4. Data contracts (per interaction)

All money is a decimal **string**; all responses carry a `guardrailTrail`.

| Interaction | Request | Response |
|---|---|---|
| `quoteCover` | `InsuranceQuoteRequest { agentAddress, amount, scoreBand, activeLines[], txn }` | `PremiumQuote { decision, premium, lines, pd, credibility, receiptHash }` |
| `bindCover` | `BindRequest { agentAddress, jobId, amount, … }` | `InsurancePremiumRecord { premiumAmount, txHash, explorerUrl, guardrailTrail }` |
| `requireCover` | a `PaymentIntent` with `coverRequired` / `coverRequiredAboveUsd` | the gate auto-binds at settle time |
| `depositCapital` | `CapitalDepositRequest { lpAddress, amount }` | `LpPosition { capital, sharePct, txHash, explorerUrl, guardrailTrail }` |
| `withdrawCapital` | `CapitalWithdrawRequest { lpAddress, amount }` | `LpPosition { … }` |
| `fileClaim` / `settleClaim` | `ClaimRequest { jobId, agentAddress, merchant, line, loss, collateral }` | `InsurancePayoutRecord { collateralSlashed, poolDrawn, totalPaid, txHash, explorerUrl, guardrailTrail }` |

Read models: `GET /pool` → `PoolStatus`, `GET /agents/{a}/risk` → `AgentRiskState`,
`GET /capital` → `LpPosition[]`.

---

## 5. Endpoint ⇄ SDK ⇄ party map

| Party | SDK method | HTTP |
|---|---|---|
| Agent | `agent.quoteCover()` | `POST /treasury/insurance/quote` |
| Agent | `agent.bindCover()` | `POST /treasury/insurance/bind` |
| Agent | `agent.getRisk(addr)` | `GET /treasury/insurance/agents/{addr}/risk` |
| Counterparty | `merchant.requireCover(intent)` | builds the `coverRequired` payment intent |
| Capital Provider | `lp.depositCapital()` / `lp.withdrawCapital()` / `lp.positions()` | `POST/GET /treasury/insurance/capital*` |
| Insurer | `insurer.settleClaim()` | `POST /treasury/insurance/claim` |
| Insurer | `insurer.pool()` / `insurer.premiums()` / `insurer.payouts()` | `GET /treasury/insurance/{pool,premiums,payouts}` |

---

## 6. Invariants

1. **Deterministic boundary** — pricing, gating and the waterfall are pure/code;
   the LLM only narrates.
2. **Reproducible quotes** — every quote carries a `receiptHash` over its inputs.
3. **Capital is first-loss** — LP capital absorbs losses before the principal's
   reputation; the principal's `ScoreBand` is preserved on an insured default.
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
