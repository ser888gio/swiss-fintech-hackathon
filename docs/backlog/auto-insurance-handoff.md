# Handoff: Risk-Triggered Auto-Insurance (global default + per-agent override)

**Audience:** an implementing agent/engineer with no prior context on this thread.
**Status:** implemented on 2026-06-21. This document now records the design that
the code follows.

---

## 1. Goal (what the operator gets)

A treasury operator runs agents that pay services and invoices. They should
**never quote/bind insurance per payment**. Instead:

- Set an auto-insure rule **once** — a treasury-wide default, optionally
  overridden per agent.
- Every payment is then automatically evaluated by deterministic code: if the
  rule says "cover this", the system quotes + binds the premium before
  settlement and stamps the result on the payment.
- The rule is **risk-triggered**: insure when the **counterparty is new OR
  unverified, OR the amount ≥ threshold**.

The chosen product decisions (already settled with the stakeholder):

- **Config level:** both — a global default *and* a per-agent override.
- **Trigger:** risk-triggered (new/unverified counterparty OR amount ≥ X).

The standalone Insurance page is intentionally **deleted** and stays deleted
(`apps/web/src/pages/InsurancePage.tsx`, removed on this branch). Do not
recreate it.

---

## 2. Critical context: most of this already exists

**The auto-insure wire is already in the main payment path.** Do not rebuild it.
[`apps/api/app/agents/orchestrator.py:165-238`](../../apps/api/app/agents/orchestrator.py)
already does, inside `process_payment`:

```
evaluate_cover(...) → insurance_tool.quote(...) → insurance_tool.bind(...)
→ stamps payment.coverage (PaymentCoverage)
```

The pricing engine, Bayesian risk model, `bind`, `settle_claim`, pool, and their
unit tests are all built and passing. **This task changes the *trigger*, not the
subsystem.**

### Implemented gaps

1. **Risk trigger added.** `evaluate_cover()` handles counterparty mandate,
   new/unverified counterparty risk, and the amount threshold in fixed order.
2. **Global-vs-agent resolution added.** Agents inherit the global rule or select
   an explicit custom rule or opt-out.
3. **Quote inputs now use policy context.** Package, counterparty verification,
   novelty, and the stored agent risk band feed deterministic pricing.

---

## 3. Design: one pure resolver, `evaluate_cover`

Mirror `evaluate_scope` exactly: a **pure function, no I/O**, all inputs passed in
by the caller. This is the determinism boundary required by `CLAUDE.md` — the
cover decision is plain Python with unit tests, never an LLM branch.

### New file: `apps/api/app/insurance/cover_policy.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field, replace
from decimal import Decimal


@dataclass(frozen=True)
class CoverRule:
    """Resolved auto-insure rule for one payment, built from the global default
    merged with a per-agent override at the config boundary (resolve_cover_rule).
    The caller never constructs this by hand inside the hot path."""
    mode: str                                  # "on" | "off"  (inherit already resolved away)
    amount_threshold_usd: Decimal | None       # None disables the amount trigger
    insure_new_counterparty: bool
    insure_unverified_counterparty: bool
    package: str | None                        # "Essential" | "Standard" | "Full-Stack" | None


@dataclass(frozen=True)
class CoverDecision:
    required: bool
    required_by: str | None        # "counterparty" | "risk" | "policy" | None
    rule_fired: str | None
    package: str | None


