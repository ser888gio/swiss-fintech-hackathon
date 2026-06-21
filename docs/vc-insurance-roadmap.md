# Agent-Default Insurance — VC Roadmap & Business Case

This document backs the standalone-protocol pitch. It is authoritative for the
business model and roadmap; technical architecture lives in
[`insurance-protocol.md`](./insurance-protocol.md) and
[`insurance-engine-architecture.md`](./insurance-engine-architecture.md).

---

## 1. The thesis in one paragraph

Every autonomous agent that moves money creates residual risk: FX slippage the
oracle missed, an AML vendor that was 12 hours stale, a Firefly key that was
lost. These risks are **not eliminable by code** — they are the tail that remains
*after* deterministic guardrails enforce policy. They are also **measurable**:
every payment writes a full decision trail (AML score, guardrail results, rule
fired, tx hash) to Postgres and anchors a receipt hash in the XRPL memo. That
means every claim is *cryptographically verifiable*, not subject to adjudication.
That is what makes this underwritable at institutional scale.

> *"We do not insure the AI's judgment. We insure the residual risk that remains
> after deterministic code enforces policy — and every claim is verified
> on-chain, not argued in court."*

---

## 2. Product: three cover packages

| Package | Lines covered | Who buys it | Annual premium (est.) |
|---|---|---|---|
| **Essential** | `merchant_default` | SME treasury, first-time agentic payments | ~0.5–1% of notional |
| **Standard** | `merchant_default` + `fx_slippage` + `mandate_breach` | Mid-market CFO, multi-currency corridors | ~1–2% of notional |
| **Full-Stack** | All five lines incl. `principal_score` + `lender_credit` | Enterprise / bank treasury desk | ~2–3% of notional |

Lines defined in `apps/api/app/insurance/tables.py`:

| Line | Peril | Claim trigger | Max payout |
|---|---|---|---|
| `merchant_default` | Agent pays, goods never delivered | Counterparty files claim + collusion check | $100k |
| `fx_slippage` | Delivered < intended beyond tolerance | **Parametric** — on-ledger `delivered_amount` vs `route_quote`; no dispute | $10k |
| `mandate_breach` | Wrong payee / overspend / out-of-policy | Guardrail trail shows G4/G6 fired | $100k |
| `principal_score` | Default would burn Principal reputation | Pool absorbs; ScoreBand preserved | $25k |
| `lender_credit` | Agent doesn't repay working capital | Lender files; collateral slashed first | $250k |

`fx_slippage` is the pitch standout: **payout is automatic and on-chain-provable**.
No discretion, no committee, no 3-week wait. The agent intended to deliver 1,000
RLUSD; the ledger says 987 arrived; the pool pays 13. Done.

---

## 3. Why we win: the embedded-insurance edge

Standalone insurtech loses on attach rate and churn. Cover Genius (embedded
travel/e-commerce insurance, 40+ enterprise partners) demonstrated
**6–7× higher attach rates** vs. standalone offers when coverage binds inside the
checkout — the equivalent here is `coverRequired: true` on a payment intent.

Our cover binds *inside* the payment gate — the orchestrator auto-quotes and
auto-binds before settling `coverRequired` payments. No separate purchase
decision for the agent or the treasury team. Churn is structurally near-zero
because the policy is attached to the agent's spending policy, not a manually
renewed subscription.

Comparison:

| | Us | Nexus Mutual | Lemonade |
|---|---|---|---|
| Attach mechanism | Embedded in tx gate | Standalone DAO vote | Standalone app |
| Claim trigger | Parametric (on-chain) / guardrail trail | Discretionary DAO vote (1–3 wks) | Discretionary AI review |
| Churn | Near-zero (mandate) | High (token price volatility) | ~15–20%+ |
| Loss ratio | Target ~55–65% | Not public | ~67% gross |
| Reinsurance | LP first-loss pool | NXM stake socialization | 75% ceded to reinsurers |

Lemonade cedes 75% of premiums to reinsurers to offload tail risk. Our LP
first-loss pool is the on-chain equivalent — LPs earn pro-rata premium income in
exchange for being the first-loss tranche. This is a better structure for LPs
than a reinsurance commission because the capital earns yield directly on XRPL
(XLS-65 vault) rather than sitting in a legacy silo.

---

## 4. Revenue model

**Primary:** retained spread on premiums.
- Pool collects premium; LP capital absorbs losses; operator keeps a spread.
- At a conservative 5% retained spread on gross written premium (GWP):
  - $200M GWP pool → $10M retained ARR.
  - $1B GWP pool → $50M retained ARR (at scale, with third-party agent networks).

