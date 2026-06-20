# AGENTS.md

This file describes the **agent/tool architecture** of the treasury system — what
each component does, its determinism class, and its contract. It is the
authoritative spec for the orchestration layer.

> Companion file: `CLAUDE.md` holds repo conventions and the hard rule that the
> **LLM never decides policy or signs**. Read it first.

> Challenge authority: [`challenge.md`](challenge.md) is the source of truth for
> challenge scope, deliverables, feature availability, judging weights, and
> event facts. This file remains authoritative for implementation architecture.

## Challenge fit

The primary pillar is **Agent Financial Infrastructure**: at least one payment
is initiated autonomously on XRPL inside deterministic spending, compliance,
approval, and audit guardrails. **Payments & FX** supplies the institutional use
case through RLUSD/issued-token settlement and routing. **Credit & Lending** via
XLS-65/XLS-66 is optional and must not displace the guarded payment MVP.

## Mental model

The product *presents* a team of agents. The implementation uses **one backend
workflow** (`apps/api/app/agents/orchestrator.py`) with a fixed deterministic
tool sequence. `apps/api/app/agents/treasury_agent.py` evaluates scheduled goals
and invokes that workflow as its only payment actuator. The LLM may narrate the
result, but it does not choose the tool order, policy outcome, transaction, or
signature. Every consequential decision is made by deterministic code.

```
payment intent
      │
      ▼
┌──────────────────────────────────────────────┐
│ Treasury Orchestrator (fixed workflow)        │
└──────────────────────────────────────────────┘
   │        │            │            │
   ▼        ▼            ▼            ▼
 routing  compliance   policy      execution / firefly / audit
(determ.) (determ.)  (CODE, not   (determ.)
                      the LLM)
```

## XRPL SDK and research policy

### Python SDK only

