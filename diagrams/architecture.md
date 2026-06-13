# Software Architecture Documentation

## Overview

A single backend workflow orchestrates corporate cross-border payments on XRPL.
The architecture is built around one hard rule: **the LLM orchestrates and
narrates but never decides policy or signs**. Policy (auto-settle vs. escalate
vs. block) and signature verification are deterministic Python; the only
LLM-assisted step is the human-readable audit explanation. The system spans three
deployable units — a React dashboard, a FastAPI backend, and a local Node bridge
to a Firefly hardware device — sharing TypeScript types via `@treasury/shared`.

## System Context

- **Operator (treasurer)** drives everything from the browser dashboard.
- **Firefly hardware device** is the only thing that can release a large payment;
  it signs an approval challenge on a physical button press.
- **External providers**: XRPL testnet (settlement), OpenAI (narration),
  Frankfurter + CoinGecko (rates), OpenSanctions (screening).

## Layers / Services

### Web dashboard (`apps/web`)
- **Purpose**: Operator UI to submit payment intents, watch the agent log, and
  approve locked payments.
- **Technology**: TypeScript, React 18, Vite.
- **Entry Points**: `main.tsx` → `App.tsx`; pages `DashboardPage`, `TransferPage`;
  components `NewPaymentForm`, `PaymentCard`.
- **Dependencies**: `lib/api.ts` (backend REST), `lib/firefly.ts` (local bridge),
  `@treasury/shared` types.
- **Interfaces**: Renders payment state; triggers create / quote / release.
- **Location**: `apps/web/src/`.

### Shared types (`packages/shared`)
- **Purpose**: Single source of TypeScript contracts used by web and bridge.
- **Technology**: TypeScript (`src/types.ts`, `src/index.ts`).
- **Interfaces**: `PaymentIntent`, `Payment`, `RouteQuote`, `ApprovalChallenge`,
  `BridgeSignRequest/Response`. The Python API mirrors these in
  `apps/api/app/schemas.py` by hand.

### API / Orchestrator (`apps/api`)
- **Purpose**: Run the payment workflow as a fixed sequence of deterministic tool
  calls, persisting a full decision trail.
- **Technology**: Python 3.11, FastAPI, Pydantic, `httpx`, `xrpl-py`, OpenAI SDK,
  `eth_keys` (secp256k1).
- **Entry Points**: `app/main.py` mounts `routes/health` and `routes/payments`.
- **Key modules**:
  - `agents/orchestrator.py` — fixed-order workflow + narration (no decisions).
  - `policy/engine.py` — **the policy boundary**; pure `evaluate()` returning
    settle / escalate / block.
  - `tools/routing.py` — FX path quote (Frankfurter / CoinGecko).
  - `tools/compliance.py` (+ `tools/public_intel.py`) — sanctions + AML score.
  - `tools/execution.py` — XRPL Payment / EscrowCreate / EscrowFinish.
  - `tools/firefly.py` — build approval challenge, verify secp256k1 signature.
  - `tools/audit.py` — **only LLM call**; narrates the decision trail.
  - `tools/receipt.py` — deterministic receipt hash.
  - `store.py` / `models.py` / `schemas.py` — persistence + contracts.

### Firefly bridge (`apps/firefly-bridge`)
- **Purpose**: Local broker between the browser and the USB hardware device.
- **Technology**: Node 20, Express, `serialport` (or mock device).
- **Entry Points**: `src/index.ts` (`/health`, `/sign` on :4747);
  `src/device.ts` (`deriveDigest` mirrors the Python canonical payload);
  `src/keygen.ts`.
- **Interfaces**: `POST /sign` → device shows request → button press → signature.

## Data Flow

### 1. Submit a payment (deterministic decision)
1. Browser `POST /payments` with a `PaymentIntent` (`routes/payments.py:14`).
2. `orchestrator.process_payment` saves the payment and logs the intent.
3. `routing.get_fx_path` fetches an FX/crypto rate and builds a `RouteQuote`.
4. `compliance.check_compliance` screens the receiver (OpenSanctions or fallback)
   and computes an AML score.
5. `policy.engine.evaluate(dest_amount, aml_score, sanctioned)` returns the
   decision — **the only place money policy is decided**.
6. `audit.write_audit` (OpenAI, or template) narrates the trail.
7. Branch: `_settle` → `execution.execute_payment` (XRPL Payment);
   `_escalate` → `execution.lock_payment` (EscrowCreate, status
   `pending_approval`); `_block` → refuse. Sanctioned counterparties are blocked
   outright and cannot be overridden.

### 2. Release a locked payment (hardware veto)
1. Browser `GET /payments/{id}/challenge` → `firefly.challenge_for_payment`
   returns a sha256 digest bound to network + escrow.
2. Browser `POST localhost:4747/sign` → bridge → Firefly device → physical button
   press → secp256k1 signature.
3. Browser `POST /payments/{id}/release` with the signature.
4. `orchestrator.release_payment` calls `firefly.verify_signature`; only on
   success does `execution.finish_escrow` (EscrowFinish) run and the status
   become `released`.

## API Contracts

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/payments` | Submit intent, run workflow |
| POST | `/payments/quote` | Preview FX quote |
| GET | `/payments` / `/payments/{id}` | List / fetch payment |
| GET | `/payments/{id}/logs` | Agent narration log |
| GET | `/payments/{id}/challenge` | Approval digest |
| POST | `/payments/{id}/release` | Verify signature, finish escrow |
| POST | `/payments/{id}/release-tampered` | DEMO: prove signature binding |
| GET | `/payments/{id}/receipt` | Terminal-state receipt |
| GET | `/health` | Liveness |

## Deployment Mapping

Web dashboard and API run as separate Railway services (see
`infrastructure.md`); the bridge and device run on the operator's machine. The
determinism boundary (`policy/engine.py`, `tools/firefly.py`,
`tools/execution.py`) is plain, unit-tested Python — the LLM in `tools/audit.py`
sits entirely outside it.

## Technical Debt / Concerns

- `store.py` is in-memory; the Postgres/SQLAlchemy swap in `models.py` is staged
  but not wired.
- `tools/execution.py` mocks XRPL submission (`use_mock_xrpl`); real Payment /
  Escrow paths raise `NotImplementedError` until testnet wallets are set up.
- The canonical approval payload is duplicated by hand in
  `tools/firefly.py` and `firefly-bridge/src/device.ts`; the two MUST stay in
  sync.
