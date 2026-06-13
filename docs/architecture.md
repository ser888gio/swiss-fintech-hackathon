# Architecture

## System overview

```
                         ┌─────────────── Railway ───────────────┐
                         │                                        │
   ┌──────────┐  HTTP    │   ┌──────────┐        ┌────────────┐   │
   │  Browser │◄────────►│   │   API    │◄──────►│  Postgres  │   │
   │ (web app)│          │   │ FastAPI  │        │  (audit)   │   │
   └────┬─────┘          │   └────┬─────┘        └────────────┘   │
        │                │        │                               │
        │                │        │ xrpl-py (wss)                 │
        │                └────────┼───────────────────────────────┘
        │ localhost HTTP          │
        ▼                         ▼
   ┌──────────────┐         ┌───────────────┐
   │ Firefly      │         │  XRPL Testnet │
   │ bridge       │         │  (RLUSD/IOU,  │
   │ (LOCAL only) │         │   escrow)     │
   └──────┬───────┘         └───────────────┘
          │ USB / serial
          ▼
   ┌──────────────┐
   │   Firefly    │  ESP32-C3 hardware (github.com/firefly)
   │   device     │  displays request → button press → secp256k1 signature
   └──────────────┘
```

**Why the bridge is local:** the Railway API can never reach a USB device in the
operator's hand. The browser talks to a localhost bridge (`apps/firefly-bridge`)
which owns the serial connection to the Firefly. The signature travels
browser → API, and the API verifies it before releasing funds.

## Request flow — small payment (auto-settle)

1. Web posts a payment intent to `POST /payments`.
2. API runs the orchestrator: `get_fx_path` → `check_compliance` →
   `evaluate_policy`.
3. Policy returns `requires_approval = false`.
4. Execution tool submits a direct token Payment on XRPL testnet.
5. Audit tool writes the full decision trail + tx hash to Postgres.
6. Web shows the settled payment with an explorer link.

## Request flow — large/flagged payment (hardware veto)

1. Same intent posting and tool calls.
2. Policy returns `requires_approval = true` (over threshold or AML > flag).
3. Execution tool submits **EscrowCreate** — funds locked on-chain.
4. A pending-approval record is created; the web shows a pending card.
5. Operator clicks "Approve on device". Web asks the local bridge to sign.
6. API builds an **approval challenge** (digest of payment id + escrow details).
   The bridge sends it to the Firefly; the device **displays the request and
   waits for the button press**, then returns a **secp256k1 signature**.
7. Web posts `{ payment_id, signature }` to `POST /payments/{id}/release`.
8. API **verifies the signature** against `FIREFLY_PUBLIC_KEY`. Only on success
   does it submit **EscrowFinish**.
9. Audit tool records the approval payload + signature + release tx hash.

> The verification step at (8) is the whole point. If it is skipped or faked, the
> "hardware veto" is theatre. It must be a real secp256k1 verify against a key
> registered before the demo.

## Request flow — sanctioned counterparty (refused in code)

1. Same intent posting and tool calls.
2. Compliance returns `sanctioned = true`. The policy engine **short-circuits to
   `blocked` before any approval logic** — hardware cannot override a sanctions
   hit.
3. No XRPL transaction is submitted. The payment ends in the terminal `blocked`
   status with a `block_reason`, and a receipt hash is computed.
4. Web shows a refused card. Crucially, the payment does **not** enter the
   approval queue: there is no signature that releases it.

> This is the third terminal outcome alongside `settled` and `released`. It exists
> to prove the boundary cuts both ways — code can refuse a payment the operator
> (or the agent) might otherwise wave through.

## Firefly device specifics

- Hardware: open-source ESP32-C3 device, github.com/firefly.
- Signing curve: **secp256k1** (Ethereum-style). This is why we use a signed
  approval payload verified by the backend (Option C), not XRPL-native multisig
  (XRPL uses ed25519/secp256k1 over its own serialization, which the stock
  Firefly firmware does not produce).
- UX: the device receives a request, renders it on screen, and the operator
  **presses the physical button to confirm**. No button press → no signature →
  funds stay locked. That is the veto.
- Transport: the bridge owns the device connection (USB serial by default). The
  exact framing depends on the firmware build; `apps/firefly-bridge` isolates it
  behind a `FireflyDevice` adapter with a mock implementation for development.

## Data model (Postgres)

Each payment accumulates a complete, queryable decision trail. Minimum columns:

| Field | Source | Notes |
|---|---|---|
| `id` | API | UUID |
| `intent` | request | from, to, amount, currency, reference |
| `route_quote` | routing tool | rate, path summary, fee, dest amount |
| `compliance` | compliance tool | aml_score, sanctioned, flags, explanation |
| `policy_decision` | policy engine | requires_approval, blocked, rule_fired, reasons |
| `status` | workflow | `routing` → `settled` / `pending_approval` → `released`, or terminal `blocked` |
| `block_reason` | policy engine | set when refused (e.g. sanctions hit) |
| `escrow_sequence` | execution | set when locked |
| `approval_signature` | firefly | hex secp256k1 signature (when released) |
| `tx_hash` | execution | settle or finish tx |
| `explorer_url` | execution | testnet explorer link |
| `audit_explanation` | audit tool | LLM-written plain-language summary |
| `receipt_hash` | receipt tool | sha256 of the canonical-JSON receipt; set at every terminal state |
| `created_at` / `updated_at` | API | timestamps |

See `apps/api/app/schemas.py` (Pydantic) and `packages/shared/src/types.ts`
(TypeScript) — keep them mirrored by hand.

## Audit receipt & demo-only endpoints

- `GET /payments/{id}/receipt` — returns the canonical-JSON receipt plus its
  `receiptHash` for any payment in a terminal state (`settled`, `released`,
  `blocked`). An auditor recomputes the hash to verify nothing was altered.
- `POST /payments/{id}/release-tampered` — **DEMO ONLY**, gated by `DEMO_MODE`.
  Rebuilds the approval digest from a tampered copy of the payment (amount ×1000)
  and verifies the *real* signature against it. Always returns `403` — proving the
  signature is bound to the exact payment. It never writes the tampered copy.
- `DEMO_MODE` (config flag) also controls whether the web shows the Tamper button.
  Leave it off outside the demo.

## Network

- XRPL **Testnet** (`wss://s.altnet.rippletest.net:51233`).
- Token: RLUSD if the testnet issuer has enabled trust-line locking
  (`asfAllowTrustLineLocking`); otherwise a self-issued mock USD IOU from a
  wallet we control with SetFlag 17 set. Escrow (XLS-85 TokenEscrow) requires the
  issuer flag either way.
