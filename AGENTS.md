# AGENTS.md

This file describes the **agent/tool architecture** of the treasury system — what
each component does, its determinism class, and its contract. It is the
authoritative spec for the orchestration layer.

> Companion file: `CLAUDE.md` holds repo conventions and the hard rule that the
> **LLM never decides policy or signs**. Read it first.

## Mental model

The product *presents* a team of agents. The implementation is **one backend
workflow** (`apps/api/app/agents/orchestrator.py`) that runs an LLM tool-use
loop. The LLM's only jobs are (1) call the right tools in order and (2) narrate
what happened in plain language. Every consequential decision is made by
deterministic code inside a tool.

```
payment intent
      │
      ▼
┌──────────────────────────────────────────────┐
│  Treasury Orchestrator  (LLM tool-use loop)   │  ← narrates only
└──────────────────────────────────────────────┘
   │        │            │            │
   ▼        ▼            ▼            ▼
 routing  compliance   policy      execution / firefly / audit
(determ.) (determ.)  (CODE, not   (determ.)
                      the LLM)
```

## Components

| Component | Determinism | Module | Responsibility |
|---|---|---|---|
| **Treasury Orchestrator** | LLM loop | `app/agents/orchestrator.py` | Receives a payment intent, calls tools in order, narrates decisions. Holds **no** policy logic. |
| **Routing tool** `get_fx_path` | Deterministic | `app/tools/routing.py` | Frankfurter FX quote + XRPL `ripple_path_find`; returns the cheapest path summary. |
| **Compliance tool** `check_compliance` | Deterministic (mock OK) | `app/tools/compliance.py` | Sanctions/KYC screen + AML score 0–100 + plain-language reason. |
| **Public intelligence tool** `assess_public_intel` | Deterministic facade, agent-ready | `app/tools/public_intel.py` | Returns an advisory OSINT risk result. Future AI agents may gather evidence, but code computes the score and policy effect. |
| **Policy engine** | **Deterministic — code-enforced** | `app/policy/engine.py` | Threshold + risk-score decision: auto-settle vs. escalate. **Never the LLM's call.** |
| **Execution tool** | Deterministic | `app/tools/execution.py` | Direct token Payment, or escrow/lock for large payments. |
| **Firefly approval tool** | Deterministic | `app/tools/firefly.py` | Builds the approval challenge, verifies the Firefly signature, then triggers release. |
| **Audit tool** | LLM-assisted | `app/tools/audit.py` | Writes a human-readable explanation of each decision to Postgres. |

## The policy boundary (the core innovation)

Defined once, in code, and unit-tested. The LLM cannot reach past it.

```python
# apps/api/app/policy/engine.py
THRESHOLD_USD = 10_000
COMPLIANCE_FLAG_SCORE = 60

requires_approval = amount_usd > THRESHOLD_USD or aml_score > COMPLIANCE_FLAG_SCORE
```

- `requires_approval == False` → execution tool settles directly. Seconds.
- `requires_approval == True` → funds are **locked on-chain** (escrow) and a
  pending-approval card appears. Release requires a verified Firefly signature.

## Tool contracts

Each tool takes and returns typed, JSON-serializable data. Pydantic schemas live
in `app/schemas.py` and mirror `packages/shared/src/types.ts`.

- `get_fx_path(intent) -> RouteQuote` — `{ source_amount, dest_amount, rate,
  path_summary, estimated_fee }`.
- `check_compliance(intent) -> ComplianceResult` — `{ aml_score, sanctioned:
  bool, flags: string[], explanation, sanctions_matches[], public_intel }`.
- `assess_public_intel(intent) -> PublicIntelResult` — `{ score,
  confidence, flags[], sources[], summary }`. Advisory only; it can raise AML
  risk but cannot block or approve a payment by itself.
- `evaluate_policy(amount_usd, aml_score) -> PolicyDecision` — `{
  requires_approval, rule_fired, reasons[] }`. **Pure function, no I/O.**
- `execute_payment(intent, route) -> ExecutionResult` — direct payment;
  returns `{ tx_hash, explorer_url, status }`.
- `lock_payment(intent, route) -> EscrowResult` — escrow create; returns
  `{ escrow_sequence, tx_hash, explorer_url }`.
- `build_approval_challenge(payment_id) -> ApprovalChallenge` — `{ payment_id,
  digest }` for the Firefly to sign.
- `verify_and_release(payment_id, signature) -> ExecutionResult` — verifies the
  signature against `FIREFLY_PUBLIC_KEY`, then submits EscrowFinish.
- `write_audit(payment_id, decision_trail) -> None`.

## Hardware veto — chosen approach

Baseline shipped first (per `docs/PLAN.md §5`):

**Option C — Firefly-signed approval payload.** Firefly signs the payment digest;
the backend verifies the signature before submitting the release (EscrowFinish).
Combined with an on-chain escrow so funds are genuinely locked, not just
UI-gated. Upgrade to a crypto-condition escrow (Option A) or XRPL multisig
(Option B) only if Ripple mentors confirm feasibility in time.

The signature must be **cryptographically meaningful** — verified against a known
public key — not a UI button. If the verification step is fake, the core
innovation is fake.

## Rules for agents editing this system

1. New tool → add it to this table, define its Pydantic schema + the mirrored TS
   type, and register it in the orchestrator's tool list.
2. Never move a decision into the prompt. If you find yourself prompt-engineering
   a threshold, you are doing it wrong — put it in `policy/`.
3. Every tool that touches XRPL returns an explorer URL. Demos need proof.
4. Keep tools pure where possible; isolate I/O (network, DB) at the edges so the
   policy engine stays trivially testable.
