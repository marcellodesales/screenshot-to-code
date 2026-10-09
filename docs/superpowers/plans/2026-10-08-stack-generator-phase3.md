# Stack Generator Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every generation as a git-versioned run workspace whose SHAs the UI shows, and add "🚀 Build app" that migrates the selected version's mocks into a catalogued stack, commits it and runs it behind Traefik.

**Architecture:** New backend package `backend/stack_generator/` (catalog, naming, workspace+git, migration, builder) used by the websocket pipeline (versions) and new `/api/runs/...` + `/api/stacks` HTTP routes. Frontend gains `runId`/`gitSha` on the project, wires manual code edits into versions, a Build system setting and a Build app button with progress.

**Tech Stack:** FastAPI, pytest(-asyncio), PyYAML, git CLI via `subprocess`, Docker CLI + compose (host socket); React + zustand + Jest (ts-jest).

**Spec:** `docs/superpowers/specs/2026-10-08-stack-generator-design.md` (§2, §2.1, §2.2, §3, §5, §7, §7.1, §8)

## Global Constraints

- Stack ids: `<runtime>-<build-system>-<ui>-<styling>` (`static-pnpm-html`, `nextjs-pnpm-react-tailwind`).
- Run dir: `${RUNS_DIR:-/data/runs}/<run-id>/`; run id format `run_YYYYmmdd_HHMMSS_<8 hex>` (same as `fs_logging/agent_runs.py`).
- Layout: `stack.yaml`, `uploads/{video,screenshots}/`, `op<N>/design/mock.html` (1-based), `op<N>/app/`. `uploads/` gitignored.
- Commit messages (exact): `:art: Version 1 — mock (<source-stack>)`, `:art: Version <n> — <instruction>`, `:art: Version <n> — manual edit`, `:tada: First version`, `:rocket: Build app from version <n>`.
- Git author/committer: `screenshot-to-code <noreply@screenshot-to-code.local>`.
- Version refs: `refs/s2c/versions/<ui-commit-hash>`; `main` = most recent version/build.
- APP_ID: `<run-id with _→->-op<N>` lowercased, `[a-z0-9-]`, ≤ 63 chars; APP_HOST `<APP_ID>.localhost`; URL `http://<APP_HOST>:3311/`.
- Gateway network `traefik_webgateway`; container port 3000; no host ports.
- `STACK_GENERATOR_ENABLED` (default off) gates the build endpoints (403 with message when off). Version tracking only needs `RUNS_DIR` writable; workspace failures never break generation.
- Templates dir: `STACK_TEMPLATES_DIR` (default `<repo>/internal/stack` resolved from `backend/..`; compose mounts it at `/opt/stack-templates`).
- New WS message types: `runInfo` (`value` = run id), `versionCommitted` (`data` = `{commitHash, gitSha}`). New request params: `runId`, `commitHash`, `parentCommitHash`.
- Backend rule (CLAUDE.md): after every change `poetry run pytest` + `poetry run pyright` with no new warnings in changed files. Frontend: `pnpm lint` (baseline errors exist — no new ones) + `pnpm test`.
- Prompt text: triple-quoted strings; interpolated multi-line prompts as one triple-quoted f-string.

**How to run backend checks** (no host Poetry; the dev image `s2c-feat-backend:dev` has git + docker CLI; rebuild it with `docker build -t s2c-feat-backend:dev $W/backend` only if you change `pyproject.toml`/`poetry.lock`):
`docker run --rm -v "$W/backend:/app" -v "$W/internal/stack:/opt/stack-templates:ro" -e STACK_TEMPLATES_DIR=/opt/stack-templates s2c-feat-backend:dev sh -c 'poetry run pytest -q && poetry run pyright <changed files>'`
(`W` = the worktree root.)

## Review Focus

