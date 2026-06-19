# CLAUDE.md

Guidance for Claude Code (and any AI agent) working in this repository.

## What this project is

An **Autonomous Treasury Agent with a Firefly hardware veto, built on XRPL** for
SwissHacks 2026 and Ripple's **Future of Finance on XRPL: Payments, Credit &
Agent Financial Infrastructure** challenge. It runs corporate
cross-border payments: small/low-risk payments settle autonomously in seconds;
large or compliance-flagged payments are locked on-chain and can only be
released by a physical Firefly hardware approval.

One-line framing for any user-facing copy:
**"The AI decides nothing about money — code does. The AI explains. And no one,
including the agent, can move a large payment without the device in hand."**

## Source-of-truth order

1. [`challenge.md`](challenge.md) is authoritative for challenge scope,
   submission requirements, network/feature availability, judging weights, and
   event facts.
2. [`AGENTS.md`](AGENTS.md) is authoritative for orchestration and tool
   contracts.
3. This file is authoritative for repository conventions and safety invariants.
4. `docs/PLAN.md`, `docs/judging.md`, and `docs/demo-script.md` translate those
   sources into execution and presentation plans and must not contradict them.

The submission is positioned primarily under **Agent Financial
Infrastructure**, with **Payments & FX** as the live institutional use case.
Credit & Lending is an optional extension, not an MVP requirement. The challenge
is about infrastructure agents need—not an AI demo—so prioritize real guarded
on-chain activity, institutional usability, and a credible Mainnet path.

## The one rule that must never be broken

> **The LLM orchestrates and narrates. It NEVER decides policy or signs
> transactions.** Policy (auto-settle vs. escalate) and signing are enforced by
> deterministic code only.

If you are tempted to let the model branch on an amount, a risk score, or
whether to release funds — stop. That logic lives in `apps/api/app/policy/` and
the execution/firefly tools, never in a prompt. A misbehaving model must, at
worst, produce bad narration — never a bad payment.

## Architecture (locked — do not relitigate)

- **Two deployed services on Railway** + Postgres:
  - `apps/api` — Python FastAPI: orchestrator, XRPL, policy, compliance, audit.
  - `apps/web` — React/Vite dashboard.
- **`apps/firefly-bridge` runs LOCALLY only.** It talks to the Firefly hardware
  over USB/serial and exposes a localhost HTTP endpoint to the browser. The
  Railway API must **never** connect directly to hardware. Flow is:
  `browser → localhost bridge → Firefly device → signature → backend verifies`.
- **`packages/shared`** — TypeScript types shared by `web` and `firefly-bridge`.
  The Python API mirrors these as Pydantic models in `apps/api/app/schemas.py`;
  keep the two in sync by hand.
- "Agents" are a UI/narrative concept. Under the hood there is **one backend
  workflow** calling deterministic tools.

## Tech stack

- Backend: Python 3.11+, FastAPI, SQLAlchemy (async), Pydantic, `xrpl-py`,
  `httpx`, OpenAI SDK.
- Frontend: TypeScript, React 18, Vite.
- Bridge: TypeScript, Node 20, Express, `serialport` (or a mock device).
- DB: PostgreSQL.
- Monorepo: npm workspaces for the TS packages; the Python API lives alongside
  in `apps/api` and is run with its own venv.

> **XRPL SDK rule: Python `xrpl-py` only.** All code that constructs, signs,
> submits, queries, or decodes XRPL transactions uses `xrpl-py`. Do not add
> `xrpl.js`, `xrpl4j`, or any other XRPL SDK; the React frontend and the
> TypeScript Firefly bridge call the Python API and must never become a second
> XRPL client. `AGENTS.md` holds the full policy and the required research tools.

## XRPL research tools (use before changing protocol behavior)

Confirm transaction fields, amendment/network availability, and `xrpl-py`
support against primary sources — never model memory:

- [XRPL docs](https://xrpl.org/docs) · [Open Source Ripple](https://opensource.ripple.com)
- [Context7 XRPL MCP/search](https://context7.com/?q=xrpl) — source-grounded library context
- [XRPL AI tools, Skills & MCP](https://xrpl.org/resources/dev-tools/ai-tools)
- [Resources index](https://linktr.ee/rippledevrel) · [RippleDevRel sample scripts](https://github.com/RippleDevRel/xrpl-js-python-simple-scripts) (port JS to `xrpl-py`)
- RLUSD: [docs](https://docs.ripple.com/products/stablecoin) · [Testnet faucet](https://tryrlusd.com) (Testnet only, not Devnet)
- Agent/x402: [x402 facilitator](https://xrpl-x402.t54.ai/#setup) · [x402Secure](https://www.x402secure.com/) · [Claw Credit](https://www.claw.credit) · [x402 XRPL SDK](https://github.com/t54-labs/x402-xrpl) · [RLUSD CLI](https://github.com/t54-labs/rlusd-cli) · [RLUSD Agent Skills](https://github.com/t54-labs/rlusd-skills) · [OpenWallet Standard](https://openwallet.sh)
- Browser-wallet testing: [Crossmark](https://crossmark.io) or [GemWallet](https://gemwallet.app) only, with isolated faucet-funded accounts — never repo or production secrets.

See `AGENTS.md` for how each tool maps to the deterministic policy boundary.

## Repo layout

```
apps/
  api/            Python FastAPI backend (Railway service)
  web/            React/Vite dashboard (Railway service)
  firefly-bridge/ Local-only Node bridge to the Firefly device
  crypto/         Local XRPL testnet spike (Node scripts: fund wallet, send payment)
packages/
  shared/         Shared TypeScript types
docs/             Plan, architecture, demo script, judging map
```

## How to run

- **API:** `cd apps/api && python -m venv .venv && . .venv/Scripts/activate &&
  pip install -r requirements.txt && uvicorn app.main:app --reload` (port 8000).
- **Web:** `npm run dev:web` (Vite, port 5173).
- **Bridge:** `npm run dev:bridge` (port 4747, local machine only).
- Copy `.env.example` → `.env` first. The API reads root `.env`; Vite reads
  `apps/web/.env` (or root with `VITE_` prefix).

## Conventions

- **Secrets never enter the repo.** Wallet seeds and API keys live only in
  `.env` / Railway variables. `.gitignore` already blocks `.env` and `*.seed`.
- **Money claims discipline.** Do not write "zero intermediaries" or
  "instant/free forever" — fiat on/off ramps exist. Be precise.
- **Determinism boundary.** Anything that decides or signs is plain Python with
  unit tests. Anything that explains can call the LLM.
- **Audit everything.** Every payment writes a full decision trail to Postgres
  (intent, route quote, compliance result + score, policy decision + rule
  fired, approval payload + signature, tx hash, timestamps). See
  `docs/architecture.md`.
- **Testnet, with explorer proof.** Demo viability = everything live on testnet
  with explorer links, deployed on Railway, not localhost.

## When in doubt

Read `challenge.md` first, then `docs/PLAN.md` and `docs/architecture.md`.
The MVP build order and the hour-32 demo gate are in `docs/PLAN.md §6`.

Before submission, verify the public repository documentation, demo video,
on-chain transaction evidence, XRPL feature/amendment explanation, developer
feedback form, and a pitch deck of no more than 10 slides. The live pitch and
demo must fit 5–10 minutes, followed by 3 minutes of jury Q&A.
