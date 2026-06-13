# web — Treasury Agent dashboard

React + Vite dashboard. Deployed as a Railway service. Talks to the `api` service
over HTTP and to the local `firefly-bridge` for hardware approvals.

## Run

```bash
npm install            # from the repo root (workspaces)
npm run dev:web        # http://localhost:5173
```

Set `VITE_API_BASE_URL` and `VITE_BRIDGE_BASE_URL` (see root `.env.example`).
The bridge URL is always a localhost address — the dashboard reaches the Firefly
through the operator's own machine, never through Railway.

## Build

```bash
npm run build --workspace apps/web
```
