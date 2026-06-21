# Infrastructure Overview (Simplified)

## System Summary

The Autonomous Treasury Agent runs as two **Railway**-hosted containers (a Python
API and a React web app) on a managed **PostgreSQL** database, while a **local-only
Node bridge** keeps the **Firefly hardware** signer off the cloud. The API talks to
the **XRP Ledger** and a handful of HTTPS providers for FX, screening, and AI
narration.

## Major Components

### Web App (React/Vite on Railway)
**Purpose**: Operator dashboard for payments, treasury, insurance, and approvals.
**Contains**: Static Vite build served by `serve`; API base + bridge URL inlined at build.

### API Service (Python/FastAPI on Railway)
**Purpose**: Deterministic orchestrator, policy/guardrail engine, XRPL client, audit store.
**Contains**: Routes, tools, policy boundary, compliance, insurance/cover engines.

### Database (PostgreSQL on Railway)
**Purpose**: Durable audit trail and agent/insurance state.
**Contains**: ~17 tables; in-memory cache rehydrated on startup, in-memory fallback if down.

### Firefly Bridge (Node/Express — local only)
**Purpose**: Localhost broker the browser calls to reach the USB hardware signer.
**Contains**: Express `/sign` on :4747; serial or mock device.

### Firefly Pixie (Hardware)
**Purpose**: Physical secp256k1 signer; releases locked payments only on a button press.

### XRP Ledger (Testnet/Devnet)
**Purpose**: Settlement, escrow, credentials, vault, lending — the source of truth for money.

### External APIs (OpenAI, Frankfurter, OpenSanctions/Plaid, t54 x402)
**Purpose**: AI narration, FX rates, AML/sanctions screening, agent pay-at-need settlement.

## Data Flow

1. Operator's browser loads the **Web App** from Railway.
2. The browser calls the **API Service** (HTTPS/JSON) to submit and track payments.
3. The API persists the decision trail to **PostgreSQL** and settles on the **XRP Ledger**.
4. For large/flagged payments, the browser calls the **local Firefly Bridge**, which
   asks the **Firefly Pixie** to sign; the API verifies the signature before release.
5. The API enriches decisions via **External APIs** (FX, screening, narration, x402).

## Key Boundaries

| Boundary | Inside | Outside |
|----------|--------|---------|
| Railway cloud | Web app, API, Postgres | Operator browser, hardware |
| Operator machine | Browser, Firefly bridge, Pixie device | Cloud services |
| Money authority | XRP Ledger + Firefly signature | Everything else (advisory) |
