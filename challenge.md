# Ripple

## Challenge Title

Future of Finance on XRPL: Payments, Credit & Agent Financial Infrastructure

## Introduction

### Problem Description

Institutional financial services across payments, credit, and treasury remain trapped in legacy infrastructure that is fragmented, slow, and costly. While DeFi has shown the potential of on-chain primitives, most protocols target retail users and lack the compliance, scalability, and reliability that institutions require. In parallel, AI agents are emerging as a way to automate complex financial workflows, yet the financial infrastructure they need to operate autonomously in institutional environments (verified identity, spending controls, compliant settlement, governed sub-agents) does not yet exist.

### Case Introduction

Ripple's Institutional DeFi strategy is built around three pillars: Payments & FX, Credit & Lending, and Agent Financial Infrastructure. New and existing XRPL amendments, including the Lending Protocol (XLS-66) and Single Asset Vaults (XLS-65), cut across all three pillars and enable institutional-grade financial products on-chain.

This challenge asks teams to build a working prototype that addresses a genuine institutional pain point within one or more of these pillars and shows a credible path to Mainnet. Both crypto-native teams building from scratch and fintech teams integrating XRPL into an existing product are welcome.

## Potential Users

Banks, asset managers, treasury departments, fintech companies, and institutional investors seeking on-chain lending, borrowing, payments, vault management, and tokenized asset solutions.

Secondary users include developers building institutional-grade tooling and enterprises looking to leverage AI agents for automated on-chain financial operations.

## Use Cases

The challenge is organized around three pillars. Teams can build within a single pillar or combine elements across pillars. Solutions may incorporate RLUSD and/or AI agents to orchestrate workflows.

**Payments & FX.** Reimagine how money moves: cross-border payment corridors that settle in seconds using RLUSD, FX settlement layers that remove intermediaries, B2B platforms with programmable invoice logic and automatic reconciliation, treasury tools that optimize cross-border fund movement, or lending-backed liquidity pools that make emerging-market corridors viable without heavy pre-funding.

**Credit & Lending.** Fix how credit works: trade finance platforms that tokenize receivables so suppliers get paid today instead of in 90 days, institutional lending markets backed by on-chain collateral, RLUSD-collateralized credit facilities with dynamic interest rate models, supply chain finance connecting buyers, suppliers, and lenders on a single ledger, or capital mobility solutions across on-chain products. The Lending Protocol (XLS-66) is the technical anchor.

**Agent Financial Infrastructure.** This pillar is about the financial infrastructure agents need, not about building AI. A winning submission must include at least one on-chain transaction executed autonomously by an agent within institutional guardrails (spending limits, policy enforcement, compliance checks, or audit trails). Example angles:

- **Know Your Agent (KYA):** identity verification for agents using DID, Credentials, and Permissioned Domains.
- **Agent Wallets with Spending Policies:** corporate-grade spending controls (limits, approval thresholds, jurisdiction restrictions, audit trails).
- **Regulated Settlement for Autonomous Payments:** a compliance layer between an agent's payment intent and settled transaction, performing sanctions screening and policy validation with RLUSD settlement (e.g. in an x402 flow).
- **Agent-to-Agent Funding & Delegation:** a parent agent that deploys, funds, and governs sub-agents with scoped wallets and task-specific permissions via x402 and RLUSD.

Agent integration within the Payments & FX or Credit pillars is also recognized under Creativity & Innovation. Teams are not required to arrive with a use case; mentors can help scope an integration during the event.

## Expected Outcome

A working prototype deployed on XRPL Testnet or DevNet that demonstrates an institutional DeFi use case in one or more pillars, leveraging XRPL amendments such as the Lending Protocol (XLS-66), Single Asset Vaults (XLS-65), MPTokens, TokenEscrow, and Credentials. Solutions may incorporate RLUSD and/or AI-powered agents. The prototype must drive real on-chain activity and show a credible path to production on XRPL Mainnet.

Submission requirements:

- Working prototype deployed on XRPL Testnet or DevNet
- Public GitHub repository with documentation and a demo video
- Clear demonstration of on-chain transactions
- Explanation of which XRPL features and amendments are used
- If applicable, demonstration of AI agent interaction with XRPL
- A slide deck supporting the pitch (max 10 slides)
- Developer feedback form: https://forms.gle/A8AY3HXWiSxSJ2pA7

Presentation format: 5 to 10 minute live demo and pitch, followed by 3 minutes of Q&A with the jury. The pitch should cover the problem statement, solution architecture (which amendments and XRPL features are used), a live demo on Testnet or DevNet, the business model, and go-to-market strategy.

## Technology

### Available Technology

| Component | Description | Resources | Status |
| --- | --- | --- | --- |
| MPTokens (XLS-33) | Multi-Purpose Tokens amendment for flexible token issuance | https://github.com/XRPLF/XRPL-Standards/tree/master/XLS-0033-multi-purpose-tokens | Mainnet / Testnet / Devnet |
| Lending Protocol (XLS-66) | On-chain lending and borrowing protocol | https://github.com/XRPLF/XRPL-Standards/tree/master/XLS-0066-lending-protocol | Devnet only |
| Single Asset Vault (XLS-65) | Tokenized vault primitive for asset management | https://github.com/XRPLF/XRPL-Standards/tree/master/XLS-0065-single-asset-vault | Devnet only |
| TokenEscrow (XLS-85) | Escrow mechanism for tokenized assets | https://github.com/XRPLF/XRPL-Standards/tree/master/XLS-0085-token-escrow | Mainnet / Testnet / Devnet |
| RLUSD | Ripple's USD-backed stablecoin on XRPL | https://tryrlusd.com | Mainnet / Testnet |
| xrpl.js | JavaScript SDK for XRPL | https://xrpl.org/docs/tutorials/get-started/get-started-javascript | Ready |
| xrpl4j | Java SDK for XRPL | https://xrpl.org/docs/tutorials/get-started/get-started-java | Ready |
| xrpl-py | Python SDK for XRPL | https://xrpl.org/docs/tutorials/get-started/get-started-python | Ready |

