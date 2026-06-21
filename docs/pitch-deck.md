# Blaiko — Pitch Deck Content
## SwissHacks 2026 · Ripple: Future of Finance on XRPL

---

## Slide 1 — Title

**Blaiko**
*The first insurance protocol for AI agents making financial decisions*

Built on XRPL · Powered by RLUSD · Protected by hardware

*SwissHacks 2026 — Ripple: Future of Finance on XRPL*

---

## Slide 2 — Problem Statement

**AI agents are moving money. Nobody's insuring the mistakes.**

- $67.4B lost to enterprise AI hallucinations globally in 2024
- $2.3B in avoidable finance losses from AI errors in Q1 2026 alone
- Average cost per affected company: **$4.4M per incident**
- Agentic AI in financial services: **$7.78B in 2026, growing to $43.5B by 2031**
- Finance teams using AI agents jumped from 7% → 44% in just 14 months

**The insurance industry's response?** Berkshire, Chubb, and Travelers are *excluding* AI liability from standard policies. The gap is wide open.

Three failure modes nobody is covering today:
1. **Hallucinated amounts** — agent sends $500 when instructed $5,000
2. **Wrong recipient** — agent fabricates or misreads a destination address
3. **Non-delivery** — payment confirmed, goods never arrived

---

## Slide 3 — What We Built (Business Perspective)

**An autonomous treasury agent that settles cross-border payments in seconds — and insures its own mistakes on-chain.**

Two products in one:

| Feature | What it means for a CFO |
|---|---|
| Autonomous payment routing | $500 vendor invoice settled in 4 seconds, no human in the loop |
| Hardware veto | No one *can* bypass approval for payments over $10K — physically impossible |
| Parametric cover policy | Treasury buys insurance against agent errors, priced by risk score |
| Automatic claim trigger | Divergence detected → payout in seconds, no claims adjuster |

**Savings vs. traditional cross-border wire transfers:**
- Wire transfer: 2–5 days, $25–50 fee, 1–3% FX spread
- Blaiko: ~4 seconds, near-zero fee, RLUSD eliminates FX spread
- For a $50M/year treasury: **estimated $500K–1.5M in annual savings**

**Competitive position:** Only one competitor exists at prototype stage (Klaimee, YC 2026). They cover general AI deployment errors. We cover the specific financial transaction layer, on-chain, parametrically, on XRPL.

---

## Slide 4 — How It Works (Business UI)

**Three flows. One dashboard.**

**Flow 1 — Small payment (auto-settle):**
> Invoice arrives → agent routes via XRPL pathfinding, screens for sanctions, settles in RLUSD → explorer link in ~4 seconds → audit log written in plain English

**Flow 2 — Large payment (hardware veto):**
> $50K invoice arrives → agent flags as over-threshold → funds locked on-chain via TokenEscrow → Firefly device lights up with payment details → operator presses physical button → secp256k1 signature verified by backend → EscrowFinish submitted → settled

**Flow 3 — Cover claim (parametric payout):**
> Agent sends wrong amount → reconciliation engine compares expected vs. executed → cover pool pays shortfall directly to merchant → LLM narrates what happened in plain English, no adjuster involved

The dashboard shows: invoice queue · live agent narration · pending approval queue · on-chain transaction history · cover policy status and remaining capacity.

---

## Slide 5 — What the Product Is

**Three-layer institutional infrastructure:**

```
┌─────────────────────────────────────────────┐
│  LAYER 3: INSURANCE                         │
│  Parametric cover policies priced per agent │
│  · Hallucination line (wrong amount/address)│
│  · Non-delivery line                        │
│  · Automatic trigger, payout in seconds     │
├─────────────────────────────────────────────┤
│  LAYER 2: GOVERNANCE                        │
│  Policy engine (code, not AI)               │
│  · Spending limits enforced deterministically│
│  · Firefly hardware veto for large payments │
│  · Sanctions hard-block (no override)       │
├─────────────────────────────────────────────┤
│  LAYER 1: PAYMENT RAILS                     │
│  XRPL + RLUSD                               │
│  · Settle in seconds, not days              │
│  · TokenEscrow (XLS-85) locks funds on-chain│
│  · KYA Credentials (XLS-70) for agent identity│
└─────────────────────────────────────────────┘
```

**The core invariant:** The LLM orchestrates and narrates. It never decides policy, signs transactions, or approves claims. Those are deterministic code.

XRPL features in use: TokenEscrow (XLS-85) · RLUSD · Credentials/KYA (XLS-70) · pathfinding · Postgres audit trail with tamper-evident receipt hash.

---

## Slide 6 — Why It's the Best Solution on the Market

**Nobody else has this combination:**

