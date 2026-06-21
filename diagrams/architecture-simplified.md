# Architecture Overview (Simplified)

## System Summary

An autonomous treasury agent runs corporate cross-border payments and agentic
financial primitives on XRPL. Small, low-risk payments settle automatically in
seconds; large or flagged payments are locked on-chain and can only be released by
a physical Firefly hardware approval. The AI explains decisions; deterministic code
makes them.

## Major Components

### Dashboard (React/Vite)
**Purpose**: Operator submits intents and approves locked payments across the
payments, treasury, insurance, cover, credentials, and demo workspaces.

### Orchestrator (FastAPI)
**Purpose**: Runs each workflow as a fixed sequence of deterministic tool calls and
narrates each step. Decides nothing about money itself.
**Contains**: payment orchestrator, autonomous treasury agent, x402/delegation/
trade-finance flows.

### Policy & Guardrail Engine (deterministic Python)
**Purpose**: The single boundary that decides settle vs. escalate vs. block via the
G1–G7 guardrail chain and a USD threshold + AML score. The LLM never reaches past it.

### Compliance & Routing Tools
**Purpose**: Screen the counterparty (OpenSanctions/Plaid) into an AML score, verify
XLS-70 credentials, and quote an FX path (Frankfurter).

### Domain Engines (Insurance / Cover / Credentials)
**Purpose**: Actuarial pricing, agent cover, and XLS-70 KYC/KYA credential issuance,
each invoked deterministically from the orchestrator.

### Audit Narrator (OpenAI gpt-4o)
**Purpose**: The only LLM call — turns the decision trail into plain language; an
Ed25519 hash-chained event log records every decision.

### Execution Tool (XRPL)
**Purpose**: Submits Payment (settle), EscrowCreate (lock), and EscrowFinish (release).

### Firefly Hardware Approval (local bridge + device)
**Purpose**: Signs a network-bound approval challenge on a physical button press; the
backend verifies the secp256k1 signature before releasing funds.

### Audit Store (PostgreSQL)
**Purpose**: Durable, append-only decision trail for every payment and agent action.

## Data Flow

1. Dashboard sends a **PaymentIntent** to the **Orchestrator**.
2. Orchestrator calls **Routing** and **Compliance**, then the **Policy & Guardrail
   Engine** returns the deterministic decision.
3. The **Audit Narrator** explains it; the trail is written to the **Audit Store**.
4. Auto-settle → **Execution** sends an XRPL Payment. Escalate → Execution locks
   funds in escrow (`pending_approval`). Sanctioned → blocked outright.
5. To release, the dashboard gets a challenge, the **Firefly device** signs it via the
   local bridge, and the Orchestrator verifies the signature before **Execution**
   finishes the escrow.

## Key Interactions

| From | To | What |
|------|-----|------|
| Dashboard | Orchestrator | Payment intent / release |
| Orchestrator | Policy & Guardrail Engine | Deterministic decision |
| Orchestrator | Compliance & Routing | Screen + quote |
| Orchestrator | Domain Engines | Insurance / cover / credentials |
| Orchestrator | Audit Narrator | Explain (LLM) |
| Orchestrator | Execution (XRPL) | Settle / escrow / finish |
| Orchestrator | Audit Store (Postgres) | Persist decision trail |
| Dashboard | Firefly Hardware | Sign approval (button press) |