Documentation:

- XRPL docs: https://xrpl.org/docs
- XRPL tutorials: https://xrpl.org/docs/tutorials
- Lending Protocol (open source Ripple): https://opensource.ripple.com/docs/xls-66d-lending-protocol/concepts/lending-protocol
- Single Asset Vaults (open source Ripple): https://opensource.ripple.com/docs/xls-65d-single-asset-vault
- Create a Single Asset Vault tutorial: https://xrpl.org/docs/tutorials/defi/lending/use-single-asset-vaults/create-a-single-asset-vault
- Create a Loan Broker tutorial: https://xrpl.org/docs/tutorials/defi/lending/use-the-lending-protocol/create-a-loan-broker
- XRPLF GitHub: https://github.com/XRPLF

### Expected or Suggested Tech Stack

No specific stack is required. Suggested entry points:

- **xrpl.js** (JavaScript / TypeScript): https://xrpl.org/docs/tutorials/get-started/get-started-javascript
- **xrpl-py** (Python): https://xrpl.org/docs/tutorials/get-started/get-started-python
- **xrpl4j** (Java): https://xrpl.org/docs/tutorials/get-started/get-started-java
- **xrpl-connect** (wallet connector): framework-agnostic wallet connection toolkit for XRPL (Xaman, Crossmark, GemWallet, WalletConnect), https://github.com/XRPL-Commons/xrpl-connect
- **RLUSD** as the stable, programmable settlement asset
- Workshop materials provided during the hackathon

## Challenge Slides

[To be added: link to the challenge introduction slides]

## Resources & Further Information

### Relevant Links

Resources index: https://linktr.ee/rippledevrel

Core XRPL:

- XRPL documentation and API references: https://xrpl.org/docs
- Open source Ripple: https://opensource.ripple.com
- Sample scripts and starter code: https://github.com/RippleDevRel/xrpl-js-python-simple-scripts
- XRPL CLI (xrpl-up): https://github.com/ripple/xrpl-up
- Context7 (XRPL): https://context7.com/?q=xrpl

RLUSD:

- RLUSD stablecoin docs: https://docs.ripple.com/products/stablecoin
- RLUSD Testnet faucet (Testnet only, not Devnet): https://tryrlusd.com

XRPL AI and agent resources:

- XRPL AI tools (Skills and MCP): https://xrpl.org/resources/dev-tools/ai-tools
- XRPL x402 facilitator: https://xrpl-x402.t54.ai/#setup
- x402Secure Service: https://www.x402secure.com/
- Claw Credit (autonomous agent credit via x402): https://www.claw.credit
- x402 XRPL SDK: https://github.com/t54-labs/x402-xrpl
- RLUSD CLI: https://github.com/t54-labs/rlusd-cli
- RLUSD Agent Skills: https://github.com/t54-labs/rlusd-skills
- OpenWallet Standard: https://openwallet.sh

### Additional Information

All solutions should address a genuine institutional pain point, drive real on-chain activity, and demonstrate a credible path to Mainnet deployment. Mentors will be available on-site to help teams scope an integration during the event.

## Judging Criteria

Evaluation balances technical depth with business viability and creative thinking.

| Criterion | Description | Weight |
| --- | --- | ---: |
| Viability & Feasibility | Business model, institutional market fit, path to Mainnet production. Maturity of the prototype, working on-chain transactions, deployment readiness | 40% |
| Technical Integration / Use of XRPL Features | Effective use of XRPL amendments (e.g. XLS-65, XLS-66), SDKs, and integrations | 30% |
| Creativity & Innovation | Originality of the approach, novel use of Lending Protocol, Vaults, and/or AI agents | 15% |
| Presentation | Clarity and impact of the pitch, storytelling, live demo quality | 10% |
| Design & Usability | User experience, interface quality, suitability for institutional users | 5% |

## Point of Contact

### Contact Person(s)

| Role | Name | Department / Contact |
| --- | --- | --- |
| Hackathon Lead / Jury | Maxime Dienger | Developer Relations, maximed@ripple.com |
| Jury Member | Whittney Levitt | Director, Ecosystem Growth, wlevitt@ripple.com |

### Availability

In person throughout the event (SwissHacks, Zurich, 19 to 21 June 2026). Mentors will be on-site on the evening of 19 June after the presentations, and on 20 June from 9:00 to 19:00. The contacts above are also reachable by email for any questions before or during the event.

## Prize

The winning team members will each receive:

- **Point Zero Forum Pitch:** the opportunity to pitch at the Point Zero Forum (23 June 2026).
- **Ripple Builder Award:** top teams will be fast-tracked for consideration in Ripple's builder grants program, with funding to support Mainnet deployment.
- **Fintech Solutions Lab:** outstanding projects with institutional market fit will be considered for Ripple's Fintech Program, offering access to co-create with institutional partners and dedicated go-to-market support.
