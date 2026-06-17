# Deploying the dashboard to Cloudflare Pages

The React/Vite dashboard (`apps/web`) deploys to **Cloudflare Pages** as a static
site. The FastAPI backend stays on **Railway** — the dashboard calls it over
HTTPS. The Firefly bridge is never deployed (it runs on the operator's laptop).

## One-time setup (GitHub → Pages CI)

1. In the Cloudflare dashboard: **Workers & Pages → Create → Pages → Connect to
   Git**, and pick the `gaaprojects/Ripple_tests` repo.
2. Set the **production branch** (e.g. `main`, or the branch you demo from).
3. **Build settings** — this is a monorepo with npm workspaces, so build from the
   repo root:

   | Setting | Value |
   | --- | --- |
   | Framework preset | None |
   | Root directory | `/` (repo root) |
   | Build command | `npm install && npm run build --workspace apps/web` |
   | Build output directory | `apps/web/dist` |

4. **Environment variables** (Production + Preview):

   | Variable | Value |
   | --- | --- |
   | `NODE_VERSION` | `20` |
   | `VITE_API_BASE_URL` | `https://api-production-c47fd.up.railway.app` |

   `VITE_API_BASE_URL` is optional — `api.ts` already falls back to the Railway
   API for any non-localhost host — but setting it explicitly is the robust
   choice and lets you point a preview build at a different API.

5. **Save and Deploy.** Every push to the production branch redeploys; other
   branches get preview URLs.

## What's already wired in the repo

- `apps/web/public/_redirects` → `/* /index.html 200` so client-side routes
  (`/`, `/transfer`) resolve on direct navigation / refresh (SPA fallback).
- `.nvmrc` pins Node 20 for the build.
- `api.ts` sends any deployed (non-localhost) origin to the Railway API.
- The API's CORS (`CORS_ORIGIN_REGEX`) now allows `*.pages.dev`.

## Important: redeploy the Railway API for CORS

The browser calls the Railway API from the new `*.pages.dev` origin, so the API
must allow it. The default `CORS_ORIGIN_REGEX` now includes `pages.dev`, but the
**running Railway service must pick up the change** — redeploy `apps/api` (or set
`CORS_ORIGINS` on the Railway service to include your exact Pages URL). If you
attach a custom domain to Pages, add that origin too.

## Manual deploy alternative (wrangler)

From a machine with a Cloudflare API token:

```bash
npm install
VITE_API_BASE_URL=https://api-production-c47fd.up.railway.app \
  npm run build --workspace apps/web
npx wrangler pages deploy apps/web/dist --project-name=fx-sentinel
```
