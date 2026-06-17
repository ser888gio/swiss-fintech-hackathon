# fx-sentinel — build roadmap

Forward plan for the Claude Code web session. `main` is a compliance-gated FX
treasury agent on XRPL (FastAPI `apps/api`, Vite `apps/web`, mock Firefly bridge
`apps/firefly-bridge`). See `docs/verification-report.md` for the on-chain
evidence and findings this plan builds on.

## Status (verified this session)
- **5/8 core flows proven on Testnet/in-code:** small auto-settle, sanctions block,
  escrow lock → Firefly-verified release → tamper-reject. 41/41 unit tests pass.
- **Two escrow fixes landed** in `apps/api/app/tools/execution.py` (`await sign`→sync
  `sign`; `finish_after` +1s→+9s).
- Treasury wired to Testnet via gitignored `apps/api/.env` (reuses fx-sentinel
  funded wallets; HOT holds 423 RLUSD).

## Invariants to preserve in every phase
main's determinism boundary: the LLM **orchestrates and narrates only — it never
decides policy or signs**. Policy lives in `app/policy/engine.py` (pure,
unit-tested); signing/verification in `app/tools/{execution,firefly}.py`; audit is
append-only; secrets stay in gitignored env only.

## Phase 1 — Finish the Testnet verification matrix
Recon: HOT holds 423 RLUSD; subject CP_NEW (`rnt6…pRqv`) already has an RLUSD trust
line; issuer = COMPLIANCE_ISSUER (`rEF5…6uew`); RLUSD hex
`524C555344000000000000000000000000000000`, issuer
`rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV`.
1. **Credentials (XLS-70)** via `app/agents/credential_agent.py`: issue → accept →
   verify; capture CredentialCreate + CredentialAccept hashes; prove the gate
   (credentialed subject auto-settles, un-credentialed escalates). Wire
   `CREDENTIAL_*` in `apps/api/.env`.
2. **RLUSD settlement Payment** HOT→CP_NEW (`TOKEN_CURRENCY` = RLUSD hex,
   `TOKEN_ISSUER_ADDRESS` = issuer). Finding to record: routing has no real FX path
   for RLUSD (`base==quote` short-circuit) — addressed in Phase 2.2.

## Progress log
- **Phase 5 — landed.** New `app/tools/mptoken.py` (MPTokenIssuanceCreate / MPTokenAuthorize / mint_attestation,
  mock + real paths, same shape as vault.py). xrpl-py 4.5.0 ships `MPTokenIssuanceCreate`,
  `MPTokenAuthorize`, and `MPTAmount` (for Payment). The COMPLY issuance uses no transfer flags —
  soulbound compliance badge. Mock mode: full flow in-memory (create, authorize, mint).
  Real mode: MPTokenIssuanceCreate lands on Testnet (XLS-33 is available on Testnet);
  MPTokenAuthorize submits from treasury; mint is simulated unless `MPT_RECIPIENT_ADDRESS` +
  `MPT_RECIPIENT_SEED` are configured (recipient must have opted in first).
  Treasury agent `run()` now calls `_mint_compliance_attestation()` after each auto-settled
  payment when `mpt_enabled=True` — deterministic, never the LLM.
  New routes: `GET /treasury/mpt`, `POST /treasury/mpt/issuance`,
  `POST /treasury/mpt/authorize`, `POST /treasury/mpt/mint`. MPT section added to TreasuryPage.
  13 new tests (106/106 total pass). TypeScript typecheck clean.
- **Phase 3 — landed.** New `app/tools/vault.py` (VaultCreate / VaultDeposit / VaultWithdraw,
  mock + real paths, same shape as execution.py). xrpl-py 4.5.0 ships these classes natively;
  real-mode transactions go to `VAULT_XRPL_ENDPOINT` (Devnet by default — XLS-65 is not yet
  on Testnet). In-memory vault state tracks `deposited`, `shares`, `wallet_balance` for the
  mock demo. Treasury agent `run()` now calls `_vault_sweep()` on each cycle (deterministic:
  deposit excess above `vault_sweep_threshold_usd`, recall when below `vault_recall_threshold_usd`).
  New routes: `GET/POST /treasury/vault`, `POST /treasury/vault/deposit`,
  `POST /treasury/vault/withdraw`. Vault section added to TreasuryPage. 13 new vault tests
  (93/93 total pass). Both TS packages typecheck clean.
- **Phase 4 — landed.** `SerialFireflyDevice` added to `apps/firefly-bridge/src/device.ts`:
  newline-delimited JSON serial protocol (ESP32-C3, secp256k1); `DEVICE_MODE=hardware|simulator`
  selects the adapter; `BRIDGE_SERIAL_PORT` + `FIREFLY_PUBLIC_KEY` required in hardware mode.
  Simulator (`MockFireflyDevice`) continues to work unchanged — same env vars, same keygen script.
  Server-side `firefly.verify_signature` is **untouched** (signature + public-key byte format is
  identical). README updated with serial protocol contract and hardware setup instructions.
  80/80 backend tests pass; both TS packages typecheck clean.
