# Running the project

Autonomous Treasury Agent with a Firefly hardware veto, built on XRPL.
Three pieces run independently:

| Service | Path | Port | Where it runs |
|---|---|---|---|
| **API** (FastAPI orchestrator + XRPL + policy) | `apps/api` | `8000` | server / local |
| **Web** (React/Vite dashboard) | `apps/web` | `5173` | server / local |
| **Firefly bridge** (talks to the device) | `apps/firefly-bridge` | `4747` | **local machine only** |

> The bridge is local-only on purpose: it owns the USB/serial link to the Firefly
> device. The API never touches hardware — the signature travels
> `browser → localhost bridge → device → API`, and the API only *verifies* it.

## Prerequisites

- **Python 3.11+** (the API)
- **Node 20+** (web + bridge — see `.nvmrc`)
- **PostgreSQL** — optional. The API runs fine without it (in-memory store);
  Postgres only adds audit durability across restarts.
- A **funded XRPL Testnet wallet** if you want real on-ledger transactions
  (free from the faucet — see "Real Testnet mode" below).

## 1. Environment

All services read configuration from the repo-root `.env`. Copy the template and
fill it in:

```bash
cp .env.example .env
```

Secrets (wallet seeds, API keys) live **only** in `.env` — never commit them
(`.gitignore` already blocks `.env` and `*.seed`).

Key variables:

| Variable | Meaning |
|---|---|
| `XRPL_ENDPOINT` | `wss://s.altnet.rippletest.net:51233` (Testnet) |
| `TREASURY_WALLET_SEED` | funded Testnet wallet — the agent's operating account |
| `TOKEN_CURRENCY` | settlement currency (`XRP`, or a token with `TOKEN_ISSUER_ADDRESS`) |
| `CREDENTIAL_KYC_ENABLED` | `true` requires the receiver to hold an accepted XLS-70 KYC credential |
| `DEMO_MODE` | enables the tamper-proof demo endpoint (`/payments/{id}/release-tampered`) |
| `FIREFLY_PUBLIC_KEY` | secp256k1 pubkey the API verifies approvals against (required to release escrows) |

The web app auto-targets `http://localhost:8000` in local dev, so
`VITE_API_BASE_URL` is optional locally.

## 2. Backend — API (port 8000)

```bash
cd apps/api
python -m venv .venv
. .venv/Scripts/activate          # Windows;  use  . .venv/bin/activate  on macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- Health check: `GET http://localhost:8000/health` → `{"status":"ok"}`
- Interactive API docs: <http://localhost:8000/docs>

## 3. Frontend — Web (port 5173)

From the **repo root** (npm workspaces):

```bash
npm install
npm run dev:web
```

Open <http://localhost:5173>. It calls the API on `:8000`.

## 4. Firefly bridge (port 4747, local only — optional)

Only needed to exercise the hardware-approval release flow.

```bash
npm install                                   # from repo root
npm run keygen --workspace apps/firefly-bridge
```

Flash `FIREFLY_DEVICE_PRIVATE_KEY` onto the Firefly Pixie and copy the printed
`FIREFLY_PUBLIC_KEY` into `.env`. Then start the bridge:

```bash
FIREFLY_DEVICE_PATH=COM3 FIREFLY_PUBLIC_KEY=<hex> npm run dev:bridge
```

The bridge requires a physical device connected at `FIREFLY_DEVICE_PATH`.

## 5. Live transactions (Testnet)

1. Put a funded Testnet seed in `TREASURY_WALLET_SEED`.
2. Verify connectivity and fund a wallet with the smoke-test helper:

   ```bash
   cd apps/api
   python scripts/smoke_xrpl.py status            # endpoint + treasury balance
   python scripts/smoke_xrpl.py fund              # create + fund a faucet wallet
   python scripts/smoke_xrpl.py pay <dest> <xrp>  # send real XRP from the treasury
   ```

3. Drive a payment through the full stack (`POST /payments`). Deterministic policy
   decides the outcome — the LLM never does:
   - **low risk, under threshold** → auto-settles → a real `Payment`.
   - **flagged or ≥ `POLICY_THRESHOLD_USD`** → locked in a real `EscrowCreate`,
     releasable only with a verified Firefly signature (`POST /payments/{id}/release`).
   - **sanctioned counterparty** → blocked outright.

Every transaction returns an explorer link (`https://testnet.xrpl.org/transactions/<hash>`)
so the decision trail is provable on-ledger.

## Ports summary

| Service | URL |
|---|---|
| API | <http://localhost:8000> (`/docs`, `/health`) |
| Web dashboard | <http://localhost:5173> |
| Firefly bridge | <http://localhost:4747> |

See `CLAUDE.md` and `docs/` for architecture, the policy boundary, and the demo
script.
