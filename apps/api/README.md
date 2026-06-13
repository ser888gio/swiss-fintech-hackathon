# api — Treasury Agent backend

Python FastAPI service: orchestrator, XRPL execution, policy engine, compliance,
audit. Deployed as a Railway service. See `../../docs/architecture.md`.

## Run locally

```bash
cd apps/api
python -m venv .venv
. .venv/Scripts/activate          # Windows; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp ../../.env.example ../../.env   # then fill in values
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for the interactive API.

By default `USE_MOCK_XRPL=true`, so the full payment workflow runs offline with
deterministic fake tx hashes. Set it to `false` and provide funded testnet
wallet seeds to submit real XRPL transactions.

## Test

```bash
pytest
```

`tests/test_policy.py` covers the policy boundary — the deterministic decision
that the LLM is never allowed to make.

## Layout

```
app/
  main.py            FastAPI app + CORS
  config.py          env-backed settings
  schemas.py         Pydantic models (mirror packages/shared/src/types.ts)
  store.py           in-memory store (swap for models.py + Postgres)
  models.py          SQLAlchemy target schema for the audit store
  xrpl_client.py     XRPL helpers (explorer URLs)
  policy/engine.py   THE policy boundary — deterministic, tested
  agents/orchestrator.py   workflow: calls tools in order, narrates
  tools/             routing, compliance, execution, firefly, audit
  routes/            health, payments
tests/               policy tests
```

## Endpoints

- `POST /payments` — submit an intent, run the workflow.
- `GET /payments` — list payments.
- `GET /payments/{id}` — one payment.
- `GET /payments/{id}/logs` — agent log entries.
- `GET /payments/{id}/challenge` — the digest the Firefly must sign.
- `POST /payments/{id}/release` — submit a Firefly signature to release a locked
  payment. Verified server-side before EscrowFinish.
