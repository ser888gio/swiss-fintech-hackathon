# Insurance Pricing & Risk Engine — Architecture & Operations (ARS Pillar 3)

This document explains how the agent-default insurance engine works, the design
decisions behind it, the changes shipped on `feat/insurance-pricing-risk-engine`,
and the path to production. It complements the product spec in
[`insurance-pricing-risk-engine.md`](./insurance-pricing-risk-engine.md).

---

## 1. What it is

A **dynamic premium engine** that prices insurance against an autonomous agent
defaulting on a payment, and pays claims when a default happens. It is the
insurance pillar of the Agentic Risk Standard (ARS), sitting beside the existing
pillars (payments, trade finance, delegation, x402).

The engine is **hybrid** by design:

- a **statistical core** *learns* how risky an agent is, on this kind of
  transaction, lately; and
- a **deterministic envelope** turns that estimate into a bounded, loaded,
  signed premium that the rest of the system can trust.

The split is the whole point: the model can change or be retrained without
changing the contract. Every quote is reproducible from its inputs, and every
payout is gated and waterfalled — the same determinism discipline as the policy
kernel.

---

## 2. Architecture at a glance

```
        ┌──────────────────────────────────────────────────────────────┐
 agent  │  STATISTICAL CORE   (pure, app/insurance/risk.py + tables.py) │
outcome │  • agent default posterior  Beta(α,β)  ← seeded from ScoreBand │
 ─────▶ │  • relative-risk table  RR(category,tenor,counterparty,novelty)│──▶ PD, credibility Z
        │  • context adjustments (amount, velocity, concentration)       │
        └──────────────────────────────────────────────────────────────┘
                                   │  PD is an *input*, never the final price
                                   ▼
        ┌──────────────────────────────────────────────────────────────┐
 quote  │  DETERMINISTIC ENVELOPE  (pure, app/insurance/engine.py)       │
request │  eligibility → PP per line (PD·LGD·EAD) → loadings → floor/cap │──▶ PremiumQuote
 ─────▶ │  → solvency gate → band-round → receipt hash                   │   OFFER / REVIEW / DECLINE
        └──────────────────────────────────────────────────────────────┘
                                   │  OFFER
                                   ▼
        ┌──────────────────────────────────────────────────────────────┐
 bind / │  SETTLEMENT LAYER  (async, app/tools/insurance.py)            │
 claim  │  • bind     → premium settles into the pool (on-ledger)       │──▶ XRPL tx + explorer link
 ─────▶ │  • claim    → waterfall: collateral → first-loss pool draw    │
        │  • reprice  → default updates the posterior (price moves up)   │
        └──────────────────────────────────────────────────────────────┘
```

The two pure modules have **no I/O** and are unit-tested like `app/policy/`. The
settlement layer is the only part that touches the ledger, and it reuses the same
audit log and explorer helpers as the other ARS tools.

---

## 3. How it works, end to end

### 3.1 Pricing (`price()`, pure)

1. **PD** — `pd_txn()` blends the agent's Beta posterior mean with a
   portfolio-calibrated relative-risk multiplier and fast context signals, then
   clamps to `[PD_MIN, PD_MAX]`.
2. **Credibility `Z`** — `0` when the agent has no track record (all band prior),
   rising to `1` as its own experience accumulates.
3. **Loadings** — `load = 1 + λ_expense + λ_capital + λ_risk·(1 − Z)`. The risk
   margin is **largest when the estimate is least credible** and shrinks as data
   arrives, so cold-start premiums are conservative automatically.
4. **Per line** — premium is `max(FLOOR, PD·LGD·EAD·load)` for each active cover
   line (merchant default, lender credit, principal score, mandate breach),
   summed and bounded by a cap, then **band-rounded**.
5. **Solvency gate** — if the exposure needs more capital than the pool holds,
   the quote is `REVIEW` instead of `OFFER`.
6. **Receipt** — a canonical SHA-256 of the inputs/outputs, so a quote is fully
   auditable and reproducible.

### 3.2 Binding (`bind()`, async)

Re-quotes server-side (never trusts a client price). Only an `OFFER` binds. The
premium is settled **on-ledger** and an `InsurancePremiumRecord` is written with
the real tx hash + explorer link. The pool's first-loss capital grows by the
premium.