All application code that constructs, signs, submits, queries, or decodes XRPL
transactions **must use Python and [`xrpl-py`](https://xrpl.org/docs/tutorials/get-started/get-started-python)**.
Do not add `xrpl.js`, `xrpl4j`, or another XRPL SDK. The React frontend and the
TypeScript Firefly bridge may call the Python API, but they must not become a
second XRPL client or transaction-signing implementation. If an external sample
is written in JavaScript or Java, translate the relevant behavior to `xrpl-py`
and cover it with Python tests.

Keep XRPL network access behind the Python API's tool/client boundary. Never
move transaction construction, wallet seeds, policy evaluation, or signing into
the browser, the LLM prompt, or an MCP server.

### Required research and integration resources

Before implementing or changing XRPL behavior, agents should consult the
official documentation and use the available XRPL research tools. Confirm
transaction fields, amendment/network availability, and `xrpl-py` support; do
not rely on model memory. Record material Testnet/Devnet/Mainnet assumptions in
the relevant plan or verification document.

Installed XRPL agent skills (in `.claude/skills/`, invoke via the Skill tool):

- **`xrpl-payments`** — constructs XRP/RLUSD/IOU/cross-currency/escrow transaction
  objects (SourceTag, Memos, simulate-before-submit). Build with `xrpl-py`.
- **`xrpl-agent-wallet`** — wallet lifecycle and the signing ceremony (no-seed-echo,
  autofill, `submit_and_wait`, untrusted-memo guard). Each carries a
  *project adapter* note: in this repo signing is `xrpl-py` only, server-side,
  and human confirmation is the Firefly + policy boundary — not an interactive
  chat prompt. Use the skills for discipline and patterns; obey the adapter.

Core references and discovery tools:

- [XRPL documentation and API reference](https://xrpl.org/docs)
- [Open Source Ripple documentation](https://opensource.ripple.com)
- [XRPL resources index](https://linktr.ee/rippledevrel)
- [Context7 XRPL search/MCP](https://context7.com/?q=xrpl) — use for current,
  source-grounded library and protocol context
- [XRPL AI tools, Skills, and MCP resources](https://xrpl.org/resources/dev-tools/ai-tools)
- [RippleDevRel sample scripts](https://github.com/RippleDevRel/xrpl-js-python-simple-scripts)
  — use only the Python/`xrpl-py` examples or port the behavior to Python
- [XRPL CLI (`xrpl-up`)](https://github.com/ripple/xrpl-up) — environment and
  node/dev tooling only; production transaction logic remains in `xrpl-py`

Agent-payment and wallet resources to use when the corresponding integration is
in scope:

- [XRPL x402 facilitator](https://xrpl-x402.t54.ai/#setup)
- [x402Secure Service](https://www.x402secure.com/)
- [Claw Credit](https://www.claw.credit)
- [x402 XRPL SDK](https://github.com/t54-labs/x402-xrpl) — integration reference
  or external service boundary only; do not introduce a JavaScript XRPL runtime
  into this repository
- [RLUSD CLI](https://github.com/t54-labs/rlusd-cli) — development and
  verification aid, not the application's transaction engine
- [RLUSD Agent Skills](https://github.com/t54-labs/rlusd-skills)
- [OpenWallet Standard](https://openwallet.sh)

RLUSD references:

- [RLUSD stablecoin documentation](https://docs.ripple.com/products/stablecoin)
- [RLUSD Testnet faucet](https://tryrlusd.com) — Testnet only, not Devnet

Wallet testing:

- Use [Crossmark](https://crossmark.io) or
  [GemWallet](https://gemwallet.app) for manual browser-wallet, connection,
  authorization, and user-signing tests. Do not introduce or recommend another
  browser wallet without updating this policy.
- Use dedicated Testnet/Devnet accounts with faucet funds only. Never import the
  treasury seed, credential-issuer seed, Firefly key, or any production key into
  a browser extension.
- Treat wallet approval as a user-facing integration test, not as a replacement
  for the Python API, deterministic policy engine, or Firefly approval flow.
  XRPL application logic and server-submitted transactions remain implemented
  with `xrpl-py`.
- Record the wallet name, network, account, transaction hash, and explorer URL in
  the relevant verification report. Never commit recovery phrases or secrets.

These resources can inform implementation, verification, and interoperability,
but none may bypass this repository's deterministic policy boundary, Python API,
credential checks, Firefly approval verification, or audit trail.

## Components

| Component | Determinism | Module | Responsibility |
|---|---|---|---|
| **Treasury Orchestrator** | LLM loop | `app/agents/orchestrator.py` | Receives a payment intent, calls tools in order, narrates decisions. Holds **no** policy logic. |
| **Routing tool** `get_fx_path` | Deterministic | `app/tools/routing.py` | Frankfurter FX quote + XRPL `ripple_path_find`; returns the cheapest path summary. |
| **Compliance tool** `check_compliance` | Deterministic (mock OK) | `app/tools/compliance.py` | Sanctions/KYC screen + AML score 0–100 + plain-language reason. Folds in the credential status. |
| **Credentials tool** `verify_kyc` / `issue_credential` | Deterministic | `app/tools/credentials.py` | XRPL Credentials (XLS-70): issues KYC credentials and verifies the receiver holds an accepted, non-expired one. Reports status only — escalation is the policy engine's call. |
| **Public intelligence tool** `assess_public_intel` | Deterministic facade, agent-ready | `app/tools/public_intel.py` | Returns an advisory OSINT risk result. Future AI agents may gather evidence, but code computes the score and policy effect. |
| **Policy engine** | **Deterministic — code-enforced** | `app/policy/engine.py` | Threshold + risk-score decision: auto-settle vs. escalate. **Never the LLM's call.** |
| **Execution tool** | Deterministic | `app/tools/execution.py` | Direct token Payment, or escrow/lock for large payments. |
| **Firefly approval tool** | Deterministic | `app/tools/firefly.py` | Builds the approval challenge, verifies the Firefly signature, then triggers release. |
| **Audit tool** | LLM-assisted | `app/tools/audit.py` | Writes a human-readable explanation of each decision to Postgres. |
| **Shared wallet tool** | Deterministic, read-only | `app/tools/wallet.py` | Derives only the configured treasury public address server-side and reads its XRP/token balances and validated transaction history from Testnet and Devnet. |
| **x402 service-payment tool** | Deterministic | `app/tools/x402.py` | Fetches and validates a 402 requirement, submits a direct RLUSD Payment with `xrpl-py`, and retries with invoice-bound ledger proof. Policy and agent reservations are enforced by the orchestrator before settlement. |
| **Simulated merchant router** | Deterministic | `app/routes/merchants.py` | Represents five distinct counterparties inside the existing API deploy and releases resources only after exact validated-ledger verification. |

## The policy boundary (the core innovation)

### Unified guardrails

`app/policy/guardrail.py` is the orchestrator-facing source of truth. Callers
pre-fetch facts and pass them into a pure evaluator. It dispatches only the
checks relevant to the workflow context, returns an ordered `guardrail_trail`,
and stops at the first block or review result.

| Guardrail | Meaning | Current status |
|---|---|---|
| **G1 KYA** | Agent holds the required accepted credential | Wired for service payments, delegation funding, and loan underwriting |
| **G2 sanctions** | Counterparty is not sanctioned | Wired as a hard block for payments and applicable financial contexts |
| **G3 AML enrichment** | External VASP/AML enrichment | Placeholder (`reason=not_wired`); do not claim a live provider |
| **G4 scope** | Amount, velocity, host/type and configured agent restrictions | Wired; spend reservations provide retry/concurrency safety |
| **G5 delegation** | Child spend fits the remaining grant | Wired for delegation and delegated-agent paths |
| **G6 threshold** | Amount/AML threshold determines allow vs. review | Wired; review becomes escrow/Firefly for payments and a no-pay result for x402 |
| **G7 hardware veto** | Release requires the registered Firefly signature | Enforced in `release_payment`, immediately before `EscrowFinish` |

Current dispatch contexts include `payment`, `agent_payment`,
`service_payment`, `delegation_fund`, `loan_underwrite`, and
`insurance_payout`. The separate `app/ars/constraint_engine.py` implements an
ARS abstraction with different G1-G7 labels; do not conflate its numbering with
the orchestrator-facing dispatcher.

### Extended components

| Component | Determinism | Module | Responsibility |
|---|---|---|---|
| **Autonomous treasury agent** | Deterministic; optional LLM narration | `app/agents/treasury_agent.py` | Evaluates scheduled goals and invokes the orchestrator as its only payment actuator. |
| **Agent scope engine** | Deterministic, pure | `app/policy/scope.py` | Enforces transaction/day limits and optional host, service, asset, network, category, and merchant restrictions. |
| **KYA credentials** | Deterministic | `app/credentials/kya/` | Issues and verifies scoped agent identities using XRPL Credentials. |
| **Delegation tool** | Deterministic | `app/tools/delegation.py` | Funds child wallets and enforces expiry, per-transaction, daily, and total grants. |
| **Reservation system** | Deterministic | `app/store.py`, `app/ars/` | Reserves, commits, or releases spend so retries and concurrent runs cannot silently reuse allowance. |
| **Trade finance** | Deterministic; optional | `app/tools/trade_finance.py` | Receivable registration, early supplier payment, repayment, and optional Vault/Loan operations. |
| **Vault and lending** | Deterministic; optional Devnet extension | `app/tools/vault.py`, `app/tools/lending.py` | Constructs XLS-65/XLS-66 transactions in real mode; disabled by default and not demonstrated without explorer evidence. |
| **Insurance / Cover** | Deterministic pricing and policy; optional | `app/insurance/`, `app/cover/` | Extends the same control boundary to agent risk cover; not part of the guarded-payment MVP. |

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
- `get_overview() -> WalletOverview` — read-only `{ address, fetched_at, networks[] }`, where each network contains its independent funds, recent validated transactions, and explorer links.
- `fetch_requirement(service_url) -> X402PaymentRequirement` — performs the
  initial GET and validates asset, issuer, network, facilitator, and positive
  amount without moving funds.
- `settle_x402(requirement) -> X402Settlement` — submits the direct RLUSD
  Payment with SourceTag and invoice memo after the orchestrator's full-scope
  policy gate and agent-keyed reservation.
- `retry_with_proof(requirement, settlement) -> ServiceResponse` — retries with
  the invoice-bound transaction proof and requires a successful merchant response.

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
5. Use only Python + `xrpl-py` for XRPL application logic. Do not introduce a
   second XRPL SDK in the web or bridge packages.
6. Use the official XRPL docs, Context7 XRPL MCP/search, and the relevant tools
   listed above before changing protocol behavior; verify network/amendment
   availability and return explorer evidence.
7. Use only Crossmark or GemWallet for browser-wallet testing, with isolated
   faucet-funded accounts and no repository or production secrets.
