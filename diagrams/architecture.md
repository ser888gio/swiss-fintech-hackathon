# Software Architecture Documentation

## Overview

A single backend workflow orchestrates corporate cross-border payments and a
suite of agentic financial primitives on XRPL. The architecture is built around
one hard rule: **the LLM orchestrates and narrates but never decides policy or
signs**. Auto-settle vs. escalate vs. block, and signature verification, are
deterministic Python; the only LLM-assisted step is the human-readable audit
explanation. The system spans three deployable units — a React dashboard, a
FastAPI backend, and a local Node bridge to a Firefly hardware device — sharing
TypeScript contracts via `@treasury/shared` (mirrored by hand into Pydantic
`schemas.py`).

## System Context

- **Operator (treasurer)** drives everything from the browser dashboard
  (`apps/web/src/App.tsx`).
- **Firefly Pixie device** is the only thing that can release a locked payment; it
  signs an approval challenge on a physical button press.
- **External providers**: XRPL Testnet/Devnet (settlement, escrow, credentials),
  OpenAI (narration), Frankfurter (FX), OpenSanctions + Plaid (screening), t54 x402
  facilitator (pay-at-need).

## Layers / Services

### Web dashboard (`apps/web`)
- **Purpose**: Operator UI to submit intents, watch the agent log, approve locked
  payments, and drive the treasury / insurance / credentials / demo workspaces.
- **Technology**: TypeScript, React 18, Vite. Hash-free pathname router in
  `App.tsx` with lazy-loaded pages.
- **Entry Points**: `main.tsx` → `App.tsx`; pages include `DashboardPage`,
  `TransferPage`, `TreasuryPage`, `CoverPage`,
  `CredentialsPage`, `SanctionsPage`, `WalletPage`, `DemoLabPage`.
- **Dependencies**: `lib/api.ts` (typed REST client for the whole API surface),
  `lib/firefly.ts` (local bridge), `@treasury/shared` types.
- **Location**: `apps/web/src/`.

### Shared types (`packages/shared`)
- **Purpose**: Single source of TypeScript contracts used by web and bridge.
- **Interfaces**: `PaymentIntent`, `Payment`, `RouteQuote`, `ApprovalChallenge`,
  `BridgeSignRequest/Response`, plus agent, insurance, cover, delegation, and
  receivable types. Python mirrors these in `apps/api/app/schemas.py`.

### API / Orchestrator (`apps/api`)
- **Purpose**: Run each workflow as a fixed sequence of deterministic tool calls,
  persisting a full decision trail to Postgres.
- **Technology**: Python 3.11, FastAPI, Pydantic, async SQLAlchemy, `httpx`,
  `xrpl-py`, OpenAI SDK, `eth_keys` (secp256k1).
- **Entry Points**: `app/main.py` mounts routers under `routes/`: `health`,
  `payments`, `credentials`, `kyc`, `treasury`, `wallet`, `agents`, `merchants`,
  `cover`, `redteam`. Lifespan rehydrates state from the DB.
- **Determinism boundary (never LLM)**:
  - `policy/engine.py` — pure `evaluate()`: settle / escalate / block on a USD
    threshold + AML flag score; sanctions = hard block.
  - `policy/guardrail.py` — unified G1–G7 guardrail chain dispatched per context
    (payment, agent_payment, service_payment, delegation_fund, loan_underwrite,
    insurance_payout).
  - `policy/scope.py` — per-agent velocity / allowlist scope (G4).
  - `tools/firefly.py` — build approval challenge, verify secp256k1 signature.
  - `tools/execution.py` — XRPL Payment / EscrowCreate / EscrowFinish.
- **Tool layer (`tools/`)**: `routing` (FX path + USD normalisation), `compliance`
  + `country_risk` + `public_intel` (sanctions/AML), `audit` + `audit_log`
  (**only LLM call** + Ed25519 hash-chained event log), `receipt`/`receipt_pdf`,
  `x402`, `delegation`, `trade_finance`, `lending`, `vault`, `mptoken`, `wallet`.
- **Domain modules**: `agents/` (orchestrator + autonomous `treasury_agent`),
  `insurance/` (actuarial engine, risk, tables), `cover/` (annual agent cover),
  `credentials/` (XLS-70 KYC/KYA issuance, Plaid IDV), `ars/` (constraint engine).
- **Persistence**: `store.py` write-through in-memory cache, `db.py` async session
  factory, `models.py` SQLAlchemy tables, `schemas.py` Pydantic contracts.

