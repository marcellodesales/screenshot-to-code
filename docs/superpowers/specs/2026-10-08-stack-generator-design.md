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

### 2.1 Git history of a run (versions)

`data/runs/<run-id>/` is **one git repo per run**. `uploads/` is gitignored
(videos can be large); everything else is tracked.

- **Commit 1 — the mock only.** When a create generation finishes, commit
  `stack.yaml` + every `op<N>/design/mock.html` as
  `:art: Version 1 — mock (<source-stack>)`.
- **Every later UI version is a git commit on the same files.** AI edits
  ("Edit" versions) and manual code edits overwrite `op<N>/design/mock.html`
  (never `mock_v2.html`): `:art: Version <n> — <edit instruction or "manual edit">`.
- **Branching follows the UI.** The UI lets the user edit an older version,
  which forks its history. The git parent of a version commit is the git
  commit of its UI parent version (written with `git commit-tree`), every
  version is pinned by `refs/s2c/versions/<ui-commit-hash>`, and `main` points
  at the most recent version. SHAs live only in those refs: `stack.yaml`'s
  versions index records `n`, `ui_commit_hash`, `parent` and `message`,
  never a SHA, so the committed `stack.yaml` always matches the working copy.
- **Commit 2+ — the app.** "🚀 Build app" commits `op<N>/app/**` on top of
  the version it was built from: `:tada: First version` for the first build,
  `:rocket: Build app from version <n>` afterwards.
- **The UI shows the SHA.** After each version is committed the backend sends
  `versionCommitted {commitHash, gitSha}`; the history panel shows the short
  SHA next to "Version N" while keeping the existing version UX.
- Commit author: `screenshot-to-code <noreply@screenshot-to-code.local>`.

### 2.2 Linking requests to a run

Today nothing ties an edit request to its create request (each websocket
request gets a fresh `generation_id`; the UI's commit graph lives only in
browser memory with `nanoid` hashes). New protocol fields:

- Create: backend allocates `run-id`, sends `runInfo {runId}` first; the UI
  stores it on the project.
- Every request then sends `runId`, `commitHash` (the UI commit being
  generated) and `parentCommitHash`; the backend commits into that run.
- Manual edits: the code editor's `onCodeChange` (currently a no-op in
  `PreviewPane.tsx`) is wired up. The first edit after an AI version creates
  a new UI version of type `code_edit` (child of the current head);
  subsequent edits update that same version. Saves are debounced (1.5 s idle)
  and sent to `PUT /api/runs/{runId}/versions/{commitHash}` →
  `{gitSha}`; each save is a new git commit on that version's ref.

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
host Docker socket. **That socket is root-equivalent on the host**: acceptable
for local use only, and called out in the README and in `docker-compose.yml`.

What is implemented: the socket is mounted in every install — Traefik needs it
(read-only) for its Docker provider anyway, and the backend mounts it so
"Build app" can run `docker`/`docker compose` on the host daemon. The
protection is the env flag `STACK_GENERATOR_ENABLED` (default `false`): unless
it is `true`, the build endpoints (`POST`/`GET /api/runs/{runId}/build`)
answer **403** and the backend never invokes Docker. Users who do not want the
backend to hold the socket at all can drop that volume from their compose
file; the rest of the app works without it.

## 7. "🚀 Build app" pipeline (phase 2+ backend work)

Triggered by `POST /api/runs/{runId}/build {commitHash, buildSystem}`;
progress via `GET /api/runs/{runId}/build` (per-option state, step, URL,
error). Builds every option of the selected version, in parallel.

1. Check out the version's mocks (`refs/s2c/versions/<commitHash>`); uploads
   and `op<N>/design/mock.html` already exist from generation time.
2. Resolve target stack from catalog (source stack + chosen build system;
   default: the framework template for the source stack, else static).
3. Derive app name from the prompt (slug; fallback `app-<short-run-id>`).
4. Per option: scaffold into `op<N>/app/` via the template's `scaffold.sh`
   (static templates: copy), then **migrate** `mock.html` into the stack:
   - static: copy as `public/index.html`;
   - framework: one LLM call per option that turns the mock into the
     template's `migration_targets` (e.g. `src/app/page.tsx`,
     `src/app/layout.tsx`, `src/components/*.tsx`), returned as a file map
     and validated (paths inside the app, allowed extensions only);
   - the generator always writes `layout.tsx` with a **local system font
     stack** instead of the scaffold's `next/font/google`, so builds need no
     network access to Google Fonts.
5. Lockfile (`scaffold.sh` produces it after the migrated sources land), then
   commit (§2.1).
6. Write `.env` (`APP_ID`, `APP_HOST`), `docker compose up -d --build --wait`,
   then report `http://<APP_HOST>:3311/` per option to the UI.

Errors at any step are reported per option; one option failing does not stop
the other.

### 7.1 Docker from inside the backend container

The backend talks to the host daemon through the mounted socket, so bind
mounts in `docker run -v` would resolve on the *host*, not in the backend
container. Therefore `scaffold.sh` moves files with `docker create` +
`docker cp` (no bind mounts), and generated compose files use only build
contexts (sent by the CLI) — never host volumes. The backend image adds the
Docker CLI + compose plugin and `git`; templates are mounted read-only at
`/opt/stack-templates` (`STACK_TEMPLATES_DIR`).

## 8. UI

- Settings: new **Build system** select (`pnpm` default, `npm`, `bun` — only
  values with a catalog entry for the current source stack are enabled).
- "🚀 Build app" button next to "Select & edit"; shows per-option
  progress and the resulting URL.
- History panel: short git SHA next to each "Version N" (tooltip: full SHA).

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
