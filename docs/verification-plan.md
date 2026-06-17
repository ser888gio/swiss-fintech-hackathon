# Plan — Verify `main` on real XRPL Testnet, cross-check explorers, report gaps & value-adds

## Context

We consolidated onto `main`. It contains a working-in-mock treasury agent
(FastAPI + React + a mock Firefly bridge) for the SwissHacks Ripple "Future of
Finance" challenge. The challenge scores **viability/feasibility (40%)** and
**technical XRPL use (25%)** the heaviest, and judging hinges on *everything
proven live on Testnet with explorer links* — but `main` currently defaults to
`USE_MOCK_XRPL=true`, so **nothing has been demonstrated on-chain yet**.

The goal of this task: **verify the solution locally, prove the happy paths on
real Testnet, cross-check the same transactions on a second explorer, then write
a gap + value-add report.** No feature code is written until the findings are
approved. The four prioritized value-adds (credentials-as-gate, on-chain
compliance metadata, autonomous AI-agent payments, durable Postgres audit) are
documented as a roadmap in the report, not built in this pass.

Relevant tracks: **cross-border payments & FX**, **AI agents for finance**,
**AI-agent payments**, plus **XRPL Credentials (XLS-70)**.

## Decisions locked

- **Deliverable:** verify + report first; build later.
- **Token strategy:** phased — **XRP first** for a guaranteed green on-chain
  loop, **then real RLUSD** for the cross-border headline, with the RLUSD-escrow
  caveat verified on-ledger.
- **Value-add roadmap to document:** all four selected features.

## Recheck notes (watch-items found while validating against the code)

1. **RLUSD currency code must be 40-char hex.**
   `apps/api/app/tools/execution.py:_token_amount` (and `routing.py`) pass
   `settings.token_currency` raw into `IssuedCurrencyAmount`. XRPL only accepts a
   3-char ISO code or a 160-bit hex code; `"RLUSD"` (5 chars) is invalid, so
   `TOKEN_CURRENCY` for RLUSD must be set to the **hex** form. If a literal 4–6
   char ticker is ever needed, add a small "to currency hex" helper. Confirm
   during step A2.5 before blaming the network.
2. **xrpscan likely has no Testnet view.** `https://xrpscan.com` is
   mainnet-focused and may not resolve Testnet tx hashes at all. For a genuine
   *second-explorer* cross-check on Testnet, use **`https://test.bithomp.com`**
   (Bithomp Testnet) alongside `https://testnet.xrpl.org`. Keep xrpscan for the
   mainnet path-to-mainnet narrative, and note explicitly in the report wherever
   xrpscan cannot resolve a Testnet tx.
3. Validated and accurate: `USE_MOCK_XRPL=true` default (`config.py`); in-memory
   `store.py` with unused `models.py`; mock-only `firefly-bridge/src/device.ts`;
   optional-LLM `tools/audit.py`; credentials gate wiring
   (`verify_kyc → KYC_MISSING_SCORE → policy`); no Memos on settle/escrow txns;
   `xrpl_client.explorer_tx_url` emits only testnet.xrpl.org; `keygen` and
   `smoke_xrpl.py {status,fund,pay}` exist.

## Token strategy rationale

The riskiest on-chain dependency is **escrow of an issued token (XLS-85)**, which
requires the token *issuer* to have set `asfAllowTrustLineLocking`. We don't
control the RLUSD issuer. So:

1. **XRP** proves the *entire* loop today (auto-settle Payment + EscrowCreate +
   EscrowFinish), no trust lines, no issuer dependency → fast guaranteed green.
2. **Real RLUSD** (verified Testnet issuer; currency hex on hand) proves the
   *named challenge primitive* and the cross-border framing (EUR amount → FX rate
   from Frankfurter → settle as RLUSD on XRPL). A non-escrow RLUSD **Payment**
   only needs a receiver trust line, which we can set.
3. We **probe the RLUSD issuer's `asfAllowTrustLineLocking` flag on-ledger**. If
   set → also demo RLUSD escrow. If not → report that the locked/large path stays
   on XRP (or a self-issued IOU where we set the flag), the documented fallback in
   `docs/PLAN.md` risk register.

---

## Phase A — Local verification (the core deliverable)

