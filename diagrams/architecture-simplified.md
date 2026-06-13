# Architecture Overview (Simplified)

## System Summary

An autonomous treasury agent runs corporate cross-border payments on XRPL. Small,
low-risk payments settle automatically in seconds; large or flagged payments are
locked on-chain and can only be released by a physical Firefly hardware approval.
The AI explains decisions; deterministic code makes them.

## Major Components

### Dashboard (React/Vite)
**Purpose**: Operator submits intents, watches the agent log, and approves locked
payments.

### Orchestrator (FastAPI)
**Purpose**: Runs the payment workflow as a fixed sequence of tool calls and
narrates each step. Decides nothing about money itself.

### Policy Engine (deterministic Python)
**Purpose**: The single boundary that decides auto-settle vs. escalate vs. block.
The LLM never reaches past it.

### Compliance & Routing Tools
**Purpose**: Screen the receiver (OpenSanctions) into an AML score and quote an FX
path (Frankfurter/CoinGecko).

### Audit Narrator (OpenAI gpt-4o)
**Purpose**: The only LLM call — turns the decision trail into plain language.

### Execution Tool (XRPL testnet)
**Purpose**: Submits Payment, EscrowCreate (lock), and EscrowFinish (release).

### Firefly Hardware Approval (local bridge + device)
**Purpose**: Signs a network-bound approval challenge on a physical button press;
the backend verifies the secp256k1 signature before releasing funds.

## Data Flow

1. Dashboard sends a **PaymentIntent** to the **Orchestrator**.
2. Orchestrator calls **Routing** and **Compliance**, then asks the **Policy
   Engine** to decide.
3. The **Audit Narrator** explains the decision.
4. Auto-settle → **Execution** sends an XRPL Payment. Escalate → Execution locks
   funds in escrow (`pending_approval`). Sanctioned → blocked outright.
5. To release, the dashboard gets a challenge, the **Firefly device** signs it, and
   the Orchestrator verifies the signature before **Execution** finishes the escrow.

## Key Interactions

| From | To | What |
|------|-----|------|
| Dashboard | Orchestrator | Payment intent / release |
| Orchestrator | Policy Engine | Deterministic decision |
| Orchestrator | Compliance & Routing | Screen + quote |
| Orchestrator | Audit Narrator | Explain (LLM) |
| Orchestrator | Execution (XRPL) | Settle / escrow / finish |
| Dashboard | Firefly Hardware | Sign approval (button press) |
