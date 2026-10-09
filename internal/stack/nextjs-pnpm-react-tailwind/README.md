# nextjs-pnpm-react-tailwind

Phase-2 target stack: turns a single-file **React + Tailwind mock**
(`react_tailwind` source stack: React 18 UMD + Babel standalone + Tailwind Play
CDN) into a production **Next.js 16 (App Router, TypeScript, Tailwind v4)** app,
built with **pnpm**, packaged as a small non-root container, and served behind
the Traefik gateway (design spec §5).

## Template strategy: scaffold + overlay + migrate

The template does **not** vendor a full Next.js skeleton. It holds only what
we own, and the generator builds the app in three steps:

1. **Scaffold** with the official, pinned `create-next-app` (see
   `template.yaml#scaffold.command`):

   ```sh
   pnpm dlx create-next-app@16.4.0 {{app_name}} \
     --ts --tailwind --eslint --app --src-dir --import-alias "@/*" \
     --use-pnpm --skip-install --disable-git --no-agent-feedback --yes
   ```

   `--disable-git` because the generator does its own `git init` +
   `:tada: First version` commit; `--skip-install` because we only need the
   lockfile, not a host `node_modules`. The scaffold writes
   `"packageManager": "pnpm@<version that ran it>"`, so run it with the pinned
   pnpm (corepack, below).

2. **Overlay**: copy these files over the scaffold output:
   `Dockerfile`, `.dockerignore`, `docker-compose.yaml`, `.env.example`,
   `next.config.ts` (scaffold defaults + `output: "standalone"` +
   `poweredByHeader: false`). Store the mock at `design/mock.html`.

3. **Migrate** the mock into `src/` (below), then produce the lockfile:
   `pnpm install --lockfile-only --store-dir /tmp/pnpm-store`.
   The committed `pnpm-lock.yaml` is what makes the image build reproducible
   (`pnpm install --frozen-lockfile`).

Why scaffold instead of vendoring: create-next-app output changes with every
Next major (16.x writes `@tailwindcss/turbopack`, `cacheComponents`,
`pnpm-workspace.yaml#allowBuilds`, `AGENTS.md`); pinning the scaffolder version
gets the upstream-blessed baseline with a small overlay that is easy to diff
when bumping. Bump `create-next-app`, `pnpm`, and the Node image digest
together and re-run the template test. If the scaffold's `next.config.ts`
changes, update the overlay to match.

No host Node is needed; the reference runner is the pinned Node image:

```sh
docker run --rm -v "$PWD":/work -w /work \
  -e COREPACK_ENABLE_DOWNLOAD_PROMPT=0 -e NEXT_TELEMETRY_DISABLED=1 \
  node:22.23.3-alpine3.24 sh -c \
  'corepack enable && corepack prepare pnpm@12.10.1 --activate && \
   pnpm dlx create-next-app@16.4.0 my-app --ts --tailwind --eslint --app \
     --src-dir --import-alias "@/*" --use-pnpm --skip-install --disable-git \
     --no-agent-feedback --yes'
```

## Migration: `design/mock.html` → app

| In the mock | In the app |
|---|---|
| `<script src=…react…>`, `react-dom`, `@babel/standalone`, `cdn.tailwindcss.com` | **Dropped.** React/Next come from `package.json`; Tailwind v4 is compiled at build time via `src/app/globals.css` (`@import "tailwindcss"`). |
| The top-level `App` component in `<script type="text/babel">` | `src/app/page.tsx` (default export). Keep it a Server Component when it has no state/effects/handlers. |
| Other components (`function Card() {…}`) | `src/components/<Name>.tsx`, one default export each, imported via `@/components/<Name>`. |
| `React.useState`, `React.useEffect`, `const { useState } = React` | `import { useState, useEffect } from "react"`; any file using hooks or event handlers starts with `"use client"`. |
| `ReactDOM.createRoot(...).render(<App />)` and `<div id="root">` | **Dropped** — Next renders `page.tsx` into `layout.tsx`. |
| `className="…"` Tailwind utilities | **Carry over unchanged.** Tailwind v4 scans `src/` automatically. Inline `tailwind.config = {…}` customisations become `@theme { … }` in `globals.css`. |
| `<title>`, `<meta>` | `export const metadata` in `src/app/layout.tsx`. |
| Google Fonts `<link>` | **Dropped.** No `next/font`: the generator rewrites `layout.tsx` and points `--font-sans`/`--font-mono` in `globals.css` at a system font stack (`apply_system_fonts`), so builds need no network. |
| `<style>` blocks | `src/app/globals.css`. |
| Local/inline images and assets | `public/` (referenced as `/file.png`). Remote images (placehold.co, unsplash, …) stay as plain `<img>`; switching to `next/image` requires `images.remotePatterns` in `next.config.ts`. |
| Font Awesome / icon CDNs | Swap for an npm package or inline SVG components (`layout.tsx` is regenerated, so a `<link>` there does not survive). |
| `onClick="…"` strings / `document.querySelector` scripts | Rewrite as React state + handlers inside a `"use client"` component. |
| `body` classes | `<body className=…>` in `layout.tsx`. |

