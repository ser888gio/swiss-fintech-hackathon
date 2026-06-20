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

1. A user posts an intent to `POST /payments`, or the deterministic treasury
   agent fires a due goal and invokes the same orchestrator without a human pay
   click.
2. API runs the orchestrator: `get_fx_path` → `check_compliance` →
   `evaluate_policy`.
3. Policy returns `requires_approval = false`.
4. Execution tool submits a direct token Payment on XRPL testnet.
5. Audit tool writes the full decision trail + tx hash to Postgres.
6. Web shows the settled payment with an explorer link.

For challenge qualification, preserve one evidence chain from `agent_run_id`
and goal to payment id, guardrail trail, validated transaction hash, and explorer
URL. A transaction hash proves settlement, but not that the autonomous agent
initiated it.

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

### Trust-boundary precision

The current Option C design is an **application-enforced cryptographic veto**.
XRPL locks the funds in escrow, and the supported API workflow refuses to call
`EscrowFinish` until the Firefly signature verifies. The signature is not itself
an XRPL escrow condition: a party controlling the treasury signing key could
construct an `EscrowFinish` outside this API after `FinishAfter`. Public claims
should therefore say "the governed workflow cannot release without the device,"
not "the ledger makes release impossible without the device." Crypto-condition
escrow or XRPL multisignature is the future ledger-enforced upgrade.

## Unified guardrail boundary

The orchestrator-facing evaluator is `apps/api/app/policy/guardrail.py`. Callers
fetch facts, the pure evaluator runs only the checks relevant to the context,
and the first failed check returns `block` or `review`.

| ID | Control | Enforcement |
|---|---|---|
| G1 | KYA credential | Required for scoped agent/service contexts |
| G2 | Sanctions | Hard block; no approval path |
| G3 | External AML/VASP enrichment | Placeholder today (`not_wired`) |
| G4 | Agent scope and velocity | Per-tx/day plus configured service restrictions |
| G5 | Delegation budget | Child-agent grant limits |
| G6 | Amount/AML threshold | Auto-settle vs. review/escrow; x402 never enters approval |
| G7 | Firefly veto | Checked at release immediately before `EscrowFinish` |

The separate `apps/api/app/ars/constraint_engine.py` supplies an ARS abstraction
for additional roles. Its G1-G7 labels are not interchangeable with this table.

## Request flow - autonomous x402 service payment

1. An agent requests a service and receives an HTTP 402 requirement.
2. The API validates the network, asset, issuer, facilitator, destination,
   invoice, and positive amount before moving funds.
3. G1 verifies agent identity and G4 checks the complete scope, including rolling
   spend and merchant/service restrictions.
4. G6 evaluates the price before settlement. A review is a no-pay outcome because
   an HTTP service request cannot wait inside an approval queue.
5. Spend is reserved under an agent/idempotency key.
6. The Python API submits the RLUSD Payment with SourceTag and invoice memo.
7. The service is retried with invoice-bound ledger proof and must confirm
   success before the reservation is committed.

The built-in merchant router is a simulated counterparty surface. It can verify
real validated-ledger proof, but it is not an external merchant integration when
running inside the same API deployment.

## Request flow - delegation

1. A parent creates a grant for a child agent wallet.
2. KYA, scope, grant expiry, per-transaction, daily, and total budgets are checked.
3. Real mode funds the child with an XRPL Payment; mock mode returns a synthetic
   hash and no explorer URL.
4. Child payments carry the child identity and scope through the same
   orchestrator and reservation boundary.

## Optional Credit & Lending extension

The trade-finance state machine registers a receivable, withdraws liquidity from
an XLS-65 vault, pays the supplier early at a discount, optionally creates an
XLS-66 loan, and replenishes the pool on repayment. These modules are disabled
by default and support deterministic mock mode. Treat the pillar as demonstrated
only when the verification report contains Devnet transaction hashes and
explorer URLs for the actual Vault/Loan operations.

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
- `GET /payments/{id}/receipt.pdf` — downloads the same terminal decision trail
  as a human-readable audit report. It explains why the deterministic policy
  accepted or refused the payment and includes compliance, guardrails,
  settlement evidence, and the receipt integrity hash.
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