def evaluate_cover(
    *,
    rule: CoverRule,
    amount_usd: Decimal,
    counterparty_cover_required: bool,            # intent.cover_required (mandate)
    counterparty_threshold_usd: Decimal | None,   # intent.cover_required_above_usd
    counterparty_is_new: bool,
    counterparty_verified: bool,
) -> CoverDecision:
    """Resolution ladder (first match wins):
      1. rule.mode == "off"                          → not required (agent opt-out wins)
      2. counterparty mandate (cover_required and
         amount >= counterparty_threshold or no thr) → required_by="counterparty"
      3. risk: (new and rule.insure_new) OR
               (not verified and rule.insure_unverified) → required_by="risk"
      4. amount_threshold set and amount >= it         → required_by="policy"
      5. else                                          → not required
    """
    if rule.mode == "off":
        return CoverDecision(False, None, "agent_opt_out", None)

    if counterparty_cover_required and (
        counterparty_threshold_usd is None or amount_usd >= counterparty_threshold_usd
    ):
        return CoverDecision(True, "counterparty", "counterparty_mandate", rule.package)

    if (counterparty_is_new and rule.insure_new_counterparty) or (
        not counterparty_verified and rule.insure_unverified_counterparty
    ):
        return CoverDecision(True, "risk", "counterparty_risk", rule.package)

    if rule.amount_threshold_usd is not None and amount_usd >= rule.amount_threshold_usd:
        return CoverDecision(True, "policy", "amount_threshold", rule.package)

    return CoverDecision(False, None, None, None)


def resolve_cover_rule(settings, agent_override: "AutoInsureConfig | None") -> CoverRule:
    """Merge the global default (settings) with an optional per-agent override.
    `inherit` → global; `off` → forced off; `on` → agent fields win where set."""
    base = CoverRule(
        mode="on",
        amount_threshold_usd=Decimal(str(settings.insurance_cover_required_above_usd)),
        insure_new_counterparty=settings.insurance_auto_new_cpty,
        insure_unverified_counterparty=settings.insurance_auto_unverified_cpty,
        package=settings.insurance_default_package,
    )
    if agent_override is None or agent_override.mode == "inherit":
        return base
    if agent_override.mode == "off":
        return replace(base, mode="off")
    # mode == "on": override only the fields the agent explicitly set (non-None)
    overrides = {}
    if agent_override.amount_threshold_usd is not None:
        overrides["amount_threshold_usd"] = Decimal(str(agent_override.amount_threshold_usd))
    if agent_override.insure_new_counterparty is not None:
        overrides["insure_new_counterparty"] = agent_override.insure_new_counterparty
    if agent_override.insure_unverified_counterparty is not None:
        overrides["insure_unverified_counterparty"] = agent_override.insure_unverified_counterparty
    if agent_override.package is not None:
        overrides["package"] = agent_override.package
    return replace(base, **overrides)