| Capability | Blaiko | Traditional insurers | Nexus Mutual / Etherisc | Klaimee (YC 2026) |
|---|:---:|:---:|:---:|:---:|
| Covers AI financial hallucinations | ✅ | ❌ excluded | ❌ not focused | ✅ general only |
| On-chain parametric trigger | ✅ | ❌ | ✅ DeFi only | ❌ |
| Priced per agent, per risk band | ✅ | ❌ | ❌ | ❌ |
| Hardware veto on large payments | ✅ | n/a | n/a | n/a |
| Institutional dashboard + audit | ✅ | n/a | n/a | ❌ |
| Runs on XRPL + RLUSD | ✅ | ❌ | ❌ | ❌ |

**Regulatory tailwind:** EU AI Act enforcement starts August 2026. Organizational liability for AI decisions is mandatory. Our cover policy is the compliance answer legal teams need before they can approve AI in the payment flow.

---

## Slide 7 — The Wow Feature

### "The button that can't be faked."

**Live demo — $50,000 invoice:**

1. Agent routes via XRPL pathfinding — RLUSD quote in <1s
2. Compliance engine scores AML at 12/100 — clears sanctions
3. Policy engine fires: amount > $10K threshold → **escalate**
4. Funds locked on-chain via TokenEscrow — nobody can touch them
5. Firefly device lights up with payment details on screen
6. Operator presses the **physical button**
7. secp256k1 signature travels browser → local bridge → API
8. Backend verifies signature against registered public key
9. EscrowFinish submitted → settled in seconds
10. Open XRPL testnet explorer — both transactions live on-chain

**Then: tamper proof.** Watch what happens when we try to approve a modified amount. The signature fails. Funds stay locked. API returns 403. The signature is cryptographically bound to the exact payment details — it cannot be replayed against a different amount or recipient.

> *"No one, including the agent, can move a large payment without this device in hand."*

---

## Slide 8 — Team

| Name | Role |
|---|---|
| Sergiu Nica | AI Engineer, Work Experience from top european companies - Allianz, Generali |
| Gaspar Palma Astorga | AI Analyst, work experience from Financial/Legal departments Škoda Auto |
| Andrej Betak | Data Engineer, HW Engineer, work experience from developing DE project at Škoda Auto |

---

## Slide 9 — Go-to-Market & Business Model

**Target customer:** Corporate treasury teams at mid-market companies ($50M–$5B revenue) evaluating or already using AI payment automation.

**Revenue streams:**
- **Cover premium** — % of insured amount × risk band × term, priced on-chain, paid in RLUSD
- **SaaS subscription** — treasury dashboard + governance layer
- **Per-agent onboarding fee** — KYA credential issuance and risk scoring

**Path to Mainnet (three config swaps, architecture unchanged):**
1. Testnet endpoint → Mainnet XRPL endpoint
2. Mock RLUSD issuer → real Ripple RLUSD issuer
3. Mock compliance → real sanctions provider (Elliptic, Chainalysis)
4. Local Firefly bridge → HSM/custody signer (adapter interface already abstracted)

**Go-to-market:** Partner with XRPL institutional ecosystem; lead with the EU AI Act compliance angle to legal/risk teams at enterprises already running AI in finance workflows. August 2026 enforcement deadline creates immediate urgency.

---

## Slide 10 — Summary

> **The AI decides nothing about money — code does. The AI explains. And no one, including the agent, can move a large payment without the device in hand.**

- **$67B problem.** One competitor at prototype stage. No one on XRPL.
- **Live on Testnet.** Explorer proof. Deployed on Railway. Not localhost.
- **Three XRPL features:** TokenEscrow (XLS-85) · Credentials (KYA/XLS-70) · RLUSD settlement.
- **First parametric AI agent insurance protocol on a public ledger.**

---
---

# Judge Q&A Prep — Ripple Jury

*Prepared for: Maxime Dienger (Hackathon Lead / Jury) · Whittney Levitt (Director, Ecosystem Growth)*

---

## On the insurance mechanism

**Q: "How does the cover pool stay solvent? Who funds it?"**

The pool is pre-funded — the treasury deposits RLUSD at initialization. Premium income replenishes it over time. The solvency gate in the pricing engine blocks new policy issuance when `cover_cap > free_pool_capacity`, so we cannot over-insure. In production, a reinsurance layer (traditional or DeFi) backs tail risk. Risk is priced per agent using a PD (probability of default) model calibrated to agent transaction history and score band.

**Q: "What stops a treasury from colluding with the merchant to file fake claims?"**

Three controls: (1) a collusion guard blocks a third claim if more than 2 have already fired against the same merchant; (2) claims require the payment to be in `settled` status — you cannot claim on a blocked or pending payment; (3) a sanctions check runs on the merchant address before any payout is authorized.

**Q: "Is 'parametric' the right word if a human can submit the non-delivery trigger?"**

