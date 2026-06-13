# Build context is the REPO ROOT (workspaces need the root package.json and the
# @treasury/shared package). On Railway, set this service's root to the repo root
# and the Dockerfile path to apps/web/Dockerfile.
FROM node:20-slim AS build
WORKDIR /repo
COPY package.json package-lock.json* ./
COPY packages/shared/package.json packages/shared/package.json
COPY apps/web/package.json apps/web/package.json
RUN npm install
COPY packages/shared packages/shared
COPY apps/web apps/web
# Vite inlines env vars at build time. Railway passes service variables as build
# args, so declare the ones the web build needs and promote them to ENV before
# `npm run build`. api.ts still has safe local/Railway defaults if this is unset.
ARG VITE_API_BASE_URL
ARG VITE_BRIDGE_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_BRIDGE_BASE_URL=$VITE_BRIDGE_BASE_URL
RUN npm run build --workspace apps/web

FROM node:20-slim AS serve
WORKDIR /app
RUN npm install -g serve@14
COPY --from=build /repo/apps/web/dist ./dist
EXPOSE 3000
CMD ["sh", "-c", "serve -s dist -l ${PORT:-3000}"]