`tests/fixture/` holds a minimal worked example: `design/mock.html` and its
hand-migrated `src/app/page.tsx` + `src/components/Counter.tsx`, rendering the
marker `STACK-FIXTURE-MARKER nextjs-pnpm-react-tailwind`. It is test-only and
not part of the overlay.

## Container image (`Dockerfile`)

- `# syntax=docker/dockerfile:1.7`, 4 stages: `base` → `deps` → `builder` →
  `runner`.
- **Base pinned by tag and digest**: `node:22.23.3-alpine3.24@sha256:0a71…`
  (multi-arch index digest, so amd64 and arm64 both build). No
  `libc6-compat`: SWC, Turbopack, lightningcss and Tailwind oxide ship musl
  binaries (verified by building on Alpine).
- **deps**: copies only `package.json`, `pnpm-lock.yaml`,
  `pnpm-workspace.yaml`; `corepack enable pnpm && corepack install` uses
  exactly `packageManager`; `pnpm install --frozen-lockfile` with the store in
  a BuildKit cache mount (`id=pnpm,target=/pnpm/store`). Source edits don't
  invalidate this layer.
- **builder**: `FROM deps` (reuses pnpm + `node_modules`), `COPY . .`,
  `pnpm build`, `NEXT_TELEMETRY_DISABLED=1`.
- **runner**: only `.next/standalone`, `.next/static`, `public/`, all
  `--chown=nextjs:nodejs`; user `nextjs` uid **1001** / group `nodejs` gid
  **1001**, `USER 1001:1001` (numeric for k8s `runAsNonRoot`);
  `NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0`; `EXPOSE 3000`;
  `HEALTHCHECK` via Node's built-in `fetch` (no curl/wget in the image);
  exec-form `CMD ["node","server.js"]` (PID 1 gets SIGTERM; stop is immediate).
- OCI labels; override with `--build-arg APP_NAME= APP_VERSION= VCS_REF=
  BUILD_DATE=`.
- `.dockerignore` keeps `node_modules`, `.next`, `.git`, `design/`, `.env*`,
  docs and compose files out of the build context.

Image size (fixture app): **~201 MB**. The `node:22-alpine` base is 164 MB,
and the app layers are ~38 MB.

## Build and run

Standalone:

```sh
docker build -t my-app .
docker run --rm -p 127.0.0.1:3000:3000 my-app   # http://127.0.0.1:3000
```

Behind the gateway (contract §5: no host ports, external network
`traefik_webgateway`, which the root `docker-compose.yml` creates):

```sh
cp .env.example .env          # set APP_ID; APP_HOST defaults to ${APP_ID}.localhost
docker compose up -d --build --wait
open "http://$(. ./.env; echo "$APP_ID").localhost:3311/"
docker compose down --rmi local
```

`APP_HOST=${APP_ID}.localhost` in `.env` works because Docker Compose
interpolates variables inside `.env` (verified with Compose v5.5). The labels
use list form so `${APP_ID}` is also interpolated inside label keys. Compose
fails fast if `APP_ID`/`APP_HOST` are unset.

## Develop

```sh
corepack enable && pnpm install && pnpm dev     # http://localhost:3000
pnpm lint && pnpm build
```

## Testing this template

1. Run the scaffold (above) into a temp dir, overlay the files, and copy
   `tests/fixture/design/mock.html` → `design/mock.html` and
   `tests/fixture/src/**` → `src/`.
2. Run `pnpm install --lockfile-only --store-dir /tmp/pnpm-store`.
3. Run `docker build`, then `docker run -p 127.0.0.1:<port>:3000`. Expect
   `curl -fsS /` to return 200 with the marker, and `docker inspect`
   health=healthy, uid 1001.
4. Run `docker compose up -d --build --wait` on `traefik_webgateway`, then
   `curl -H "Host: $APP_HOST" http://localhost:3311/` and expect the marker.
   Finish with `docker compose down --rmi local`.