**Secondary:** LP capital management fee.
- Fee on LP capital deployed (analogous to fund management fee).
- Conservative: 0.5% on AUM. At $50M LP pool → $250k/yr. Scales linearly.

**Unit economics sanity check (illustrative, not projected):**
- Average notional per covered payment: $5,000
- Premium rate (Standard package): 1.5% = $75 premium
- Retained spread (5% of premium): $3.75 per payment
- At 100,000 covered payments/year: $375k retained
- At 1M covered payments/year (50 enterprise clients × 20k payments each): $3.75M retained
- Path to $10M retained ARR: ~2.7M covered payments/year or higher premium rates

**External benchmarks used above:** Premium rates inferred from actuarial first
principles (PD × LGD × load); LGDs from SME credit proxy data. Lemonade loss
ratio sourced (Q2 2025 ~67%). Cover Genius attach-rate uplift sourced. Nexus
Mutual TVL sourced (~$109M). Sardine/Alloy/Unit21 per-request ACVs are
*not public* — not cited.

---

## 5. TAM sizing

| Layer | Source / anchor | Estimate |
|---|---|---|
| Cross-border payment volume | BIS 2026 | ~$237B/yr |
| TMS software market | Grand View Research | $6.96B (2025) → $10.76B (2033) |
| AI-in-insurance TAM | Various (35.7% CAGR) | $154B by 2034 |
| **Agent-payment insurance premium pool** | 0.25–0.5% attach on cross-border B2B | **$200M–$1B/yr** |

SOM: capture 1–5% of the $200M floor = **$2–10M premium pool in year 3**, at 5%
retained spread = **$100k–$500k retained ARR** from a standing start. The
**$10M retained ARR milestone** requires either scale (2.7M payments) or premium
compression absorption as volume grows, consistent with SaaS unit economics.

---

## 6. Product roadmap

### Now (shipped in this repo)
- Actuarial pricing engine (`PD × LGD × load × EAD`, per-agent Beta posterior)
- Three cover packages: Essential / Standard / Full-Stack
- Parametric `fx_slippage` line (auto-triggered from on-ledger facts)
- Per-line claim payout with full G1–G7 guardrail trail
- First-loss LP capital pool, XLS-65 vault settlement, Ed25519 audit chain
- `@treasury/insurance-sdk` for third-party integrators

### Near-term (next 60 days)
- **MPT-tokenized LP shares (XLS-33):** on-ledger LP share tokens; enables
  secondary market for LP positions and junior/senior tranche subordination.
- **Agent onboarding flow:** third-party agent networks (x402 agents, Skyfire,
  Coinbase AgentKit) integrate via SDK; KYA (XLS-70 Credentials) gate.
- **Claim portal UI:** merchant/lender files claim through a UI; guardrail trail
  and on-chain evidence displayed inline.

### Medium-term (3–6 months)
- **Junior/senior tranches:** LP capital split into senior (lower yield, priority
  recovery) and junior (higher yield, first loss). Institutional LP onboarding.
- **Reinsurance backstop:** pool cedes catastrophic tail to a traditional
  reinsurer or a DeFi backstop pool (Nexus Mutual, Unslashed).
- **Per-party signing:** Crossmark/GemWallet per market party; each LP, agent,
  and merchant signs its own transactions (today the Operator wallet stands in).
- **Experience-rating API:** third-party risk data providers enrich the agent
  posterior beyond the on-chain history (credit bureaus, Sardine, Alloy).

### Long-term (6–18 months)
- **Mainnet deployment:** production swap of testnet for XRPL Mainnet; RLUSD as
  the settlement asset; real compliance screening providers.
- **Underwriting marketplace:** any agent platform lists agents; LPs underwrite
  specific score bands or sectors; premium is market-cleared.
- **Regulatory sandbox engagement:** Swiss FINMA sandbox or MAS sandbox for the
  insurance layer; compliant reserve ratio reporting.

---

## 7. Why XRPL and why now

- **TokenEscrow (XLS-85)** is live on Mainnet (Feb 2026): large-payment escrow
  is real on-chain, not a mock. The Firefly veto is not a UI button — it unlocks
  a live escrow.
- **RLUSD** is the settlement asset: stable, composable, available on
  Testnet/Mainnet. Premiums and payouts denominated in RLUSD → no FX exposure
  on the insurance pool itself.
- **XLS-65 Single Asset Vault**: the first-loss pool is an on-ledger vault, not
  an off-chain custody account. LP capital is on-chain, auditable, composable.
- **The agent payment wave is 2025–2027.** Skyfire, Coinbase AgentKit, x402,
  Visa Intelligent Commerce, and OpenWallet are all shipping agent payment rails
  now. Insurance is the missing layer. First-mover advantage is highest before
  a standards-body defines the spec.
