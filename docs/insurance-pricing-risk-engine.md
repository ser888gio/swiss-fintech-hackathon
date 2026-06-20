# Pricing & Risk Engine
### Dynamic premium pricing for agent-default insurance — the statistical core inside a deterministic envelope

**Decisions locked (from discovery):**
- **Coverage:** four lines — merchant payment default, lender credit loss, principal score protection, mandate breach / mis-execution.
- **Distribution:** cover is **optional by default**, but a merchant or lender can make it **obligatory** as a condition of the transaction or loan.
- **Pricing:** **hybrid** — a statistical core estimates risk; a deterministic envelope bounds, loads, and signs the quote.

**Plugs into:** `pay_premium` (bind), `decide(PAYMENT)` (cover-requirement gate), `decide(PAYOUT)` (claims), the certified `ScoreBand` (prior), the `InsuranceVault` + first-loss capital + LP tiers (capacity).

---

## 1. Architecture — why hybrid, and where the line sits

```
        ┌──────────────────────────────────────────────────────────────┐
  agent │  STATISTICAL CORE   (off-chain, learns)                       │
 outcome│  • agent default posterior  Beta(α,β)                         │
  ─────▶│  • transaction-type relative-risk table  RR(category,tenor,…) │──▶ PD, credibility
        │  • context adjustments (amount, velocity, concentration)      │
        └──────────────────────────────────────────────────────────────┘
                                   │  PD is an *input*, never the final price
                                   ▼
        ┌──────────────────────────────────────────────────────────────┐
  quote │  DETERMINISTIC ENVELOPE   (auditable, signed — like decide())  │
 request│  eligibility → PP per line (PD·LGD·EAD) → loadings → floor/cap │──▶ Quote
  ─────▶│  → solvency check → band-round → receipt                       │   OFFER / REVIEW / DECLINE
        └──────────────────────────────────────────────────────────────┘
```

The split is the whole point: **the core may change, improve, or be replaced without changing the contract.** The envelope guarantees every premium is bounded, explainable, reproducible, and receipted — the statistical number is wrapped in the same deterministic, signed discipline as the compliance kernel. The core runs off-chain (rich model, frequent recalibration); the envelope is deterministic and anchored on-chain.

---

## 2. The four covered lines

Each line has its own exposure and loss-given-default basis, so the premium is **additive across the active lines**, not one blended number.

| Line | Peril | Exposure (EAD) | Loss-given-default basis | Beneficiary | Moral-hazard sensitivity |
|---|---|---|---|---|---|
| **Merchant default** | agent doesn't pay for delivered goods | transaction amount | shortfall above agent collateral | merchant | medium |
| **Lender credit loss** | agent doesn't repay working capital | outstanding principal + interest | loss after first-loss capital | lender / LP | medium |
| **Principal score protection** | a default would burn the principal's standing | the repricing/credit impact avoided | expected standing loss absorbed | principal | low |
| **Mandate breach / mis-execution** | wrong payee, wrong amount, overspend | the erroneous amount | net of recoverability | merchant / principal | **high** |

Score protection is the odd one: it isn't a cash payout to a third party but a promise that the pool *absorbs the reputational/credit consequence* of an insured default, so the principal's portable `ScoreBand` survives one bad sub-agent. Its premium funds that absorption. Mandate-breach carries the highest moral-hazard weight (an operator could induce it), so it gets the strictest collateral and the heaviest scrutiny in §6/§8.

---

## 3. The cover-requirement mechanism (optional, but mandatable)

Cover is opt-in for the agent, but a counterparty can **require** it — and that requirement is what protects the pool from adverse selection.

- A **merchant or lender attaches a `cover_required` condition** to a transaction or loan (carried in their terms / Permissioned-Domain policy). It can be **conditional**: required only above an amount threshold, for certain categories, or for agents below a score band.
- At the gate, `decide(PAYMENT)` (or loan origination) checks the requirement:

