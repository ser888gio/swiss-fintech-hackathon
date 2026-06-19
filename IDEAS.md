# Product and demo ideas

[`challenge.md`](challenge.md) is the source of truth. This document ranks ideas
by their ability to improve the official judging criteria without weakening the
working guarded-payment prototype.

## Product thesis

Institutional adoption of autonomous finance is blocked less by whether an AI
can propose a payment than by whether an institution can constrain, prove, and
audit what happens next. This project supplies that missing agent financial
infrastructure on XRPL.

The strongest proof is a real autonomous on-chain payment that succeeds inside
guardrails, followed by a payment that the agent cannot release by itself. The
LLM may route calls and explain results; deterministic code enforces spending
and compliance policy, and a verified Firefly signature releases escrowed funds.

## Ranked ideas

### 1. Guarded autonomous treasury cycle — must ship

Have the treasury agent detect a payable obligation and initiate a real XRPL
transaction without a human clicking “pay.” A routine payment settles; a large
or risky payment enters escrow. This directly satisfies the Agent Financial
Infrastructure requirement for autonomous on-chain activity inside
institutional guardrails.

### 2. Firefly WYSIWYS approval and tamper rejection — must ship

Display payee, amount, asset, network, and reference on the device. Sign a
canonical payment digest only after a physical confirmation. Reuse the signature
against an altered amount and show server-side verification reject it. This
proves the approval is cryptographic and bound to the exact transaction.

### 3. Sanctions veto — must ship

Send an intent to a sanctioned test counterparty. Deterministic policy refuses
it before execution and does not create an approval request. Hardware approval
must not override a sanctions block.

### 4. XRPL Credentials as the identity gate — high priority

Show CredentialCreate, CredentialAccept, and verification for the receiving
institution. A missing or expired accepted credential raises deterministic risk
or blocks according to policy. Return explorer URLs for every on-chain step.

### 5. Auditor-ready receipt — high priority

Export the intent, route, compliance result, rule fired, XRPL hashes, approval
digest/signature, timestamps, and canonical receipt hash. Anchor compact
decision evidence in transaction Memos where appropriate.

### 6. RLUSD settlement and FX routing — high priority

Use RLUSD on Testnet for the routine payment when the required trust line and
issuer settings are available. Keep a clearly labelled XRP or self-issued-token
fallback for escrow. Never call a self-issued token RLUSD.

### 7. Idle treasury vault — stretch only

On Devnet, deposit excess assets into a Single Asset Vault (XLS-65) and withdraw
when liquidity is required; connect XLS-66 only when a real lending action can be
shown. This can deepen Credit & Lending integration, but it must not destabilize
the core autonomous payment, escrow, credential, or audit proof.

### 8. Agent delegation — post-MVP

Give a sub-agent a scoped budget, allowed asset, destination/jurisdiction rules,
and expiry. Route every request through the same deterministic policy engine.
This is a strong future direction, but only after the single-agent flow is fully
proven.

## Ideas to avoid

- A staged prompt-injection where narration pretends to be compromised. It risks
  confusing judges about the LLM boundary; prove the boundary with real failed
  authorization instead.
- Claims of “zero intermediaries,” guaranteed instant settlement, or production
  compliance while using mocks.
- Adding XLS-65/XLS-66 merely for amendment count without a coherent treasury
  action and explorer evidence.
- Calling a browser button, simulator key, or backend release key a hardware
  veto without clearly showing what is real.

## Rubric priority

1. **Viability & Feasibility — 40%:** institutional pain, working deployment,
   business model, and credible Mainnet migration.
2. **Technical Integration / XRPL Features — 30%:** successful transactions,
   correct amendment use, and explorer proof.
3. **Creativity & Innovation — 15%:** a useful policy boundary and physical veto,
   not AI theatre.
4. **Presentation — 10%:** a crisp 5–10 minute story and reliable live demo.
5. **Design & Usability — 5%:** an interface a treasury operator can understand.