1. **Generation must never fail because of the workspace** (disk full, git missing, read-only `/data`): log and continue — test in Task 3.
2. **Malicious/odd LLM migration output** (absolute paths, `..`, `node_modules/`, huge files, non-allowed extensions) must be rejected, not written — test in Task 5.
3. **Update request for an unknown/crafted `runId`** (server restarted with a new data dir, or `../../etc`) → treated as no run, never path-traversed — tests in Task 2 (`run_dir_for`) and Task 3.
4. **Build clicked twice / while running** → second POST returns the running job, never two concurrent builds of one run — test in Task 6.
5. **Old localStorage settings without `buildSystem`** → `pnpm` back-filled — test in Task 9.

---

### Task 1: Catalog + naming

**Files:**
- Create: `backend/stack_generator/__init__.py`, `backend/stack_generator/catalog.py`, `backend/stack_generator/naming.py`
- Modify: `backend/config.py` (add `STACK_TEMPLATES_DIR`, `RUNS_DIR`, `STACK_GENERATOR_ENABLED`), `backend/pyproject.toml` (+ `pyyaml` direct dep; regenerate the lock inside the dev image with `poetry lock --no-update`)
- Test: `backend/tests/test_stack_catalog.py`, `backend/tests/test_stack_naming.py`

**Interfaces — Produces:**
- `@dataclass(frozen=True) class StackTemplate: id: str; source_stacks: list[str]; build_system: str; phase: int; status: str; path: Path; mock_path: str; has_scaffold: bool; migration_targets: list[str]`
- `load_catalog(templates_dir: Path | None = None) -> list[StackTemplate]` — merges `catalog.yaml` entries with each `<id>/template.yaml`; entries without a dir keep their catalog `status` and get `mock_path=""`.
- `resolve_template(source_stack: str, build_system: str, catalog: list[StackTemplate]) -> StackTemplate` — prefer an `available` non-static template for the source stack, else `static-<bs>-html`; `ValueError` if none.
- `app_id_for(run_id: str, option_index: int) -> str` (0-based index → `op<index+1>`).
- `app_slug_from_prompt(prompt_text: str, run_id: str) -> str` — npm-safe slug ≤ 40 chars; drop the words build, make, create, me, a, an, the, please, for, with; fallback `app-<last 8 chars of run_id>`.

- [ ] **Step 1: Write failing tests**
  - `test_load_catalog_reads_available_templates`: real `internal/stack` → `static-pnpm-html` and `nextjs-pnpm-react-tailwind` present with `status == "available"`; nextjs `has_scaffold is True`, `mock_path == "design/mock.html"`; static `mock_path == "public/index.html"`.
  - `test_resolve_prefers_framework_template`: `("react_tailwind","pnpm")` → `nextjs-pnpm-react-tailwind`; `("bootstrap","pnpm")` → `static-pnpm-html`; `("react_tailwind","bun")` raises `ValueError`.
  - `test_app_id_for`: `app_id_for("run_20261008_101500_ab12cd34", 0) == "run-20261008-101500-ab12cd34-op1"`; a 200-char run id still matches `^[a-z0-9-]{1,63}$` and ends with `-op1`.
  - `test_app_slug_from_prompt`: `"Build me a Coffee Shop landing page!!"` → `"coffee-shop-landing-page"`; `""` → `"app-ab12cd34"`.
- [ ] **Step 2: Run, verify FAIL** (module missing).
- [ ] **Step 3: Implement** (`yaml.safe_load`).
- [ ] **Step 4: Run backend checks, verify PASS.**
- [ ] **Step 5: Commit** `feat(stack-generator): catalog loader and app naming`.

### Task 2: Run workspace + git versions

**Files:**
- Create: `backend/stack_generator/workspace.py`
- Test: `backend/tests/test_stack_workspace.py`