### A0. Sanity in mock mode + unit tests
- Create/confirm a Python env and install API deps from
  `apps/api/requirements.txt` (root `venv` exists; confirm deps or create
  `apps/api/.venv`). Toolchain present: Python 3.12.2, Node 22.18.
- Run the suite: `cd apps/api && pytest` — expect green for policy, compliance,
  credentials, credential_agent, execution, firefly, receipt, routing.
- Boot mock stack once to confirm health: API (`uvicorn app.main:app --reload`),
  web (`npm run dev:web`), bridge (`npm run dev:bridge`). The `.env` already
  exists — **inspect it without printing seeds**; note current `USE_MOCK_XRPL`
  and which seeds/keys are populated.

### A1. Flip to real Testnet
- Use `apps/api/scripts/smoke_xrpl.py fund` to faucet **treasury**, **receiver**,
  and **credential issuer/subject** wallets (Testnet, no real funds).
- Set in `.env` (local only, never commit): `USE_MOCK_XRPL=false`,
  `XRPL_ENDPOINT=wss://s.altnet.rippletest.net:51233`, the funded
  `TREASURY_WALLET_SEED`, and `FIREFLY_PUBLIC_KEY` from
  `npm run keygen --workspace apps/firefly-bridge` (private key → bridge env,
  public key → API).
- `python scripts/smoke_xrpl.py status` then `... pay <dest> 1` to confirm a real
  XRP tx returns `tesSUCCESS` + a hash before driving the agent.

### A2. Drive every flow on Testnet and capture evidence
Drive via the API/UI and record `txHash` + `explorerUrl` for each:
1. **Small XRP payment → auto-settle** (direct `Payment`,
   `execution.py:execute_payment`).
2. **Sanctioned counterparty → BLOCK in code** (e.g. `ACME-SHELL-CO`); confirm it
   does *not* enter the approval queue (`policy/engine.py` sanctions
   short-circuit).
3. **Large XRP payment → escrow lock** (`EscrowCreate`) → **mock-Firefly release**
   (`EscrowFinish` after `firefly.verify_signature`) → **tamper-reject** via
   `POST /payments/{id}/release-tampered` (set `DEMO_MODE=true`).
4. **Credentials (XLS-70) lifecycle on Testnet** via the credential agent:
   `POST /credentials` (CredentialCreate) → `/accept` (CredentialAccept) →
   `/verify` (on-ledger `AccountObjects` lookup, `lsfAccepted`). Then a payment to
   the credentialed subject auto-settles while an un-credentialed one escalates —
   proving the gate (`CREDENTIAL_KYC_ENABLED=true` for this run).
5. **Real RLUSD settlement Payment** (`TOKEN_CURRENCY` = RLUSD **hex** +
   `TOKEN_ISSUER_ADDRESS` = verified Testnet issuer; receiver `TrustSet` first —
   see Recheck note 1).

### A3. Cross-explorer verification
For each captured `txHash`, open the primary explorer and a second one and
confirm they agree:
- `https://testnet.xrpl.org/transactions/<hash>` (produced by
  `xrpl_client.explorer_tx_url`).
- Second explorer for Testnet: `https://test.bithomp.com/explorer/<hash>`
  (Bithomp Testnet). Try `https://xrpscan.com` too and **record whether it
  resolves the Testnet tx** (see Recheck note 2).
- For each: engine result (`tesSUCCESS`), delivered amount, escrow create/finish
  linkage, and that both explorers show identical state.

### A4. RLUSD issuer escrow-flag probe
- Query the RLUSD issuer's `account_info` flags for `lsfAllowTrustLineLocking` to
  determine whether RLUSD escrow is possible on Testnet today; record the answer
  (drives the large-payment token choice).

### Verification matrix (fill during A2–A4)

| Flow | Tx type | Hash | testnet.xrpl.org | 2nd explorer | Result |
|---|---|---|---|---|---|
| small XRP | Payment | | ✓/✗ | ✓/✗ | tesSUCCESS |
| sanctions | (none) | — | — | — | blocked-in-code |
| large XRP lock | EscrowCreate | | | | |
| release | EscrowFinish | | | | |
| tamper | (none) | — | — | — | 403 rejected |
| credential issue | CredentialCreate | | | | |
| credential accept | CredentialAccept | | | | |
| RLUSD settle | Payment | | | | |

