# Infrastructure Documentation

## Overview

The Autonomous Treasury Agent runs as **two Railway-hosted services plus a
Postgres database**, with a **local-only Node bridge** that talks to a **Firefly
hardware device** over USB/serial. The cloud never touches hardware: all signing
flows through the operator's own machine. Several external HTTP/WebSocket
providers supply FX rates, sanctions screening, audit narration, and XRPL
settlement.

## Components

### Compute

- **API service (`apps/api`)** — Python 3.11 FastAPI app. Built from a
  `DOCKERFILE` builder and started with
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`; health-checked at `/health`
  with `restartPolicyType: ON_FAILURE`. Source of truth:
  `apps/api/railway.json:3-11`, `apps/api/app/main.py:7-31`.
- **Web service (`apps/web`)** — React 18 + Vite dashboard, served as a static
  build on Railway (default demo host `web-production-cba3.up.railway.app`,
  referenced in `apps/api/app/config.py:58`).
- **Firefly bridge (`apps/firefly-bridge`)** — Node 20 + Express, **runs only on
  the operator's local machine**, listening on `http://localhost:4747`
  (`apps/firefly-bridge/src/index.ts:8,84`). It owns the USB/serial link to the
  device. The Railway API never connects to it.

### Data Stores

- **PostgreSQL (Railway)** — provisioned as the persistence tier; the API reads
  `DATABASE_URL` as `postgresql+asyncpg://…` (`apps/api/app/config.py:11`). The
  current demo build keeps payments in an in-memory store
  (`apps/api/app/store.py:12-13`) with SQLAlchemy models staged in
  `apps/api/app/models.py` for the Postgres swap.

### Networking

- **CORS boundary** — the API allows explicit origins (localhost dev ports + the
  Railway web host) plus a regex for regenerated Railway domains
  (`apps/api/app/config.py:55-67`, `apps/api/app/main.py:9-28`).
- **Browser → API** — the dashboard calls the Railway API base
  `https://api-production-c47fd.up.railway.app` (or `localhost:8000` in dev),
  selected at runtime in `apps/web/src/lib/api.ts:11-29`.
- **Browser → local bridge** — the dashboard posts approval requests to
  `http://localhost:4747/sign` (`apps/web/src/lib/firefly.ts:6-17`).

### Security

- **Hardware veto** — release of a locked payment is refused unless an approval
  signature verifies against the registered secp256k1 public key
  (`FIREFLY_PUBLIC_KEY`, `apps/api/app/config.py:35`;
  `apps/api/app/tools/firefly.py:121-137`).
- **Network-bound approval payload** — the signed challenge embeds the XRPL
  network (`xrpl:testnet`), escrow sequence, and EscrowCreate tx hash so a
  testnet signature cannot be replayed on mainnet or redirected to another
  escrow (`apps/api/app/tools/firefly.py:9-51`).
- **Secrets** — wallet seeds and API keys live only in `.env` / Railway
  variables; `.gitignore` blocks `.env` and `*.seed`.

### External Services

- **XRPL testnet** — `wss://s.altnet.rippletest.net:51233`
  (`apps/api/app/config.py:16`) for token Payment, EscrowCreate, EscrowFinish.
  Currently mocked behind `use_mock_xrpl` (`apps/api/app/tools/execution.py`).
- **OpenAI** — `gpt-4o` for the plain-language audit narration only
  (`apps/api/app/tools/audit.py:31-46`); falls back to a deterministic template
  when no key is set.
- **Frankfurter** — fiat FX rates (`apps/api/app/tools/routing.py:79-86`).
- **CoinGecko** — XRP↔fiat rates with a demo-rate fallback
  (`apps/api/app/tools/routing.py:61-76`).
- **OpenSanctions** — receiver screening via `/match/{dataset}`
  (`apps/api/app/tools/compliance.py:86-98`); local demo list is the fallback.

## Relationships

| From | To | Protocol | Purpose |
|------|-----|----------|---------|
| Operator browser | Web service (Railway) | HTTPS | Load dashboard |
| Operator browser | API service (Railway) | HTTPS/JSON | Payment intents, release |
| Operator browser | Firefly bridge (localhost) | HTTP/JSON | Request signature |
| Firefly bridge | Firefly device | USB/serial | Display + button-press sign |
| API service | PostgreSQL | asyncpg/TCP | Persist decision trail (staged) |
| API service | OpenAI | HTTPS | Audit narration |
| API service | Frankfurter | HTTPS | Fiat FX rate |
| API service | CoinGecko | HTTPS | XRP rate |
| API service | OpenSanctions | HTTPS | Sanctions match |
| API service | XRPL testnet | WSS | Settle / escrow / finish (mocked) |

## Environment Differences

- **Local dev:** API on `localhost:8000`, web on Vite `localhost:5173`, bridge on
  `localhost:4747`, `use_mock_xrpl=true`, Postgres optional.
- **Railway (demo/prod):** API and web on `*.up.railway.app`, Postgres
  provisioned; the bridge and device **always remain local** — they are never
  deployed to Railway by design.

## Unverified Items

- **UNVERIFIED:** Postgres is provisioned on Railway per project docs, but the
  running code path uses the in-memory store; the SQLAlchemy session wiring is
  not yet active (`apps/api/app/store.py:1-6`).
