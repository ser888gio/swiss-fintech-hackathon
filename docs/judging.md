# Judging map

This map follows the official weights and requirements in
[`../challenge.md`](../challenge.md).

| Criterion | Weight | What this project must prove |
|---|---:|---|
| **Viability & Feasibility** | 40% | A genuine institutional treasury pain point; working deployment; real Testnet/Devnet evidence; business model, go-to-market, and credible Mainnet path. |
| **Technical Integration / XRPL Features** | 30% | Autonomous XRPL transaction, RLUSD/issued-token settlement, TokenEscrow (XLS-85), Credentials, pathfinding, and accurate explorer links. XLS-65/XLS-66 count only if demonstrated coherently on Devnet. |
| **Creativity & Innovation** | 15% | Deterministic guardrails plus a cryptographic Firefly veto: the agent can act autonomously but cannot bypass policy or forge approval. |
| **Presentation** | 10% | Clear problem, architecture, live on-chain demo, business model, go-to-market, and honest fallback story in 5–10 minutes. |
| **Design & Usability** | 5% | Institutional dashboard, understandable states, actionable approval details, and auditor-friendly evidence. |

## Positioning

- **Primary pillar:** Agent Financial Infrastructure.
- **Use case:** Payments & FX for cross-border treasury operations.
- **Optional extension:** Credit & Lending through XLS-65/XLS-66 on Devnet.
- **Required proof:** at least one transaction autonomously executed by an agent
  within deterministic institutional guardrails.

The demo should show four distinct outcomes: an autonomous routine settlement,
a deterministic sanctions refusal, an escrow lock requiring Firefly approval,
and a tampered approval rejection. Every submitted XRPL transaction needs an
explorer URL.

## Path to Mainnet

Production changes the network and vendors, not the trust boundary: Testnet or
Devnet becomes Mainnet; mock screening becomes a regulated sanctions/KYC
provider; demo wallets become institutional custody/HSM-backed accounts; the
local Firefly approval role can become an enterprise signer; Postgres audit
storage gains production retention and access controls. Policy remains pure,
versioned, and tested. Verify amendment activation and issuer configuration
before promising a feature on Mainnet.

## Business model and go-to-market

Sell to treasury teams and payment/fintech platforms as a workflow and controls
layer: subscription by entity/environment plus usage-based payment and screening
fees. Start with regulated fintech design partners that already operate XRPL or
stablecoin corridors, then integrate custody, compliance, and ERP providers.

## Claims discipline

- Do not say “zero intermediaries”; fiat on/off ramps and service providers exist.
- Do not imply the LLM decides policy, signs, or can release escrow.
- Do not present mocks, self-issued tokens, or simulators as production systems.
- Distinguish Testnet features from Devnet-only XLS-65/XLS-66 functionality.
- Say that routine payments can settle autonomously while consequential payments
  require policy and cryptographic approval.

## Anticipated jury questions

- **What stops the agent draining the treasury?** Deterministic, unit-tested
  policy; sanctions short-circuit; large/risky payments lock in escrow; release
  requires a verified signature whose private key the LLM cannot access.
- **Is approval just a UI button?** No. The device signs the canonical payment
  digest, the backend verifies it against a registered public key, and changing
  payment details makes verification fail.
- **Why XRPL?** Fast settlement, issued assets/RLUSD, native token escrow,
  Credentials, pathfinding, and public transaction evidence match the workflow.
- **Where is the autonomous transaction?** The treasury agent initiates the
  routine payment; deterministic tools screen and settle it without a human pay
  click. Humans intervene only when policy requires approval.
- **Why is this viable?** It addresses an existing treasury controls problem and
  has a clear migration to regulated screening, custody, HSM signing, and
  Mainnet.

## Submission checklist

- Working prototype on XRPL Testnet and/or Devnet
- Public GitHub repository with clear documentation
- Demo video and visible on-chain transaction evidence
- Explicit list of XRPL features, amendments, and target networks
- AI-agent interaction shown where claimed
- Pitch deck of no more than 10 slides
- Developer feedback form submitted
- 5–10 minute pitch/demo rehearsed, plus 3-minute Q&A