**Interfaces — Produces:**
- `new_run_id() -> str`
- `run_dir_for(run_id: str, runs_dir: Path | None = None) -> Path | None` — `None` unless `run_id` matches `^run_\d{8}_\d{6}_[0-9a-f]{8}$`.
- `class RunWorkspace`:
  - `create(run_id, *, source_stack, input_mode, prompt_text, runs_dir=None) -> RunWorkspace` — dirs, `.gitignore` with `uploads/`, `git init -b main`, `stack.yaml`.
  - `open(run_id, runs_dir=None) -> RunWorkspace | None`
  - `save_upload(kind: Literal["video","screenshots"], data_url: str) -> Path`
  - `commit_version(*, ui_commit_hash: str, parent_ui_commit_hash: str | None, option_codes: list[str], message: str) -> str` — writes `op<N>/design/mock.html` for N=1..len (removes `op<M>/design` beyond len), records `versions: [{n, ui_commit_hash, parent, sha, message}]` in `stack.yaml`, commits with `git commit-tree` whose parent is the parent version's ref (or none), updates `refs/s2c/versions/<hash>` and `main`; returns the full SHA.
  - `update_version(ui_commit_hash: str, option_index: int, code: str, message: str) -> str` — new commit on top of that version's ref; moves the ref and `main`.
  - `has_version(ui_commit_hash: str) -> bool`, `version_number(ui_commit_hash: str) -> int`, `option_codes(ui_commit_hash: str) -> list[str]`
  - `checkout_version(ui_commit_hash: str, dest: Path) -> None` (via `git archive`)
  - `commit_app(ui_commit_hash: str, message: str) -> str` — stages `op*/app/**` on top of that version's ref, moves `main`.
- All git calls via `_git(*args) -> str` (`subprocess.run(..., check=True, capture_output=True, text=True, cwd=self.path)` with author/committer env from Global Constraints).

- [ ] **Step 1: Write failing tests** (`tmp_path` as `runs_dir`; real `git`):
  - `test_create_initialises_repo_and_stack_yaml`: `stack.yaml` has `run_id`, `source_stack`, `input_mode`, `prompt`; `.gitignore` contains `uploads/`.
  - `test_commit_version_writes_mocks_and_message`: 2 option codes → `op1/design/mock.html`, `op2/design/mock.html`; `git log -1 --format=%s` == message; returned SHA == `refs/s2c/versions/h1`.
  - `test_fork_parent_is_parent_ref`: v1 (h1), v2 (h2, parent h1), v3 (h3, parent h1) → `git rev-parse <h3-sha>^` == h1 SHA; `main` == h3 SHA; `version_number("h3") == 3`.
  - `test_update_version_manual_edit`: new SHA ≠ old, its parent == old, ref moved.
  - `test_uploads_not_tracked`: `save_upload("video", "data:video/mp4;base64,AAAA")` → file under `uploads/video/`; `git status --porcelain` empty.
  - `test_run_dir_for_rejects_traversal`: `"../../etc"`, `"run_x"` → `None`.
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run backend checks, verify PASS.**
- [ ] **Step 5: Commit** `feat(stack-generator): git-versioned run workspace`.

### Task 3: Websocket integration (runInfo, versionCommitted)

**Files:**
- Modify: `backend/routes/generate_code.py` — `ExtractedParams` + `ParameterExtractionStage` gain `run_id`, `commit_hash`, `parent_commit_hash` (params `runId`, `commitHash`, `parentCommitHash`); new `RunWorkspaceMiddleware` after `ParameterExtraction`: opens the run (update) or creates one (create, or unknown/invalid id), sends `runInfo`, saves uploads from `prompt.images`/`prompt.videos` on create; after downstream generation returns, commits `context.completions` and sends `versionCommitted`.
- Test: `backend/tests/test_run_workspace_middleware.py`

**Interfaces — Consumes:** Task 2. **Produces:** `{"type":"runInfo","value":<run_id>,"variantIndex":0}`, `{"type":"versionCommitted","data":{"commitHash":..,"gitSha":..},"variantIndex":0}`.

Messages: create `:art: Version 1 — mock (<stack>)`; edit `:art: Version <n> — <prompt.text, first 72 chars>`. Skip committing when `commit_hash` is missing (old clients) or every completion is empty.

- [ ] **Step 1: Failing tests** (pattern: `tests/test_status_broadcast.py`; `monkeypatch.setenv("RUNS_DIR", str(tmp_path))`):
  - `test_create_sends_run_info_and_commits_version`: first message `runInfo`; completions `["<a/>","<b/>"]` → `versionCommitted` with 40-hex `gitSha`.
  - `test_update_reuses_run`: same `runId`, `commitHash="h2"`, `parentCommitHash="h1"` → no new run dir; new SHA's parent == h1 SHA.
  - `test_unknown_run_id_starts_new_run`: `runId="../../etc"` → a valid new run id in `runInfo`.
  - `test_workspace_failure_does_not_break_generation`: `RUNS_DIR` is a regular file → `next()` still awaited, no `throw_error`.