### 3.3 Claim & payout (`settle_claim()`, async)

On a covered default the loss is absorbed in a fixed order (spec §8):

```
recovery   = agent collateral
shortfall  = max(0, loss − recovery)
payout     = min(per-line limit, recovery_rate · shortfall)
pool_drawn = min(payout, pool first-loss)        ← drawn on-ledger
```

The payout is gated by `policy.engine.evaluate()` (limit/AML) **plus a collusion
guard** (repeated agent↔merchant payouts are refused) before any capital moves.
Then the agent's posterior takes a **default update**, exposure-weighted — so the
price moves up for every future quote. The principal's reputation is preserved
(`reputation_mpt_protected`), because the pool, not the principal, ate the loss.

### 3.4 Cover-requirement gate (orchestrator integration, spec §3)

A counterparty can **mandate** cover on a payment (`cover_required`, optionally
only above an amount). The payment orchestrator checks this after the policy
decision and, when required, **auto-binds** a premium before settling. It is
default-off, so the existing payment path is unchanged when no cover is required.

---

## 4. On-ledger settlement — two modes

The pool first-loss capital can settle two ways, selected by `INSURANCE_USE_VAULT`:

| Mode | `INSURANCE_USE_VAULT` | Premium | Payout | Networks | Explorer |
|---|---|---|---|---|---|
| **Payment** (default) | `false` | token `Payment` → pool account | token `Payment` → merchant | any (Testnet/Devnet/Mainnet) | yes |
| **Vault (XLS-65)** | `true` | `VaultDeposit` | `VaultWithdraw` | Devnet (amendment-gated) | yes |

Payment mode is the default because it works on **any** network with a standard
explorer link and needs no issued-token trust lines. Vault mode demonstrates a
genuine on-ledger first-loss pool via the XLS-65 Single Asset Vault (Devnet).

Both modes submit real transactions; use a funded Testnet or Devnet wallet.

---

## 5. Code map

**Pure core (no I/O, unit-tested):**
- `apps/api/app/insurance/tables.py` — calibration tables (band priors, RR
  multipliers, loadings, bounds, per-line LGD/floor/limit/recovery).
- `apps/api/app/insurance/risk.py` — `AgentRisk` Beta posterior, `from_band`,
  `credibility`, `pd_txn`, `update` (recency decay + exposure weighting).
- `apps/api/app/insurance/engine.py` — `price()` envelope, `cover_requirement`,
  solvency gate, receipt hash. Returns a Pydantic `PremiumQuote`.

**Settlement & integration (async I/O):**
- `apps/api/app/tools/insurance.py` — `quote` / `bind` / `settle_claim` /
  `record_outcome`, network-adaptive settlement, audit, persistence.
- `apps/api/app/agents/orchestrator.py` — the cover-requirement gate.
- `apps/api/app/routes/treasury.py` — `/treasury/insurance/*` endpoints.

**Contracts & persistence:**
- `apps/api/app/schemas.py` — `PremiumQuote`, `InsuranceQuoteRequest`,
  `BindRequest`, `ClaimRequest`, `AgentRiskState`, `PoolStatus`, records.
- `apps/api/app/models.py` — `AgentRiskRecord` + insurance record tables.
- `packages/shared/src/types.ts` — mirrored TypeScript types.

**Frontend:**
- `apps/web/src/pages/ARSPage.tsx` — the **Pricing & Risk Engine** panel.

**Endpoints** (all under `/treasury/insurance`): `POST /quote`, `POST /bind`,
`GET /premiums`, `POST /claim`, `GET /payouts`, `GET /pool`,
`GET /agents/{address}/risk`.

---

## 6. Changes shipped on this branch

1. **New insurance engine** — the pure core (`tables`/`risk`/`engine`), the
   async settlement tool, schemas, the `AgentRiskRecord` model, routes, and the
   orchestrator cover-gate.
2. **XLS-65 vault wiring** — premium/payout can settle as real `VaultDeposit`/
   `VaultWithdraw` (Devnet), with the vault balance surfaced in `PoolStatus`.
3. **Network-adaptive settlement** — `INSURANCE_USE_VAULT` toggles vault vs
   direct-Payment settlement, so the engine produces real explorer links on
   Testnet/Devnet without issued-token plumbing.
