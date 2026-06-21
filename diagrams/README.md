# System Diagrams

Auto-generated diagrams for VaultGuard — Autonomous Treasury Agent on XRPL.
See the [main README](../README.md) for the project overview.

> Note: icons are embedded as data-URIs and render in any direct SVG viewer. On
> GitHub's Markdown view the logos may be stripped by the sanitizer, but the
> shapes, colors, labels, and connections still render correctly.

---

## Architecture

The system has three deployable units. The **React dashboard** (`apps/web`) is the operator's window into every workspace — payments, treasury, agent cover, credentials, and the demo lab. It talks exclusively to the **FastAPI orchestrator** (`apps/api`) over HTTP. The orchestrator runs each workflow as a fixed sequence of deterministic tool calls:

1. **Routing** — quotes an FX path and normalises the amount to USD (Frankfurter)
2. **Compliance** — screens the counterparty for sanctions (OpenSanctions/Plaid) and produces an AML score
3. **Policy & Guardrail Engine** — the deterministic boundary that decides `settle / escalate / block` from a USD threshold + AML score, running the G1–G7 guardrail chain; the LLM never reaches past this layer
4. **Domain engines** — insurance actuarial pricing, agent cover, XLS-70 KYA credential issuance, each called deterministically
5. **Audit Narrator** — the only LLM call (OpenAI gpt-4o); turns the already-decided trail into plain English; an Ed25519 hash-chained event log anchors every decision
6. **Execution** — submits `Payment` (auto-settle), `EscrowCreate` (lock), or `EscrowFinish` (release) to XRPL via `xrpl-py`
7. **Audit Store** — append-only Postgres decision trail for every payment and agent action

To release a locked payment, the browser fetches a sha256 approval challenge from the API, sends it to the **local Firefly bridge** (`apps/firefly-bridge`, never deployed to the cloud), which forwards it to the Firefly device over USB. The operator presses the physical button; the device returns a secp256k1 signature. The browser posts that signature to the API, which verifies it before calling `EscrowFinish`. If the signature fails — wrong amount, wrong recipient, replayed — the API returns 403 and the funds stay locked.

### Overview (Simplified)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./architecture-simplified-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./architecture-simplified-light.svg">
  <img alt="Architecture Overview" src="./architecture-simplified-light.svg">
</picture>

[View simplified documentation](./architecture-simplified.md)

### Detailed

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./architecture-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./architecture-light.svg">
  <img alt="Architecture Diagram" src="./architecture-light.svg">
</picture>

[View detailed documentation](./architecture.md)

---

## Infrastructure

Two Railway services and a local-only bridge form the deployment boundary. The **API service** (`apps/api`, Python/FastAPI) and **web service** (`apps/web`, React/Vite) run as containers on Railway, backed by a **Railway PostgreSQL** database (~17 tables) that holds the full append-only decision trail. The web service is a static Vite build; the API is the deterministic orchestrator, policy engine, XRPL client, and audit store.

The **Firefly bridge** (`apps/firefly-bridge`) never reaches the cloud — it runs on the operator's laptop on port 4747 and owns the USB/serial connection to the Firefly Pixie device. The browser calls it directly over localhost for the signing step, so the hardware key never touches Railway.

External connections from the API:

- **XRPL Testnet/Devnet** over WebSocket (`xrpl-py`) — settlement, escrow, credentials
- **OpenAI** — narration only (gpt-4o), never policy
- **Frankfurter** — FX rates for USD normalisation
- **OpenSanctions / Plaid** — AML and sanctions screening
- **t54 x402 facilitator** — agent pay-at-need settlement for HTTP 402 services

### Overview (Simplified)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./infrastructure-simplified-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./infrastructure-simplified-light.svg">
  <img alt="Infrastructure Overview" src="./infrastructure-simplified-light.svg">
</picture>

[View simplified documentation](./infrastructure-simplified.md)

### Detailed

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./infrastructure-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./infrastructure-light.svg">
  <img alt="Infrastructure Diagram" src="./infrastructure-light.svg">
</picture>

[View detailed documentation](./infrastructure.md)

---

## Documentation

| Document | Description |
|----------|-------------|
| [architecture-simplified.md](./architecture-simplified.md) | High-level architecture overview |
| [architecture.md](./architecture.md) | Detailed software architecture |
| [infrastructure-simplified.md](./infrastructure-simplified.md) | High-level infrastructure overview |
| [infrastructure.md](./infrastructure.md) | Detailed infrastructure components |

## Regenerating

```
/d2:diagram               # Full regeneration
/d2:diagram --incremental # Only changed components
```