- [ ] **Steps 2–4: FAIL → implement → PASS (backend checks).**
- [ ] **Step 5: Commit** `feat(generate-code): record versions in the run workspace`.

### Task 4: Runs + stacks HTTP routes (manual edits, catalog)

**Files:**
- Create: `backend/routes/runs.py`; Modify: `backend/main.py` (include router)
- Test: `backend/tests/test_runs_routes.py` (call route functions directly, like `tests/test_design_systems.py`)

**Interfaces — Produces:**
- `GET /api/stacks` → `[{id, source_stacks, build_system, phase, status}]`.
- `PUT /api/runs/{run_id}/versions/{commit_hash}` body `{parentCommitHash: str | null, optionIndex: int, code: str}` → `{gitSha}`. Unknown version → `commit_version` with the parent's `option_codes` where `optionIndex` is replaced, message `:art: Version <n> — manual edit`; existing → `update_version`. 404 unknown run; 413 when `code` > 2 MB.

- [ ] **Step 1: Failing tests:** `test_list_stacks`, `test_put_version_creates_code_edit_version`, `test_put_version_updates_existing`, `test_put_version_unknown_run_404`, `test_put_version_too_large_413`.
- [ ] **Steps 2–4: FAIL → implement → PASS.**
- [ ] **Step 5: Commit** `feat(runs): manual-edit versions and stack catalog routes`.

### Task 5: Mock → stack migration

**Files:**
- Create: `backend/stack_generator/migrate.py`, `backend/stack_generator/prompts.py`
- Test: `backend/tests/test_stack_migrate.py`