---

## Phase B — Gap & value-add report (`docs/verification-report.md`)

### B1. On-chain proof
The filled verification matrix + explorer links. Notes on any explorer
discrepancy or xrpscan Testnet-coverage gap.

### B2. Gap analysis vs the rubric (file-referenced)
- **Persistence:** `app/store.py` is in-memory; `app/models.py` (SQLAlchemy)
  unused → audit lost on restart; contradicts `docs/architecture.md`. (40% risk.)
- **Hardware:** `apps/firefly-bridge/src/device.ts` is a mock signer only; no real
  USB/serial device → the "hardware veto" is currently software (documented
  fallback — state it honestly).
- **AI thinness:** narration is templated; LLM only optionally writes the audit
  paragraph (`tools/audit.py`). No autonomous payment-initiating agent.
- **On-chain metadata:** settle/escrow txns carry no Memos (no AML score / rule /
  receipt hash on-ledger) — judging notes call for this.
- **RLUSD/credentials defaults:** `CREDENTIAL_KYC_ENABLED=false`, token is a
  self-issued IOU by default; RLUSD needs the hex currency code (Recheck note 1).
- **Explorer coverage:** only testnet.xrpl.org links are generated.

### B3. Value-add roadmap (the four chosen features — documented, not built)
Each with file-level notes, impact (rubric %), and effort:
1. **Credentials as a first-class gate** — default `CREDENTIAL_KYC_ENABLED=true`;
   the orchestrator already wires `credentials.verify_kyc` →
   `compliance.KYC_MISSING_SCORE` → policy escalation; surface
   issue→accept→verify prominently in
   `apps/web/src/pages/CredentialsPage.tsx` and the gated-payment flow; prove on
   Testnet. (The "add credential issuers" ask.)
2. **On-chain compliance metadata** — add `Memos` (AML score, `rule_fired`,
   `receipt_hash`) to `Payment`/`EscrowCreate` in `app/tools/execution.py`; add an
   `xrpscan` URL helper in `app/xrpl_client.py`. (25% technical + verifiability.)
3. **Autonomous AI-agent payments** — new `app/agents/treasury_agent.py` with
   deterministic trigger thresholds whose *only* actuator is
   `orchestrator.process_payment` (no signing, no executor access — invariant I1);
   optional real LLM narration kept strictly outside `app/policy/engine.py`.
   (AI-agents / agent-payments tracks.)
4. **Durable audit (Postgres)** — wire `app/models.py` + an async SQLAlchemy
   session and reimplement the `app/store.py` functions against it (the route
   layer depends only on those functions, so the swap is localized);
   `DATABASE_URL` is already configured. (40% viability.)

### B4. Recommendation
Prioritized build order after approval, mapped to rubric weight and demo beats
(`docs/demo-script.md`).

---

## Out of scope (this pass)
- Building any B3 feature (only after report approval).
- XLS-65/66 Vault/Lending sweep (post-gate stretch; likely Devnet).
- Real Firefly hardware integration (keep the mock signer).
- MPTokens.

## How we'll know it worked
- `pytest` green in `apps/api`.
- Real Testnet `tesSUCCESS` for: small Payment, EscrowCreate, EscrowFinish,
  CredentialCreate, CredentialAccept, and an RLUSD Payment — each with a hash
  resolvable on `testnet.xrpl.org`, cross-checked on a second Testnet explorer.
- Sanctions block and tamper-reject reproduced (no tx for the block; 403 for
  tamper).
- `docs/verification-report.md` written with the filled matrix + gap/roadmap.

## Critical files
- Config/runbook: `.env` (local, secrets), `apps/api/app/config.py`,
  `docs/real-xrpl.md`, `apps/api/scripts/smoke_xrpl.py`.
- XRPL core: `app/tools/execution.py`, `routing.py`, `credentials.py`,
  `compliance.py`, `app/xrpl_client.py`, `app/policy/engine.py`,
  `app/agents/orchestrator.py`, `app/agents/credential_agent.py`.
- Persistence gap: `app/store.py`, `app/models.py`.
- Firefly: `apps/firefly-bridge/src/{index,device,keygen}.ts`.
- Web: `apps/web/src/App.tsx`, `pages/CredentialsPage.tsx`, `pages/TransferPage.tsx`.
