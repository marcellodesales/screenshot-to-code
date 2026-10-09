# Stack generator: from mock to running system — design

Status: draft (2026-10-08) · Branch: `feat/scaffolded-project-generation`

## 1. Intent

screenshot-to-code today turns a screenshot/video/text into a **single-file
HTML mock** (React/Vue via CDN + in-browser Babel, Tailwind Play CDN). The goal
is a **generator of systems** on top of that: take a selected mock, turn it into
a real project in a catalogued target stack, build it with the chosen build
system, commit it, and run it as a container reachable through a system-wide
Traefik gateway — the same shape it would have as a Kubernetes Ingress host.

### What stays the same

Generation (option 1, option 2, … streaming into the UI) is untouched. The new
pipeline only starts when the user clicks **🚀 Build app** (next to
"Select & edit") on a finished generation.

## 2. Run workspace layout

All under the backend `/data` volume (`./data` on the host):

```
data/runs/<run-id>/
  stack.yaml                  # run metadata: source stack, target stack id, build
                              # system, models per option, prompt, app name, hosts
  uploads/
    video/<file>              # original upload(s), when input_mode == video
    screenshots/<file>        # original upload(s), when input_mode == image
  op1/
    design/mock.html          # option 1 output exactly as generated today
    app/                      # scaffolded project = template + migrated code;
                              # own git repo, first commit ":tada: First version"
  op2/
    design/mock.html
    app/
```