```

`evaluate_cover` subsumes the old `cover_requirement()` — after wiring, delete
`cover_requirement` and update its callers/tests (see §6).

### Per-agent override semantics

| Agent `auto_insure.mode` | Result |
|---|---|
| `off` | No cover, even if global/amount/risk would trigger (ladder step 1). |
| `inherit` (default) | Use the global risk-triggered rule. |
| `on` + fields | Agent's set fields override the global ones. |

---

## 4. The counterparty signals (where new/verified come from)

Inside `process_payment`, a KYC credential is **already fetched** at
[`orchestrator.py:82`](../../apps/api/app/agents/orchestrator.py):
`credential = await credentials.verify_kyc(intent.to)`. **Reuse it** — do not
re-call.

- `counterparty_verified` = `credential.verified` (or `credential.checked and
  credential.verified` — confirm the field; `verify_kyc` returns a result with
  `.verified`, `.checked`, `.reason`, `.credential_type`).
- `counterparty_is_new` — there is no first-seen tracker for arbitrary payees on
  the standard path. Two options, pick one and note it in the PR:
  - **(a) Simple, recommended for the demo:** treat "new" = not verified AND not
    a known/allowlisted address. Cheap, no new state.
  - **(b) Proper:** add a seen-counterparties set keyed by `intent.to` in
    `store`, marked after first settled payment. More faithful but more code +
    persistence. Out of scope unless asked.

---

## 5. File-by-file changes

### Backend

**B1 — NEW `apps/api/app/insurance/cover_policy.py`** — as in §3. The core work.

**B2 — `apps/api/app/config.py`** (`Settings`):
- **FIX A PRE-EXISTING BUG:** `insurance_enabled` and
  `insurance_cover_required_above_usd` are each declared **twice** (around
  lines 194/216 and 200/224) with different defaults (`None` vs `10_000.0`). The
  later declaration silently wins. **Collapse each to a single declaration.**
  Verify nothing depended on the first (`None`) value before changing the
  effective default.
- **ADD** global-default knobs:
  ```python
  insurance_auto_new_cpty: bool = True
  insurance_auto_unverified_cpty: bool = True
  insurance_default_package: str = "Essential"
  ```

**B3 — `apps/api/app/schemas.py`**:
- ADD `AutoInsureConfig(CamelModel)`:
  ```python
  class AutoInsureConfig(CamelModel):
      mode: str = "inherit"                              # "inherit" | "off" | "on"
      amount_threshold_usd: float | None = None
      insure_new_counterparty: bool | None = None
      insure_unverified_counterparty: bool | None = None
      package: str | None = None
  ```
- ADD `auto_insure: AutoInsureConfig | None = None` to **`AgentCreate`**
  (line ~497) — it is inherited by `Agent` (line ~517).
- ADD `auto_insure: AutoInsureConfig | None = None` to **`AgentUpdate`**
  (line ~526).
- `PaymentCoverage` (line ~901) already has `status` + `required_by`. The
  `CoverageStatus` enum (line ~894) is `not_required | bound | review |
  declined`. `required_by` is a free `str | None`, so `"risk"` flows without an
  enum change. No schema change needed there.

**B4 — `apps/api/app/models.py`** (`AgentRecord`, line ~292):
- ADD a JSON column: `auto_insure: Mapped[dict | None] = mapped_column(JSON,
  nullable=True)`. Follows the existing `allowed_categories` JSON pattern.
- A fresh table picks it up automatically (SQLAlchemy `create_all`). If a
  migration path exists for prod, add the column; otherwise note "new column,
  recreate dev DB".

**B5 — `apps/api/app/routes/agents.py`**:
- `_persist_agent` (line ~468): add `auto_insure=agent.auto_insure.model_dump()
  if agent.auto_insure else None` to the `AgentRecord(...)`.
- `_row_to_agent` (line ~503): add `auto_insure=AutoInsureConfig(**row.auto_insure)
  if row.auto_insure else None`.
- `create_agent` (line ~46): `req.model_dump(by_alias=False)` already spreads new
  fields, so `auto_insure` passes through with no change.
- `update_agent` (line ~270): the `exclude_none` patch already handles it.

**B6 — `apps/api/app/agents/orchestrator.py`** — the wiring:
- `process_payment` signature (line ~53) currently takes `agent_id`,
  `agent_scope`. **ADD** `agent_cover: AutoInsureConfig | None = None`.
- Replace the `cover_requirement(...)` call (line ~165) with:
  ```python
  rule = resolve_cover_rule(settings, agent_cover)
  cover = evaluate_cover(
      rule=rule,
      amount_usd=Decimal(str(amount_usd)),
      counterparty_cover_required=intent.cover_required,
      counterparty_threshold_usd=(
          Decimal(str(intent.cover_required_above_usd))
          if intent.cover_required_above_usd is not None else None
      ),
      counterparty_is_new=_counterparty_is_new(intent, credential),  # §4
      counterparty_verified=credential.verified,
  )
  if settings.insurance_enabled and cover.required:
      ...existing quote → DECLINE/REVIEW/OFFER → bind block...
      # required_by = cover.required_by ; package = cover.package
  ```
- Feed `cover.package` into the quote's `activeLines`/package selection (expand
  via `INSURANCE_PACKAGES` like the deleted page did), and derive `cptyBand` from
  the new/verified signal instead of the hardcoded entity-type-only line.
- Keep the existing DECLINE → block, REVIEW → escalate, OFFER → bind branches
  intact; only their *gating condition* and *inputs* change.

**B7 — `apps/api/app/agents/treasury_agent.py`** (lines ~263-276): the two
`process_payment(...)` calls that pass `agent_scope` should also pass
`agent_cover=<agent.auto_insure>`. The agent object is available where the scope
is built; thread it through `run_for_agent` the same way scope is.

> **Entry-path note:** `payments.py:20` calls `process_payment(intent)` with **no
> agent context**, so direct API payments always fall through to the global
> default (correct — they have no agent). Only the `treasury_agent` path carries
> a per-agent override.

### Frontend

**F1 — `packages/shared/src/types.ts`** — add the `AutoInsureConfig` TS type
mirroring the Pydantic model (hand-sync per `CLAUDE.md`). Add the optional
`autoInsure` field to the `Agent` / `AgentCreate` / `AgentUpdate` types.

**F2 — Agent builder/config page** (the page that creates/edits an Agent — find
the form that posts to `/agents`; it sets `maxSinglePayment` etc.). Add an
"Auto-insure" block beside the scope limits:
- mode radio: `Inherit (default) / Off / Custom`
- when `Custom`: amount threshold input, two checkboxes (new counterparty,
  unverified counterparty), package dropdown (Essential/Standard/Full-Stack).

**F3 — Payment rows + `apps/web/src/pages/DashboardPage.tsx`** — `payment.coverage`
is already populated and likely already rendered. Verify the `Covered` badge
shows premium + `explorerUrl`, and add a "covered because: {requiredBy}"
tooltip. Optionally add a dashboard tile (premiums this period / pool capacity)
from `api.getInsurancePool()`.

---

## 6. Tests (determinism-boundary discipline — required)

**NEW `apps/api/tests/test_cover_policy.py`** — table-driven over `evaluate_cover`:

| case | inputs | expect |
|---|---|---|
| opt-out wins | `mode="off"`, new + huge amount | `required=False`, `rule_fired="agent_opt_out"` |
| counterparty mandate | `cover_required=True`, below thr | `required_by="counterparty"` |
| new counterparty | new, verified, amount < thr | `required_by="risk"` |
| unverified counterparty | known, unverified, amount < thr | `required_by="risk"` |
| amount only | known, verified, amount ≥ thr | `required_by="policy"` |
| nothing fires | known, verified, amount < thr | `required=False` |
| risk disabled | `insure_new=False`, new, verified, below thr | `required=False` |

Plus `resolve_cover_rule`: `inherit` → global; `off` → forced off; `on` →
overrides only set fields.

**UPDATE** any test importing `cover_requirement` once it is removed (grep
`cover_requirement` under `apps/api/tests`). The engine/risk/bind/claim tests are
untouched.

Run: `cd apps/api && . .venv/Scripts/activate && pytest -q`.

---

## 7. Known issues to flag (do not silently fix unless asked)

- **`insurance_binding` is an undefined name.** `orchestrator.py:491` and `:506`
  call `insurance_binding.quote(...)` / `insurance_binding.bind_service_cover(...)`
  but only `insurance_tool` is imported. This is on the **service-payment**
  (`process_service_payment`) path, and the call is wrapped in a bare
  `except Exception: pass` (line ~511), so the `NameError` is swallowed —
  x402 cover silently never binds. Out of scope for this task, but flag it in the
  PR; fixing the standard path doesn't touch it.

---

## 8. Resolved scope decisions

- **LP capital** was deleted from the current MVP. The insurance pool is funded
  by operator-owned first-loss capital plus collected premiums.
- **Standalone quote and bind endpoints** were deleted. Both operations are
  internal deterministic steps in the payment workflow.

Still out of scope:

- A persistent first-seen counterparty tracker (§4 option b) unless the
  stakeholder wants true "new counterparty" semantics over the cheap heuristic.

---

## 9. Suggested PR sequence

1. B1 + tests (pure, no wiring) — green in isolation.
2. B2 config (incl. duplicate-key fix).
3. B3/B4/B5 schema + model + persistence.
4. B6/B7 orchestrator + treasury_agent wiring.
5. F1 shared types.
6. F2/F3 UI.

Each step is independently reviewable; steps 1-4 are backend-complete and
demoable via the agent run path before any UI work.