### Firefly bridge (`apps/firefly-bridge`)
- **Purpose**: Local broker between the browser and the USB hardware device.
- **Technology**: Node 20, Express, `serialport` (or `MockFireflyDevice`).
- **Entry Points**: `src/index.ts` (`/health`, `/sign` on :4747); `src/device.ts`
  (`deriveDigest` mirrors the Python canonical payload byte-for-byte);
  `src/keygen.ts`.
- **Interfaces**: `POST /sign` → device shows request → button press → signature.

## Data Flow

### 1. Submit a payment (deterministic decision)
1. Browser `POST /payments` with a `PaymentIntent` (`routes/payments.py`).
2. `orchestrator.process_payment` saves the payment and logs the intent.
3. `routing.get_fx_path` builds a `RouteQuote`; the source amount is normalised to
   USD (`orchestrator.py:76-96`).
4. `credentials.verify_kyc` checks the receiver's XLS-70 credential;
   `compliance.check_compliance` screens sanctions and computes an AML score.
5. `policy.guardrail.evaluate_guardrails` runs the context's guardrail chain
   (G2 sanctions + G6 threshold for a plain payment; +G4 scope for an agent),
   yielding the **deterministic** settle / escalate / block decision.
6. If cover is required, `insurance_tool.quote` may DECLINE (block), REVIEW
   (escalate), or auto-bind a premium (`orchestrator.py:163-223`).
7. `audit.write_audit` (OpenAI, or template) narrates the finished trail; a
   compliance memo + receipt hash are anchored on-ledger.
8. Branch: `_settle` → `execution.execute_payment` (XRPL Payment); `_escalate` →
   `execution.lock_payment` (EscrowCreate, status `pending_approval`); `_block` →
   refuse. Sanctioned counterparties are blocked outright and cannot be overridden.

### 2. Release a locked payment (hardware veto)
1. Browser `GET /payments/{id}/challenge` → `firefly.challenge_for_payment`
   returns a sha256 digest bound to network + escrow.
2. Browser `POST localhost:4747/sign` → bridge → Firefly device → physical button
   press → secp256k1 signature (`App.tsx:104-134`, `firefly.ts`).
3. Browser `POST /payments/{id}/release` with the signature.
4. `orchestrator.release_payment` calls `firefly.verify_signature`; only on success
   does `execution.finish_escrow` (EscrowFinish) run and the status become
   `released`. `/release-tampered` proves a mutated amount fails verification.

### 3. Agentic settlement (x402 pay-at-need)
1. `process_service_payment` fetches the HTTP 402 requirement, then runs G1 KYA →
   G4 scope → G6 threshold (no approval path — scope/threshold failures hard-block).
2. On pass it reserves agent spend, settles via the t54 facilitator, retries the
   service with payment proof, and records a `ServicePaymentRecord`
   (`orchestrator.py:353-499`).

## API Contracts (selected)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/payments` | Submit intent, run workflow |
| GET | `/payments/{id}/challenge` | Approval digest |
| POST | `/payments/{id}/release` | Verify signature, finish escrow |
| POST | `/credentials` · `/credentials/{id}/accept` | Issue / accept XLS-70 credential |
| GET/POST | `/treasury/goals` · `/treasury/run` | Autonomous agent goals & runs |
| POST | `/treasury/service-payment` | x402 pay-at-need |
| POST | `/cover/quote` | Annual agent-cover pricing |
| POST | `/agents` · `/agents/{id}/run` | Business-defined payment agents |
| POST | `/redteam/attack` | DEMO-only red-team scenarios |

## Deployment Mapping

Web dashboard and API run as separate Railway services (see `infrastructure.md`);
the bridge and device run on the operator's machine. The determinism boundary
(`policy/`, `tools/firefly.py`, `tools/execution.py`) is plain, unit-tested Python;
the LLM in `tools/audit.py` sits entirely outside it.

## Technical Debt / Concerns

- The canonical approval payload is duplicated by hand in `tools/firefly.py` and
  `firefly-bridge/src/device.ts`; the two MUST stay in sync (asserted in comments).
- TypeScript `@treasury/shared` types and Python `schemas.py` are mirrored by hand;
  drift risk on every schema change.
- `config.py` defines two `insurance_enabled` blocks (the later one wins); the
  duplicated knobs are a refactor target.
- Several amendment-gated features (vault XLS-65, lending XLS-66, MPToken XLS-33)
  are Devnet-only and disabled by default; the orchestrator degrades to direct
  token payments when they are off.