Hallucination claims (wrong amount, wrong recipient) are fully automatic — `reconcile()` is pure deterministic code comparing expected vs. executed. Non-delivery requires an attestation from the merchant or a maturity timer, which is semi-parametric — closer to trade credit insurance. We're transparent about that distinction in the product.

---

## On the hardware veto

**Q: "If the signature isn't an XRPL escrow condition, can't you just submit EscrowFinish directly from the treasury key?"**

Yes — and we're explicit about this in our architecture docs. The current implementation is an application-enforced veto, not a ledger-enforced one. A party with the treasury signing key could construct EscrowFinish after `FinishAfter`. Our public claim is precise: "the governed workflow cannot release without the device," not "the ledger makes release impossible." The ledger-enforced upgrade is crypto-condition escrow (SHA-256 preimage held by Firefly) or XRPL multisig — we've scoped both and know exactly what the blockers are.

**Q: "Why not use XRPL multisig instead?"**

Firefly uses secp256k1 over its own payload serialization, not XRPL's signing format. Multisig would require the Firefly firmware to produce XRPL-valid signatures — a firmware change that's out of scope for 48 hours. Crypto-condition escrow is the cleaner upgrade path and doesn't require any firmware modification.

---

## On XRPL feature usage

**Q: "Why TokenEscrow over standard XRP conditional escrow?"**

We need to lock RLUSD, which is an IOU. Classic XRP escrow only works for XRP. XLS-85 (TokenEscrow) activated on mainnet February 2026 and extends escrow to IOUs and MPTokens, including RLUSD. This is precisely why XRPL is the right platform — no other public ledger has this primitive live on mainnet today.

**Q: "How do you use Credentials? Aren't they just a flag you set?"**

We use Credentials (XLS-70) for Know Your Agent (KYA). Before an agent wallet can auto-settle payments, it must hold an accepted KYC credential issued by our credential issuer wallet. If the credential is absent or expired, the payment escalates regardless of amount. This maps directly to the KYA angle in the challenge brief and gives institutions an auditable identity chain for every autonomous payment.

**Q: "Did you consider XLS-65/66 (Vaults and Lending)?"**

Yes — idle treasury sweeping into a Single Asset Vault for yield is scoped as an optional extension. It's disabled by default because XLS-65/66 are Devnet-only and we prioritized a stable Testnet demo. The integration path is clear: treasury surplus → VaultDeposit → yield accrues in RLUSD → VaultWithdraw when liquidity is needed. One day's work on top of the existing stack once the amendment hits Testnet.

---

## On viability (40% of the score)

**Q: "What's your path to Mainnet? What actually breaks?"**

Nothing architectural breaks. It's three config swaps: (1) testnet → mainnet XRPL WebSocket endpoint, (2) our self-issued mock USD IOU → real Mainnet RLUSD issuer, (3) mock compliance module → real sanctions provider. The only non-trivial change is the Firefly bridge → HSM/custody signer, and the adapter interface already abstracts the device layer so that's a driver swap, not an architecture change.

**Q: "Who is your first paying customer?"**

Mid-market corporate treasury teams already evaluating AI payment automation. They have the pain — manual approval queues, no audit trail, zero recourse if the AI makes an error. The EU AI Act deadline creates urgency: legal teams need to demonstrate organizational liability coverage before they can sign off on autonomous AI in the payment flow. Our cover policy is that answer.

**Q: "How do you price the premium competitively against traditional trade credit insurance?"**

Traditional trade credit: 0.1–0.5% of insured turnover annually, 30–90 day claims process, human adjuster required. Our hallucination line: ~0.2–0.8% of cover cap (risk-banded by agent score), payout in seconds, no adjuster. We're not competing on premium price — we're competing on specificity (covers AI errors traditional policies explicitly exclude), speed (parametric payout vs. months of claims process), and audit trail (every decision is on-chain and tamper-evident).

---

## On the AI/LLM role

**Q: "The LLM narrates — but what if it narrates incorrectly and causes the operator to make a wrong decision?"**

The narration is cosmetic. It explains a decision that has already been made by deterministic code. The policy engine, compliance check, and claim eligibility rules are all pure functions. If the LLM hallucinates in its narration, the worst outcome is a confusing explanation — not a wrong payment. The Postgres audit log records ground truth from the deterministic tools, not from the narration.

**Q: "Why use an LLM at all if all the decisions are deterministic?"**

Institutional operators need to understand *why* a payment was escalated or a claim was triggered, in plain English, without reading JSON logs. The LLM translates deterministic tool outputs — AML score, compliance flags, policy rule fired — into human-readable explanations. It's a UX and audit-communication layer, never a decision layer. The invariant is enforced in code: the LLM output cannot write to any field that changes payment status.

---

*Demo tip: the physical button press and the tamper-proof 403 response are the two strongest moments in the demo. Hit them clearly and pause for the judges to absorb what they just saw.*