Option directories are `op<N>` (1-based, matching the UI's "Option N").
Stack choice lives in `stack.yaml`, never in directory names.

## 3. Stack catalog and templates

```
internal/stack/
  catalog.yaml                      # every available target stack (see §4)
  <stack-id>/
    template.yaml                   # this template's metadata (mirrors its catalog entry)
    Dockerfile
    .dockerignore
    docker-compose.yaml             # joins the Traefik network (contract §5)
    README.md                       # how to build/run/develop the generated app
    ...                             # stack-specific skeleton files
```

`<stack-id>` = `<runtime>-<build-system>-<ui>-<styling>`, lowercase, hyphenated,
e.g. `static-pnpm-html`, `nextjs-pnpm-react-tailwind`.

## 4. Stack matrix

Source stacks are what the generator produces today
(`backend/prompts/prompt_types.py::Stack`). Build systems: `pnpm` (first),
`npm`, `bun`.

| Source stack (mock) | Target template | Phase | pnpm | npm | bun |
|---|---|---|---|---|---|
| html_css | `static-<bs>-html` | 1 | ✅ P1 | later | later |
| html_tailwind | `static-<bs>-html` | 1 | ✅ P1 | later | later |
| react_tailwind | `static-<bs>-html` | 1 | ✅ P1 | later | later |
| bootstrap | `static-<bs>-html` | 1 | ✅ P1 | later | later |
| vue_tailwind | `static-<bs>-html` | 1 | ✅ P1 | later | later |
| ionic_tailwind | `static-<bs>-html` | 1 | ✅ P1 | later | later |
| react_tailwind | `nextjs-<bs>-react-tailwind` | 2 | ✅ P2 | later | later |
| react_tailwind | `vite-<bs>-react-tailwind` | 3 | later | later | later |
| html_tailwind | `vite-<bs>-html-tailwind` | 3 | later | later | later |
| vue_tailwind | `nuxt-<bs>-vue-tailwind` | 3 | later | later | later |
| ionic_tailwind | `vite-<bs>-ionic-react` | 3 | later | later | later |
| bootstrap / html_css | (static only) | — | — | — | — |

Key observation: every mock is a self-contained `index.html`, so **one static
template serves all six source stacks** (phase 1). Framework templates
(phase 2+) are where code migration (mock → components) is needed.

Build-system variants differ only in the Dockerfile install/run lines and the
lockfile; they are separate catalog entries so each is tested on its own.

## 5. Generated-service contract (every template's docker-compose.yaml)

- Reads `APP_ID` from the project `.env` (DNS label: `[a-z0-9-]`, ≤ 63 chars).
  Derived from run id + option: `run_20261008_101500_ab12cd34` + `op1` →
  `run-20261008-101500-ab12cd34-op1` (underscores → hyphens, lowercased).
- `APP_HOST` defaults to `${APP_ID}.localhost` (browsers resolve `*.localhost`
  to 127.0.0.1 with no DNS changes; mirrors an Ingress host in Kubernetes).
- Container listens on **port 3000**; **no host ports published** — Traefik is
  the only way in.
- Joins the external network **`traefik_webgateway`**.
- Labels: `traefik.enable=true`, `traefik.docker.network=traefik_webgateway`,
  router `${APP_ID}` with ``Host(`${APP_HOST}`)`` on entrypoint `web`,
  service `${APP_ID}` → `loadbalancer.server.port=3000`.
- Container `healthcheck` against `http://127.0.0.1:3000/` (Traefik's Docker
  provider skips unhealthy containers).
- Compose project name = `APP_ID`, so `docker compose down` is per option.

## 6. System gateway (root docker-compose.yml)

- New `traefik` service (Traefik v3, Docker provider, `exposedByDefault=false`,
  `network=traefik_webgateway`), entrypoint `web` on container `:80`, published
  on host **3311**. Dashboard bound to `127.0.0.1` only.
- Root compose defines the network with fixed name `traefik_webgateway`, so
  generated apps can declare it `external: true`.
- Routes: ``Host(`localhost`)`` → frontend `:5173` (the UI, incl. Vite HMR
  websockets and the proxied `/generate-code` websocket).
- Mounts `/var/run/docker.sock` read-only.

### Trust boundary

To build and start generated apps the backend needs the Docker CLI and the
host Docker socket. That is root-equivalent on the host. Acceptable for local
use; must be called out in the README and gated behind an env flag
(`STACK_GENERATOR_ENABLED`) so the default install does not mount the socket.

## 7. "🚀 Build app" pipeline (phase 2+ backend work)

1. Create `data/runs/<run-id>/` (uploads + `op<N>/design/mock.html` are written
   at generation time, so this step only validates them).
2. Resolve target stack from catalog (source stack + chosen build system).
3. Derive app name from the prompt (slug; fallback `app-<short-run-id>`).
4. Per option: copy template → `op<N>/app/`, run the stack's init/scaffold
   step, migrate `mock.html` into the stack (phase 1: copy as
   `public/index.html`; phase 2: LLM-assisted migration into components).
5. `git init`, commit `:tada: First version`.
6. `docker compose up -d --build`; poll health; report
   `http://<APP_HOST>:3311` per option back to the UI.

Errors at any step are reported per option; one option failing does not stop
the other.

## 8. UI

- Settings: new **Build system** select (`pnpm` default, `npm`, `bun` — only
  values with a catalog entry for the current source stack are enabled).
- "🚀 Build app" button next to "Select & edit"; shows per-option
  progress and the resulting URL.

## 9. Testing

- Template tests (local, Docker): for each catalog entry, scaffold into a temp
  dir with a fixture mock, `docker compose up -d --build`, then
  `curl -H "Host: <APP_HOST>" http://localhost:3311/` → 200 and contains the
  fixture marker; `docker compose down`.
- Backend unit tests: catalog parsing/validation, `APP_ID` derivation, app-name
  slugging, workspace layout writer.
- Frontend: lint + unit tests for the Build system setting.

## 10. Phases

1. Gateway + `static-pnpm-html` template, verified end-to-end behind Traefik.
2. `nextjs-pnpm-react-tailwind` template (production Dockerfile: multi-stage,
   standalone output, non-root, pinned pnpm via corepack, cache mounts,
   healthcheck).
3. Backend pipeline + run workspace + UI button/setting.
4. npm/bun variants and phase-3 templates from the matrix.
