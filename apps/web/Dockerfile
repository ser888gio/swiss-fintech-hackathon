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
RUN npm run build --workspace apps/web

FROM node:20-slim AS serve
WORKDIR /repo/apps/web
COPY --from=build /repo/node_modules /repo/node_modules
COPY --from=build /repo/apps/web/dist ./dist
COPY --from=build /repo/apps/web/package.json ./package.json
EXPOSE 4173
CMD ["sh", "-c", "npx vite preview --host 0.0.0.0 --port ${PORT:-4173}"]