**Interfaces — Produces:**
- `class MigrationError(Exception)`
- `apply_system_fonts(app_dir: Path, title: str) -> None` — rewrites `src/app/layout.tsx` (imports `./globals.css`, `metadata.title = title`, `<html lang="en">`, `<body className="antialiased">`, no `next/font`) and replaces Geist font variables in `src/app/globals.css` with a system font stack.
- `parse_file_map(raw: str) -> dict[str, str]` — JSON `{"files": {path: content}}`, optionally inside a ```json fence.
- `validate_file_map(files: dict[str, str], allowed_globs: list[str]) -> dict[str, str]` — `MigrationError` for absolute paths, `..`, paths not matching `allowed_globs` (template `migration_targets`), extensions outside `{.tsx,.ts,.css,.svg}`, a file > 200 KB, > 40 files.
- `MigrationLlm = Callable[[str, str], Awaitable[str]]` (system prompt, user prompt → raw text)
- `async def migrate_mock(*, mock_html: str, template: StackTemplate, app_title: str, llm: MigrationLlm) -> dict[str, str]` — static templates (`not template.has_scaffold`) return `{template.mock_path: mock_html}` without calling `llm`.
- `default_migration_llm(*, openai_api_key: str | None, anthropic_api_key: str | None, gemini_api_key: str | None) -> MigrationLlm` — one non-streaming completion through the existing provider layer (`agent/providers/factory.py`), preferring Anthropic, then OpenAI, then Gemini; `MigrationError("No API key for migration")` if none.
- Prompt (`prompts.py`): turn the single-file React+Tailwind mock into Next.js App Router TypeScript files limited to `migration_targets`; `"use client"` only where hooks/events are used; replace `React.useState`-style globals with imports; keep Tailwind classes; keep remote images as `<img>`; never use `next/font`; reply with only the JSON object.

- [ ] **Step 1: Failing tests:** `test_parse_file_map_accepts_fenced_json`, `test_validate_rejects_traversal_and_absolute` (`../x.tsx`, `/etc/passwd`), `test_validate_rejects_disallowed_targets` (`package.json`, `node_modules/a.ts`), `test_validate_rejects_oversize`, `test_migrate_static_skips_llm`, `test_migrate_nextjs_uses_llm_and_validates`, `test_apply_system_fonts_removes_next_font`.
- [ ] **Steps 2–4: FAIL → implement → PASS.**
- [ ] **Step 5: Commit** `feat(stack-generator): LLM mock migration with validated file map`.

### Task 6: Builder + build routes + compose wiring

**Files:**
- Create: `backend/stack_generator/builder.py`, `backend/routes/builds.py`; Modify: `backend/main.py`, `internal/stack/nextjs-pnpm-react-tailwind/scaffold.sh` (`docker create` + `docker cp`, no `-v` bind mounts — spec §7.1), `docker-compose.yml` (backend: `/var/run/docker.sock`, `./internal/stack:/opt/stack-templates:ro`, `STACK_TEMPLATES_DIR=/opt/stack-templates`, `RUNS_DIR=/data/runs`, `STACK_GENERATOR_ENABLED=${STACK_GENERATOR_ENABLED:-false}`), `README.md` (trust-boundary note + how to enable).
- Test: `backend/tests/test_stack_builder.py`, `backend/tests/test_builds_routes.py`

**Interfaces — Consumes:** Tasks 1, 2, 5. **Produces:**
- `OptionState = Literal["queued","scaffolding","migrating","committing","starting","running","failed"]`; `@dataclass OptionStatus: index: int; state: OptionState; step_message: str; url: str | None; error: str | None`; `@dataclass BuildJob: run_id: str; ui_commit_hash: str; build_system: str; template_id: str; options: list[OptionStatus]`.
- `CommandRunner = Callable[[list[str], Path], Awaitable[str]]` (injectable; default runs subprocess, raises with stderr on non-zero).
- `class BuildManager(runner: CommandRunner = ..., llm_factory=default_migration_llm)`: `start(run_id, ui_commit_hash, build_system, api_keys: dict[str, str | None]) -> BuildJob` (returns the existing job while one is running for that run), `get(run_id) -> BuildJob | None`. Options run concurrently; one failure doesn't stop others.
- Per option: checkout version mocks → scaffold (`scaffold.sh <op<N>/app> <slug> <sources>`; static: copy template) → `migrate_mock` + `apply_system_fonts` (framework) → `.env` (`APP_ID`, `APP_HOST`) → `commit_app` (`:tada: First version` first time, else `:rocket: Build app from version <n>`) → `docker compose --project-directory <app> up -d --build --wait` → `url = http://<APP_HOST>:3311/`.
- `POST /api/runs/{run_id}/build` body `{commitHash, buildSystem, openAiApiKey?, anthropicApiKey?, geminiApiKey?}` (keys fall back to env) → job JSON; 403 `{"detail": "Stack generator disabled (set STACK_GENERATOR_ENABLED=true)"}` when off. `GET /api/runs/{run_id}/build` → job JSON or 404.

- [ ] **Step 1: Failing tests:** `test_build_static_option_runs_compose` (fake runner; final `running`, url `http://run-…-op1.localhost:3311/`), `test_one_option_failure_isolated`, `test_second_start_returns_running_job`, `test_commit_messages_first_then_rebuild`, `test_build_route_disabled_403`.
- [ ] **Steps 2–4: FAIL → implement → PASS.** Then start the gateway and re-run `internal/stack/test-template.sh nextjs-pnpm-react-tailwind` to prove the `docker cp` scaffold still passes.
- [ ] **Step 5: Commit** `feat(stack-generator): Build app pipeline and routes`.

### Task 7: Frontend protocol (runId, version SHAs)

**Files:**
- Modify: `frontend/src/store/project-store.ts` (`runId: string | null`, `setRunId`, `setCommitGitSha(hash, sha)` — allowed on committed commits; `reset` clears `runId`), `frontend/src/components/commits/types.ts` (`BaseCommit.gitSha?: string`; `CommitType` += `"code_edit"` with `inputs: null`), `frontend/src/types.ts` (`CodeGenerationParams` += `runId?`, `commitHash?`, `parentCommitHash?`), `frontend/src/App.tsx` (`doGenerateCode` sends the three params; handle `runInfo` → `setRunId`, `versionCommitted` → `setCommitGitSha`), `frontend/src/generateCode.ts` (message types), `frontend/src/components/history/HistoryDisplay.tsx` (short SHA `slice(0, 7)`, `font-mono`, `title` = full SHA, next to the version badge).
- Test: `frontend/src/store/project-store.test.ts`