4. **Network-aware explorer links** — `xrpl_client` now derives the explorer
   (devnet / testnet / mainnet) from the configured endpoint, fixing a latent
   bug where core tools always linked to `testnet.xrpl.org`.
5. **XRP-only transactions** — the payment form and the autonomous-agent goal
   form are locked to XRP (no USD/EUR), removing any FX/wrong-currency failure
   mode; settlement is native `XRP->XRP` with no conversion.
6. **Frontend panel** — quote → bind → simulate-claim with live links, plus pool
   capacity and the agent's repricing posterior.
7. **Tests** — 24 new unit/integration tests; full suite green (207).

Verified live on **Devnet** with real transactions: payment, premium bind, claim
payout, and credential issuance, all linking to `devnet.xrpl.org`.

---

## 7. Configuration (`.env`)

| Variable | Meaning |
|---|---|
| `XRPL_ENDPOINT` | network endpoint (drives explorer + network label) |
| `TREASURY_WALLET_SEED` | funded agent/treasury account |
| `TOKEN_CURRENCY` | settlement asset — **XRP** for the FX-free demo |
| `TESTNET_SETTLEMENT_SCALE` | scales only the on-ledger amount to a fundable size |
| `INSURANCE_ENABLED` | master switch for the pillar |
| `INSURANCE_USE_VAULT` | `false` = Payment mode (any net); `true` = XLS-65 vault (Devnet) |
| `INSURANCE_VAULT_ADDRESS` | pool account (premium payee / payout source) |
| `INSURANCE_POOL_FIRST_LOSS_USD` | operator-funded first-loss capital |
| `INSURANCE_PREMIUM_CAP_USD` | hard cap on a single premium |
| `INSURANCE_COVER_REQUIRED_ABOVE_USD` | global automatic-cover amount threshold |
| `INSURANCE_AUTO_NEW_CPTY` | globally insure new counterparties |
| `INSURANCE_AUTO_UNVERIFIED_CPTY` | globally insure unverified counterparties |
| `INSURANCE_DEFAULT_PACKAGE` | global Essential / Standard / Full-Stack package |

The rich calibration tables (band priors, RR multipliers, per-line params) live
in `app/insurance/tables.py` and are overridden at the boundary by config.

---

## 8. Run & test

```bash
# API (from apps/api)
uvicorn app.main:app --port 8000        # /docs, /health

# Web (from repo root)
npm run dev:web                         # http://localhost:5173 → Agent tab → /ars

# Smoke test (fund + send)
python scripts/smoke_xrpl.py fund       # faucet wallet (Testnet/Devnet)
```

Browser flow: **Agent → Pricing & Risk Engine →** Get quote → Bind premium →
Simulate default → claim. Each action logs a live explorer link.

---

## 9. Next steps

**Productionization**
- **Durable store** — set `DATABASE_URL` (Postgres) so pool accounting and the
  agent posterior survive restarts; today the in-memory store resets per process.
- **Mainnet path** — point endpoints at `wss://xrplcluster.com`; explorer links
  already resolve to `livenet.xrpl.org`. Set `TESTNET_SETTLEMENT_SCALE=1.0`.
- **Issued-asset pool** — for RLUSD settlement, add the treasury trust line +
  balance; for XLS-65 vault mode on mainnet, wait for amendment activation.
- **Collateral track** — wire a real agent-collateral escrow so `slash` is an
  on-ledger action, not an accounting entry.

**Risk model**
- **Champion/challenger calibration** — recalibrate `RR_*` tables and band priors
  from realized outcomes; backtest the loop on the Arena/sandbox before exposing
  real capital.
- **Per-bucket credibility** — graduate from one agent posterior × RR table to a
  richer hierarchical model as data accrues.
- **decide(PAYOUT) hardening** — promote the payout gate from `policy.evaluate` +
  collusion heuristic to a full ARS `ConstraintEngine` (G1–G7) implementation.

**Capital structure**
- **LP tranches** — model junior/senior subordination and first-loss capital as
  distinct on-ledger positions (the waterfall already names them).
- **Subrogation** — pursue recovery from a defaulting agent back to the tranche
  that bore the loss.

**Product**
- **Reinsurance / capacity** — cap aggregate exposure and route overflow.
- **Dashboards** — loss-ratio, premium-adequacy, and pool-solvency views for LPs.
