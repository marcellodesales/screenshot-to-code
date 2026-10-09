# syntax=docker/dockerfile:1.7
#
# static-pnpm-html: serve one self-contained HTML mock (public/index.html) on :3000.
#
# Base image: node:22 on Alpine. The only runtime dependency (`serve`) is pure
# JavaScript, so musl vs glibc does not matter and Alpine gives the smallest
# image (tens of MB smaller than bookworm-slim) with a smaller CVE surface. The
# tag is pinned to an exact Node patch + Alpine release for reproducible builds.
ARG NODE_IMAGE=node:22.23.3-alpine3.24

# ---------------------------------------------------------------------------
# deps: install production dependencies with the exact pnpm from package.json
# ---------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS deps
WORKDIR /app

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0

# Only the manifest + lockfile: this layer is reused until dependencies change.
COPY package.json pnpm-lock.yaml ./

# corepack activates the pnpm version pinned in "packageManager".
RUN corepack enable && corepack install

# The pnpm store lives in a BuildKit cache mount: reused across builds and
# never baked into a layer.
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile --prod --store-dir /pnpm/store

# ---------------------------------------------------------------------------
# runtime: node + production node_modules + the mock, running as non-root
# ---------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS runtime

LABEL org.opencontainers.image.title="static-pnpm-html" \
      org.opencontainers.image.description="Self-contained HTML mock served on port 3000 (screenshot-to-code stack generator)" \
      org.opencontainers.image.source="https://github.com/abi/screenshot-to-code" \
      org.opencontainers.image.licenses="MIT"

ENV NODE_ENV=production \
    PORT=3000

WORKDIR /app

# Files stay owned by root (read-only for the runtime user); nothing needs to
# be writable. pnpm itself is not needed at runtime.
COPY --from=deps /app/node_modules ./node_modules
COPY package.json ./
COPY public ./public

# `node` (uid 1000) ships with the official image.
USER node

EXPOSE 3000

# Alpine has no curl: use Node's built-in fetch.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]

# Exec form with node as PID 1 (no pnpm/shell wrapper) so SIGTERM reaches the
# server directly. Equivalent to `pnpm start`.
CMD ["node", "node_modules/serve/build/main.js", "public", "--listen", "tcp://0.0.0.0:3000", "--no-clipboard"]
