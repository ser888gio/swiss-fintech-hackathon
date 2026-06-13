# CLAUDE.md

Guidance for Claude Code (and any AI agent) working in this repository.

## What this project is

An **Autonomous Treasury Agent with a Firefly hardware veto, built on XRPL** for
SwissHacks 2026 (Ripple — Future of Finance track). It runs corporate
cross-border payments: small/low-risk payments settle autonomously in seconds;
large or compliance-flagged payments are locked on-chain and can only be
released by a physical Firefly hardware approval.

One-line framing for any user-facing copy:
**"The AI decides nothing about money — code does. The AI explains. And no one,
including the agent, can move a large payment without the device in hand."**

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

## Repo layout

```
apps/
  api/            Python FastAPI backend (Railway service)
  web/            React/Vite dashboard (Railway service)
  firefly-bridge/ Local-only Node bridge to the Firefly device
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

Read `docs/PLAN.md` (the full preparation plan) and `docs/architecture.md`.
The MVP build order and the hour-32 demo gate are in `docs/PLAN.md §6`.
