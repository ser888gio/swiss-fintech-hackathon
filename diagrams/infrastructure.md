# Infrastructure Documentation

## Overview

The system is an **Autonomous Treasury Agent on XRPL** deployed as two Railway
services (Python API + React web) backed by a Railway PostgreSQL database, plus a
**local-only Firefly hardware bridge** that never runs in the cloud. The cloud
services are stateless request handlers; durability lives in Postgres and the
true source of money is the XRP Ledger (Testnet/Devnet). Hardware signing is
deliberately kept off the cloud — the browser reaches the Firefly device only
through a bridge on the operator's own machine.

## Components

### Compute

- **API service (`apps/api`)** — FastAPI/uvicorn container. `apps/api/Dockerfile`
  builds from `python:3.11-slim`, installs `requirements.txt`, and runs
  `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`
  (`apps/api/Dockerfile:11`). Deployed via `apps/api/railway.json`. Hosts the
  orchestrator, policy/guardrail engine, XRPL client, compliance, and audit store.
  Demo origin: `https://api-production-c47fd.up.railway.app`
  (`apps/web/src/lib/api.ts:54`).
- **Web service (`apps/web`)** — Two-stage `apps/web/Dockerfile`: a `node:20-slim`
  build stage runs `npm run build --workspace apps/web` (Vite); a serve stage runs
  `serve -s dist -l ${PORT:-3000}` (`apps/web/Dockerfile:21-26`). Build args
  `VITE_API_BASE_URL` / `VITE_BRIDGE_BASE_URL` are inlined at build time
  (`apps/web/Dockerfile:15-18`). The root `railway.json` points the deploy at this
  Dockerfile with healthcheck `/`. Demo origin:
  `https://web-production-cba3.up.railway.app`.
- **Firefly bridge (`apps/firefly-bridge`)** — **Local machine only.** Node/Express
  server on port `4747` (`apps/firefly-bridge/src/index.ts:8`). Owns the USB/serial
  connection to the Firefly Pixie (`SerialFireflyDevice`). Exposes `/health`
  and `/sign`. The Railway API never connects to hardware — by design.
- **Firefly Pixie device** — Physical secp256k1 signer. Displays the human-readable
  approval request and signs only on a physical button press.

### Data Stores

- **PostgreSQL (Railway)** — Async SQLAlchemy + `asyncpg`, configured via
  `DATABASE_URL` (`apps/api/app/config.py:23`). `init_db` runs `create_all` plus
  additive `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations at startup
  (`apps/api/app/db.py:29-78`). Tables (`apps/api/app/models.py`): `payments`,
  `agent_logs`, `credentials`, `credential_logs`, `spend_reservations`,
  `audit_events`, `service_payments`, `delegation_grants`, `receivables`,
  `insurance_premiums`, `insurance_payouts`, `agent_risks`, `agents`,
  `agent_spend_reservations`, `treasury_goals`, `treasury_agent_runs`. On startup
  the in-memory store is rehydrated from the DB (`apps/api/app/main.py:18-24`).
  Graceful degradation: if the DB is unreachable the API runs in-memory only
  (`apps/api/app/db.py:79-84`).

### Networking

- **CORS / edge** — The API allows the Railway web origin, local Vite dev ports,
  and a regex for `*.up.railway.app`, `*.railway.app`, and `*.pages.dev`
  (Cloudflare Pages) (`apps/api/app/main.py:30-59`, `config.py:264-273`). A custom
  500 handler re-adds CORS headers so server errors stay visible to the browser
  (`main.py:86-99`).
- **Browser → bridge** — The web app calls `http://localhost:4747/sign` directly
  from the operator's browser (`apps/web/src/lib/firefly.ts:6`), bypassing the
  cloud entirely for the signing step.
- **API ↔ XRPL** — WebSocket (`AsyncWebsocketClient`) to XRPL Testnet
  (`wss://s.altnet.rippletest.net:51233`) and Devnet
  (`wss://s.devnet.rippletest.net:51233`) (`config.py:28-32`,
  `xrpl_client.py:57-61`). Credential, vault, and lending endpoints can point at a
  different network than settlement (`config.py:39,147,206`).

### Security

- **Hardware veto** — Release of an escrowed payment is refused unless a secp256k1
  signature verifies against `FIREFLY_PUBLIC_KEY`
  (`apps/api/app/tools/firefly.py:121-137`). The signed digest binds network +
  payment id + owner + destination + amount + escrow sequence + escrow-create tx
  hash, preventing fund redirection or cross-network replay (`firefly.py:33-51`).
- **Secrets** — Wallet seeds, issuer seeds, OpenAI/Plaid/OpenSanctions keys, and
  the Firefly key live only in environment / Railway variables, never in the repo
  (`config.py`). All flows require real wallet credentials.

### External Services

- **XRP Ledger (Testnet / Devnet)** — settlement, escrow (XLS-85 TokenEscrow),
  pathfinding, XLS-70 Credentials, XLS-33 MPTokens, XLS-65 vault, XLS-66 lending.
  `xrpl-py` only (`xrpl_client.py`, `tools/execution.py`).
- **OpenAI API** — `gpt-4o` for audit narration only; never decides policy
  (`config.py:25-26`).
- **Frankfurter FX API** (`https://api.frankfurter.dev/v1`) — FX rates for USD
  normalisation (`config.py:65`).
- **OpenSanctions API** + **Plaid** (Monitor watchlists + Identity Verification) —
  AML / sanctions / PEP screening (`config.py:67-91`).
- **t54 x402 facilitator** (`https://xrpl-facilitator-testnet.t54.ai`) — agent
  pay-at-need settlement for HTTP 402 services (`config.py:157-162`).
- **RLUSD issuer** — issued-currency settlement asset (`config.py:35-36`).

## Relationships

| From | To | Protocol / Purpose |
|------|-----|--------------------|
| Browser (web app) | Web service (Railway) | HTTPS — static dashboard |
| Browser | API service (Railway) | HTTPS/JSON — payments, treasury, credentials |
| Browser | Firefly bridge (localhost:4747) | HTTP — request hardware signature |
| Firefly bridge | Firefly Pixie | USB/serial — sign on button press |
| API service | PostgreSQL | asyncpg — durable audit trail |
| API service | XRPL Testnet/Devnet | WebSocket — submit/query tx, escrow |
| API service | OpenAI | HTTPS — narration |
| API service | Frankfurter | HTTPS — FX rates |
| API service | OpenSanctions / Plaid | HTTPS — AML screening |
| API service | t54 x402 facilitator | HTTPS — x402 settlement |

## Environment Differences

- **Production default**: `testnet_settlement_scale=1.0`,
  `firefly_confirmation_enabled=true`, `demo_mode=false`. Mainnet
  (`xrpl_network=xrpl:0`) always fails closed — the Firefly bypass is ignored
  (`orchestrator.py:133-138`).
- **Demo/testnet**: `demo_mode=true` enables red-team routes; the non-production
  Firefly bypass can settle escalations directly on Testnet/Devnet only;
  `testnet_settlement_scale` shrinks the on-ledger amount so large intents are
  fundable while policy/approval keep the true figure (`config.py:116-130`).

## Unverified Items

- Cloudflare Pages is referenced in CORS but no Pages build config exists in-repo;
  the web service is built and served from Railway. UNVERIFIED whether a parallel
  Pages deployment is active.
- Per `MEMORY.md`, deploys are done via `railway up` CLI upload with GitHub sources
  disconnected; not reflected in committed config.