```python
def cover_gate(ctx) -> str:
    req = ctx.counterparty.cover_requirement(ctx.txn)   # NONE | REQUIRED
    if req == "REQUIRED" and not ctx.agent.has_active_cover(ctx.txn):
        return "REVIEW"     # offer to bind cover now, or refuse the transaction
    return "ALLOW"
```

- If required and unbound, the flow offers to **auto-bind** cover (price → `pay_premium` → proceed) or refuses the transaction.

**Why this is the design win:** optional cover alone invites a death spiral (only risky agents insure). Letting counterparties mandate it means every time a cautious merchant or a lender requires cover, the *good* agents transacting with them are pulled into the pool too — broadening the risk base without forcing a blanket mandate. The market sets the floor, not the protocol.

---

## 4. The premium formula

Per line, the pure premium is the expected loss; the final premium adds loadings and is bounded.

```
PP_line     = PD(agent, txn) · LGD_line · EAD_line                     # expected loss
load        = 1 + λ_expense + λ_capital + λ_risk(credibility)          # see note
Premium_line= max( FLOOR_line , PP_line · load )
Premium     = band_round( min( CAP , Σ_line∈active Premium_line ) )
```

The loadings:
- **λ_expense** — operating cost of running the cover.
- **λ_capital** — cost of the capital backing the exposure = required LP return × capital-per-unit-exposure (ties premium to solvency, §8).
- **λ_risk(credibility)** — the uncertainty margin, and the clever term: it is **largest when the PD estimate is least credible** and shrinks as the agent accumulates data: `λ_risk = λ_risk_max · (1 − Z)`. This makes cold-start premiums conservative automatically and relaxes them as evidence arrives — no manual intervention (directly addresses the cold-start problem in §10).

---

## 5. PD estimation — the statistical core

Default probability is built hierarchically so it survives sparse data (cold start) and sharpens with experience.

```
PD(agent, txn) = clamp( PD_agent · RR(txn) · ctx_adj , PD_MIN , PD_MAX )
```

- **`PD_agent`** — the agent's own default propensity, a Beta posterior (§6), initialized from the `ScoreBand` prior.
- **`RR(txn)`** — transaction-type **relative risk**, a portfolio-calibrated multiplier over category × tenor band × counterparty standing × novelty. This is the axis that makes *type of transaction* move the price. Starts from proxy priors; recalibrated at the portfolio level as outcomes accrue (champion/challenger).
- **`ctx_adj`** — fast context signals: amount vs the agent's typical ticket, velocity, and concentration (exposure to a counterparty/sector already crowded).

```python
def pd_txn(r: AgentRisk, txn) -> float:
    base = r.alpha / (r.alpha + r.beta)
    rr   = RR_CATEGORY[txn.category] * RR_TENOR[txn.tenor_band] * RR_CPTY[txn.cpty_band] * RR_NOVELTY[txn.first_seen]
    adj  = 1 + AMOUNT_SLOPE*z_amount(txn) + VELOCITY_SLOPE*txn.velocity_z + CONC_SLOPE*txn.concentration_z
    return clamp(base * rr * adj, PD_MIN, PD_MAX)
```

Keeping a single agent posterior × an RR table (rather than a full posterior per agent-per-bucket) is deliberate: it concentrates the scarce early data into one well-estimated agent number, while the RR table — estimated across the *whole* portfolio — supplies transaction-type structure that no single agent has enough data to learn alone.

---

## 6. Dynamic updating — the experience-rating loop (the core mechanism)

Each agent×default-propensity is a **Beta(α, β)**. The posterior mean is, by construction, a credibility blend of the band prior and the agent's realized rate — so "weight the agent's record against its band prior" falls out for free.