- **Phase 2.2 — landed in code (Testnet proof pending network access).** Fixed the
  dead `POLICY_THRESHOLD_USD`/`POLICY_COMPLIANCE_FLAG_SCORE`: the orchestrator now
  USD-normalizes the amount (`routing.convert_to_usd`) and passes the configured
  threshold + flag score to `engine.evaluate`. Added on-ledger compliance `Memos`
  (AML score, `rule_fired`, pre-submission `receipt_hash`) to the auto-settle Payment
  and the EscrowCreate via `execution.ComplianceMemo` + `build_memo_fields`
  (dependency-free, unit-tested) and `receipt.compute_decision_hash` (stable before
  submission). Added the second explorer (`xrpl_client.bithomp_tx_url`) surfaced as
  `Payment.explorerUrlSecondary`. **49/49 unit tests pass.** Still TODO on a funded
  Testnet: submit one settle + one escrow and confirm the Memos + both explorer
  links resolve.

## Phase 2 — value-add features
1. **Credentials as a first-class gate** — default `CREDENTIAL_KYC_ENABLED=true`;
   orchestrator already wires `credentials.verify_kyc` → `compliance.KYC_MISSING_SCORE`
   → policy escalation. Surface issue→accept→verify in
   `apps/web/src/pages/CredentialsPage.tsx` + the gated-payment flow.
2. **On-chain compliance metadata** — add `Memos` (AML score, `rule_fired`,
   `receipt_hash`) to `Payment`/`EscrowCreate` in `app/tools/execution.py`; add an
   xrpscan/bithomp URL helper in `app/xrpl_client.py`. Also fix the dead
   `POLICY_THRESHOLD_USD`: the orchestrator must pass a USD-normalized amount + the
   configured threshold to `engine.evaluate` (today it passes `route.dest_amount`
   in the settle currency and ignores the config).
3. **Autonomous AI-agent payments** — new `app/agents/treasury_agent.py`: goals +
   deterministic trigger thresholds whose ONLY actuator is
   `orchestrator.process_payment` (no signing, no executor access). Optional LLM
   narration kept strictly outside `app/policy/engine.py`.
4. **Durable audit (Postgres)** — wire `app/models.py` + an async SQLAlchemy
   session; reimplement `app/store.py` against it (route layer depends only on those
   functions, so the swap is localized). `DATABASE_URL` already configured.

## Phase 3 — XLS-65 Single Asset Vault + XLS-66 Lending
Idle-treasury sweep: agent deposits excess RLUSD into a Single Asset Vault for
yield, withdraws when liquidity is needed; narrate each step.
- New `app/tools/vault.py`: `VaultCreate`/`VaultDeposit`/`VaultWithdraw` (mock + real
  paths, same shape as `execution.py`); deterministic trigger in the autonomous
  agent (Phase 2.3) — never the LLM.
- **Network caveat:** XLS-65/66 are likely **Devnet-only** today — verify amendment
  status via the xrpl.org MCP / explorer Amendments page first; if absent on
  Testnet, run on Devnet (`wss://s.devnet.rippletest.net:51233`).
- Post-core: must not destabilize the payment/escrow demo.

## Phase 4 — Real Firefly hardware
Replace the mock signer while keeping the simulator fallback.
- Extend `apps/firefly-bridge/src/device.ts` with a `serialport`-based
  `FireflyDevice` adapter (ESP32-C3, secp256k1); `DEVICE_MODE=hardware|simulator`
  selects it (mirror the fx-sentinel `BRIDGE_SERIAL_PORT`/`DEVICE_MODE` env
  convention). The device displays the WYSIWYS payload and signs on a physical
  button press; the **server-side verify path is unchanged**
  (`firefly.verify_signature` vs `FIREFLY_PUBLIC_KEY`). Always keep the simulator
  working — never demo without it.
- Confirm the device's signature/key format matches `eth_keys` verification (curve,
  encoding); normalize if needed.

## Phase 5 — MPTokens (XLS-33)
Use MPTokens for a compliance/settlement artifact (e.g., a per-payment compliance
attestation token, or an MPT-denominated settlement asset).
- New issuance path (`MPTokenIssuanceCreate` + holder authorize); decide the use
  case (compliance metadata vs settlement asset) before coding.
- **Network/amendment caveat:** verify MPToken availability on the target network
  via MCP first. Escrow of an MPT additionally needs `tfMPTCanEscrow`.

## Sequencing & rationale
Rubric weights: viability 40%, technical XRPL 25%, innovation 20%, UX 15%. Build
order: **1 (finish matrix) → 2.2 + 2.1 (memos + credentials gate) → 2.4 (Postgres) →
2.3 (autonomous agent) → 4 (real Firefly) → 3 (vaults) → 5 (MPTokens)**. Phases 3
and 5 are amendment-gated and may need Devnet — verify first. Never cut the
policy-gate tests, the VETO hardware path, or the simulator fallback.

## Verification (per phase)
- Unit tests green (`apps/api` pytest); policy gate keeps table-driven coverage.
- Each XRPL feature proven on the target network with `tesSUCCESS` + explorer links
  (testnet.xrpl.org primary, test.bithomp.com secondary; xrpscan has no Testnet view).
- Invariants asserted in code + tests (LLM never signs/decides; audit append-only).