- [ ] **Step 1: Failing tests:** `setCommitGitSha sets gitSha on a committed commit`, `reset clears runId`.
- [ ] **Steps 2–4: FAIL → implement → PASS** (`cd frontend && pnpm test && pnpm lint`).
- [ ] **Step 5: Commit** `feat(frontend): run id and git SHA per version`.

### Task 8: Frontend manual edits → versions

**Files:**
- Modify: `frontend/src/store/project-store.ts` (`applyManualEdit(code: string): string` — head is an uncommitted `code_edit` → update its variant code; else create a `code_edit` commit with one variant, parent = head, set head; returns the commit hash), `frontend/src/components/preview/PreviewPane.tsx` (replace `setCode={() => {}}`; debounce 1500 ms via `frontend/src/hooks/useDebouncedCallback.ts`; after save `setCommitGitSha`), history label for `code_edit` = "Manual edit" (`HistoryDisplay.tsx`).
- Create: `frontend/src/lib/runs.ts` — `saveVersion(runId, commitHash, body: {parentCommitHash: string | null; optionIndex: number; code: string}, fetcher = fetch) => Promise<{gitSha: string}>` (`PUT ${HTTP_BACKEND_URL}/api/runs/{runId}/versions/{commitHash}`).
- Test: `project-store.test.ts` (`applyManualEdit creates code_edit once then updates it`), `frontend/src/lib/runs.test.ts` (fake fetcher: URL, method `PUT`, JSON body).

- [ ] **Steps 1–5: TDD, `pnpm test`, `pnpm lint`, commit `feat(frontend): track manual code edits as versions`.**

### Task 9: Frontend Build system setting + 🚀 Build app

**Files:**
- Create: `frontend/src/lib/settings.ts` (`withDefaultBuildSystem(s: Partial<Settings>): Settings` back-fill), `frontend/src/components/build/BuildAppPanel.tsx` (polls `GET /api/runs/{runId}/build` every 2 s until every option is `running` or `failed`; per option: state, step message, URL link opening a new tab, error).
- Modify: `frontend/src/types.ts` (`Settings.buildSystem: "pnpm" | "npm" | "bun"`), `frontend/src/App.tsx` (default `"pnpm"`; back-fill effect via `withDefaultBuildSystem`), `frontend/src/components/settings/SettingsTab.tsx` ("Build system" card, `Select` pattern; options disabled unless `GET /api/stacks` lists an `available` entry with that build system), `frontend/src/components/preview/PreviewPane.tsx` (`🚀 Build app` button, `data-testid="build-app"`, in the toolbar group with Select & edit / Download; enabled when `canSelectAndEdit && runId && currentCommit.gitSha`; opens `BuildAppPanel`), `frontend/src/lib/runs.ts` (`startBuild(runId, body: {commitHash; buildSystem; openAiApiKey?; anthropicApiKey?; geminiApiKey?}, fetcher)`, `getBuild(runId, fetcher)`).
- Test: `frontend/src/lib/runs.test.ts` (`startBuild` POST body), `frontend/src/lib/settings.test.ts` (`withDefaultBuildSystem({}).buildSystem === "pnpm"`, keeps `"bun"`).

- [ ] **Steps 1–5: TDD, `pnpm test`, `pnpm lint`, commit `feat(frontend): Build system setting and Build app button`.**

### Task 10: End-to-end verification (coordinator)

- [ ] Rebuild the feature stack (`-p s2c-feat`, alternate host ports, `STACK_GENERATOR_ENABLED=true`), generate via the UI, confirm `data/runs/<run-id>` git log shows Version 1 → AI edit → manual edit with SHAs matching the history panel; click 🚀 Build app; open each `http://<app-id>.localhost:3311/`; confirm the `:tada: First version` commit. Tear down.