```python
@dataclass
class AgentRisk:
    alpha: float        # pseudo-defaults
    beta: float         # pseudo-successes
    n0: float           # prior strength (pseudo-count from the band)
    a0: float; b0: float  # prior anchor (band p0)
    last_ts: float

def credibility(r) -> float:                 # Z: 0 = all prior, 1 = all own experience
    n = (r.alpha + r.beta) - r.n0
    return max(0.0, n) / (max(0.0, n) + r.n0)

def update(r: AgentRisk, defaulted: bool, exposure_weight: float, now: float,
           tau_days: float = 120) -> AgentRisk:
    # 1. recency decay — exponentially forget *observed* mass back toward the prior anchor
    decay = exp(-((now - r.last_ts)/86400) / tau_days)
    a = r.a0 + (r.alpha - r.a0) * decay
    b = r.b0 + (r.beta  - r.b0) * decay
    # 2. apply the outcome, exposure-weighted: a large default moves PD more than a tiny one
    w = clamp(exposure_weight, 0.25, 4.0)
    if defaulted: a += w
    else:         b += w
    return AgentRisk(a, b, r.n0, r.a0, r.b0, now)
```

Four properties, each a design requirement made concrete:
- **Updates per outcome** — every settle nudges PD down, every default nudges it up.
- **Credibility-weighted** — new agents lean on the band prior; seasoned agents on their own record, automatically via Z.
- **Recency decay** — old behavior fades toward the prior (`tau_days`), so the price reflects *recent* conduct.
- **Exposure-weighted** — a default on a large ticket moves the posterior more than a trivial one.

