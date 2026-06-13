# Infrastructure Overview (Simplified)

## System Summary

The system runs as two Railway cloud services plus a Postgres database, fronted
by the operator's browser. Crucially, hardware signing stays off the cloud: a
small bridge and the Firefly device live on the operator's local machine.

## Major Components

### Operator Browser
**Purpose**: Loads the dashboard and orchestrates both the cloud API and the
local signing bridge.

### Web Dashboard (React/Vite on Railway)
**Purpose**: Static front-end served from Railway.

### Treasury API (FastAPI on Railway)
**Purpose**: Runs the payment workflow, policy, compliance, and audit.
**Contains**: orchestrator, policy engine, routing/compliance/execution/firefly/
audit tools.

### Database (PostgreSQL on Railway)
**Purpose**: Persists the full payment decision trail.

### Firefly Bridge (Node/Express, local machine)
**Purpose**: Localhost broker that owns the USB link to the hardware device.

### Firefly Device (USB hardware)
**Purpose**: Signs payment approvals on a physical button press — the hardware veto.

### External APIs (XRPL testnet, OpenAI, Frankfurter, CoinGecko, OpenSanctions)
**Purpose**: Settlement, audit narration, FX/crypto rates, and sanctions screening.

## Data Flow

1. The operator's browser loads the **Web Dashboard** from Railway.
2. The browser sends payment intents to the **Treasury API** on Railway.
3. The API calls **External APIs** for rates, screening, and narration, settles on
   **XRPL testnet**, and writes the trail to **PostgreSQL**.
4. For large payments, the browser asks the **local Firefly Bridge** to sign; the
   **Firefly Device** signs on a button press and the API verifies it before release.

## Key Boundaries

| Boundary | Inside | Outside |
|----------|--------|---------|
| Railway cloud | Web, API, Postgres | Browser, external APIs |
| Local machine | Bridge, Firefly device | Cloud (never connects to hardware) |
| Trust boundary | Hardware signature | Anything the backend alone can do |
