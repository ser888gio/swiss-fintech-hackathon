# Verification report — `main` on XRPL Testnet

Status of the plan in `docs/verification-plan.md`. Network: XRPL **Testnet**
(`wss://s.altnet.rippletest.net:51233`). Treasury (reused fx-sentinel HOT
wallet): **`rLJEyCHnzFqVyqRKKtb76NN1scRMWimtGM`**, ~203 XRP funded.

`main`'s `apps/api` was wired to Testnet via a gitignored `apps/api/.env`
(`USE_MOCK_XRPL=false`, `TOKEN_CURRENCY=XRP`, treasury = HOT seed) — the root
`.env` (fx-sentinel schema) was left untouched.

## B1. On-chain proof (verification matrix)

| Flow | Tx type | Hash | testnet.xrpl.org | Result |
|---|---|---|---|---|
| small EUR→XRP | Payment | `BD59872F…81C7C14` | [link](https://testnet.xrpl.org/transactions/BD59872F3096AE7C9C81960FCFC8F0C45AA64238D9F61421978C5664181C7C14) | **settled** (auto, AML 10) |
| sanctioned party | (none) | — | — | **blocked in code** (rule `sanctions_block`, no tx) |
| large/flagged lock | EscrowCreate | `CEBBC6CA…909885B` | [link](https://testnet.xrpl.org/transactions/CEBBC6CA73FA7462424D666864EB4DE45FF18B0A5FFEAD4E7EB72715B909885B) | **pending_approval** (AML 95, seq 18160807) |
| release | EscrowFinish | `F0E5E45F…344AAEEB` | [link](https://testnet.xrpl.org/transactions/F0E5E45F3E917EF6AA2908C0353578EABCE4FCE78AABDB7DAFC6AC85344AAEEB) | **released** after verified secp256k1 signature |
| tamper & retry | (none) | — | — | **403 rejected** — signature fails vs altered payment |
| credential issue | CredentialCreate | — | — | **pending** (needs issuer/subject seeds + `CREDENTIAL_KYC_ENABLED=true`) |
| credential accept | CredentialAccept | — | — | **pending** |
| RLUSD settle | Payment | — | — | **pending** (needs RLUSD hex currency + receiver trust line) |

Unit tests: **41/41 pass** (`apps/api`).

Notes:
- The Firefly device was simulated with an `eth_keys` secp256k1 signer in Python
  (the documented simulator fallback) — it exercises the *exact* server-side
  verification path (`firefly.verify_signature` against `FIREFLY_PUBLIC_KEY`).
- Second explorer: **xrpscan.com has no Testnet view**, so use
  **`https://test.bithomp.com`** as the cross-check explorer for these hashes.

## B2. Gap analysis (file-referenced)

### Bugs found (escrow path had never run on a live network)
Two defects blocked the escrow centerpiece end-to-end; both **fixed and committed
to `main`** (see `apps/api/app/tools/execution.py`):
1. **`apps/api/app/tools/execution.py:lock_payment`** used `await sign(...)`, but
   `sign` is **synchronous** in `xrpl-py` 4.x → `TypeError: object EscrowCreate
   can't be used in 'await' expression`. Fixed: `signed = sign(await autofill(...))`.
2. **`finish_after = now + 1s`** in the same function lands in the *past* by the
   time the tx is applied (~4s later) → **`tecNO_PERMISSION`**. Fixed: +9s margin.

### Policy threshold semantics (real design gap)
- `app/agents/orchestrator.py` calls `engine.evaluate(route.dest_amount, …)`
  **without passing `policy_threshold_usd`**, so the `POLICY_THRESHOLD_USD` env
  override (`config.py`) is **dead code**, and the `10_000` threshold is compared
  against the **settle-currency amount (XRP), not USD**. With a small XRP
  treasury the amount-threshold path can't be exercised; escalation was proven via
  the **AML-score** path instead. Recommend: feed a USD-normalized amount and wire
  the configurable threshold.

### Other gaps vs the rubric
- **Persistence:** `app/store.py` is in-memory; `app/models.py` (SQLAlchemy) is
  unused → audit trail lost on restart; contradicts `docs/architecture.md`.
- **Config mismatch:** `main`'s `apps/api` doesn't read the existing `.env`
  (fx-sentinel schema). Bridged via `apps/api/.env`; RLUSD/credentials still need
  wiring (RLUSD currency must be the **40-char hex**, not `"RLUSD"` —
  `execution.py:_token_amount` passes it raw to `IssuedCurrencyAmount`).
- **Hardware:** `apps/firefly-bridge/src/device.ts` is a mock signer only; no real
  USB/serial device. State the simulator fallback honestly.
- **AI thinness:** narration is templated; LLM only optionally writes the audit
  paragraph (`tools/audit.py`). No autonomous payment-initiating agent.
- **On-chain metadata:** settle/escrow txns carry no `Memos` (no AML score / rule
  / receipt hash on-ledger).
- **Explorer coverage:** only testnet.xrpl.org links generated; no second explorer.

## B3. Value-add roadmap (documented, not built)
1. **Credentials as a first-class gate** — default `CREDENTIAL_KYC_ENABLED=true`;
   the orchestrator already wires `credentials.verify_kyc` →
   `compliance.KYC_MISSING_SCORE` → policy escalation; surface issue→accept→verify
   in `apps/web/src/pages/CredentialsPage.tsx`; prove on Testnet.
2. **On-chain compliance metadata** — add `Memos` (AML score, `rule_fired`,
   `receipt_hash`) to `Payment`/`EscrowCreate` in `app/tools/execution.py`; add an
   xrpscan/bithomp URL helper in `app/xrpl_client.py`.
3. **Autonomous AI-agent payments** — new `app/agents/treasury_agent.py` with
   deterministic triggers whose only actuator is `orchestrator.process_payment`
   (no signing, no executor access); optional LLM narration outside the gate.
4. **Durable audit (Postgres)** — wire `app/models.py` + async SQLAlchemy session;
   reimplement `app/store.py` against it (route layer depends only on those funcs).

## B4. Recommendation
Strongest demo for the 40%/25% rubric, in order:
1. Land the two escrow fixes (above) — the hardware-veto loop is the innovation
   centerpiece and now works on-chain.
2. Wire the policy threshold to a USD-normalized amount (kills the dead-config gap).
3. Finish the **credentials** and **RLUSD** Testnet flows to complete the matrix.
4. Then build B3 features in roadmap order (credentials gate → memos → Postgres →
   autonomous agent).

## Reproduce
```
# deps (one-time)
venv/Scripts/python.exe -m pip install -r apps/api/requirements.txt
# tests
cd apps/api && ../../venv/Scripts/python.exe -m pytest -q
# Testnet wiring lives in apps/api/.env (gitignored): USE_MOCK_XRPL=false, XRP
../../venv/Scripts/python.exe scripts/smoke_xrpl.py status
```