**Guardrails on the loop** (so it can't spiral):
- **Step cap:** the per-event change in the *quoted premium* is clamped (e.g. ≤ ±35%/event), so one default reprices firmly but not catastrophically; sustained behavior compounds.
- **Hysteresis:** band promotion requires the realized rate to hold below the threshold for a minimum credible count, so an agent doesn't flip bands on noise.
- **Floor/ceiling:** `PD_MIN/PD_MAX` and the premium floor/cap bound the output regardless of the posterior.
- **Penalty/suspension:** a default applies an immediate repricing; a default *streak* can suspend cover eligibility pending review.

---

## 7. The deterministic envelope — `price()`

Pure, ordered, receipted. The statistical PD enters; a bounded, signed quote leaves.

```python
def price(ctx: QuoteContext, r: AgentRisk, pool: PoolState, P: PricePolicy) -> Quote:
    # 1. eligibility + cover requirement
    if not ctx.eligible:                      # credential invalid / blocked
        return Quote(decision="DECLINE", reason="ineligible")
    pd   = pd_txn(r, ctx.txn)
    Z    = credibility(r)
    load = 1 + P.expense + P.capital + P.risk_margin_max * (1 - Z)   # λ_risk shrinks with data

    # 2. price each active line as expected loss × load, floored
    lines = {}
    for line in ctx.active_lines:
        ead = exposure_for(line, ctx.txn)
        lgd = lgd_for(line, ctx, pool)        # net of collateral / first-loss
        lines[line] = max(P.floor[line], pd * lgd * ead * load)

    premium = band_round(min(P.cap, sum(lines.values())), P.tick)

    # 3. solvency / capacity gate (tier capital adequacy)
    if breaches_capacity(ctx.txn, pool, P):
        return Quote(decision="REVIEW", premium=premium, reason="capacity", pd=pd, Z=Z)

    return Quote(decision="OFFER", premium=premium, lines=lines, pd=pd, credibility=Z,
                 receipt=receipt(ctx, premium, pd))   # canonical hash, anchored in the bind tx Memo
```

`Quote.decision`: **OFFER** (bind via `pay_premium`), **REVIEW** (capacity/risk — escalate), **DECLINE** (ineligible). Every quote carries the PD used and the credibility, so a quote is fully reproducible and auditable from its inputs.

---

## 8. Claims & payout — `decide(PAYOUT)` and the waterfall

On a covered default the loss is absorbed in a fixed order; the pool only ever pays the residual.

```python
def settle_claim(line, loss, ctx, pool, P) -> Payout:
    # recovery first: agent collateral, then first-loss capital
    recovery  = collateral_recovery(ctx) + first_loss_recovery(line, pool)
    shortfall = max(0, loss - recovery)
    payout    = min(P.limit[line], P.recovery_rate[line] * shortfall)

    d = decide(DecisionContext(kind="PAYOUT", actor=insurer, counterparty=ctx.beneficiary,
                               amount=payout))         # AML + collusion + limit gate
    assert d.outcome == "ALLOW", d.reasons

    # capital waterfall: collateral → first-loss → junior tranche → senior tranche
    return Payout(amount=payout, waterfall=["collateral","first_loss","junior","senior"])
```

Then the **post-default consequences**:
- the agent posterior takes a default update (§6), **exposure-weighted**, repricing all its future cover;
- the principal's reputation MPT is **preserved** (score protection) — the pool, not the principal, ate the loss;
- if subrogation is enabled, recovery pursued from the agent flows back to the tranche that bore the loss.

`decide(PAYOUT)` is also where **collusion** is refused: a fabricated default between an agent and a repeat-counterparty merchant is caught by the relationship/payout-pattern checks before the pool pays.

---

## 9. Parameters to calibrate

Everything tunable lives in tables, so risk appetite is set without touching code (and the deterministic envelope keeps the tables enforceable).

| Group | Parameters |
|---|---|
| **Band priors** | per `ScoreBand`: prior default rate `p0`, prior strength `n0` (ELITE: low `p0`, high `n0`; HIGH_RISK: high `p0`, low `n0`) |
| **Relative risk** | `RR_CATEGORY`, `RR_TENOR`, `RR_CPTY`, `RR_NOVELTY` (portfolio-calibrated) |
| **Context slopes** | `AMOUNT_SLOPE`, `VELOCITY_SLOPE`, `CONC_SLOPE` |
| **Loadings** | `λ_expense`, `λ_capital`, `λ_risk_max` |
| **Bounds** | `PD_MIN`, `PD_MAX`, per-line `FLOOR`, `CAP`, quote `tick` |
| **Per line** | `recovery_rate`, `limit`, LGD basis |
| **Loop** | `tau_days` (decay), per-event step cap, promotion hysteresis count |
| **Solvency** | capital-per-exposure target, tier subordination |

---

## 10. Cold start & calibration (the honest hard part)

No autonomous-agent loss history exists, so early pricing must be safe-by-construction:

- **Priors over data:** `p0/n0` per band seeded from proxy analogues (consumer/SME credit), and the `RR` tables from category/tenor priors. The agent posterior *is* the band prior until outcomes arrive.
- **Automatic conservatism:** `λ_risk = λ_risk_max·(1−Z)` makes every premium carry a large uncertainty margin while data is thin, relaxing as `Z` rises — no manual "early phase" switch.
- **Tight early limits + mandatory collateral** until the portfolio has credible counts; loosen as the realized loss rate confirms the priors.
- **Backtest on the Arena:** replay the simulation (and later, sandbox/testnet outcomes) to validate the loop's stability and the loadings before real capital is exposed; recalibrate `RR` and band priors champion/challenger as live outcomes accrue.

---

## 11. Integration & data contract

- **Bind:** `price()` → `pay_premium(amount=Quote.premium, payee=InsuranceVault)`; the `receipt` is anchored in the bind transaction's Memo.
- **Gate:** `decide(PAYMENT)` consults the cover requirement (§3); if required and unbound → REVIEW/auto-bind.
- **Inputs:** the certified `ScoreBand` selects the band prior; `PoolState` (tier capacity, first-loss level) feeds LGD and the solvency gate.
- **Outcomes:** settle/default emit ARS events; the off-chain core consumes them to `update()` the posterior; a periodic posterior summary can be anchored on-chain for audit.
- **On/off-chain split:** the core (PD, RR, posterior) runs off-chain; the envelope (`price`, floors, caps, the solvency gate, the receipt) is deterministic and anchored — so what touches LP capital is always auditable, even though the model that informs it is rich.

---

### The engine in one line

A statistical core learns *how risky this agent is, on this kind of transaction, lately* — and a deterministic envelope turns that into a bounded, loaded, signed premium that the rest of the system can trust, with every quote reproducible from its inputs and every payout gated and waterfalled. The price moves with the agent because the posterior moves with the agent; the price moves with the transaction because the relative-risk table makes it.
