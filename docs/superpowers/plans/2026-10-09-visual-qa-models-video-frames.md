# Visual QA, fluid layouts, model upgrade, video frames — design + plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. TDD every task; commit per task with explicit paths.

**Why (observed 2026-10-09, run `run_20261009_052529_095f9cb5`):** the two options of an AI edit differed by one token (`shadow-emerald-100` vs `-200`) and Build app built both; nothing verifies options differ or that the built app matches its mock; generated pages stop growing (`max-w-sm` card, the system prompt has no responsive rule); AI edits never use Claude (Gemini 3 Flash minimal + GPT 5.6 Terra low); video goes to Gemini only; the Claude/Gemini model registry is a generation behind.

**Spec (parent):** `docs/superpowers/specs/2026-10-08-stack-generator-design.md`

## Global Constraints / Contracts (binding for all lanes)

### Visual QA (backend → UI)

- Renderer: the existing headless Chromium (`backend/preview_screenshot/`), never a new browser install.
- Widths: `375, 768, 1280, 1920`; height 900; full-page screenshot at 1280 stored as the option's thumbnail.
- Stored (gitignored) at `data/runs/<run-id>/qa/<ui-commit-hash>/op<N>-<width>.png` (+ `app-op<N>-1280.png` after builds) and `qa/<ui-commit-hash>/qa.json` (the `visualQa.data` payload). `qa/` is added to the run `.gitignore`.
- Served by `GET /api/runs/{run_id}/qa/{commit_hash}/{file}` (names must match `^(app-)?op\d+-\d+\.png$`; 404 otherwise).
- `renderOk`: page loaded without uncaught errors AND the 1280 screenshot is not blank (≥ 98% of pixels within ±8 of the most common colour = blank).
- Duplicates: perceptual similarity of the 1280 screenshots, `similarity ∈ [0,1]` (1 = identical; normalised mean absolute difference of 256-px-wide greyscale thumbnails is fine). `duplicateOf` = lowest earlier option index with `similarity ≥ 0.97`, else null.
- Responsive check per width: `horizontalOverflow = documentElement.scrollWidth > innerWidth + 1`; `contentWidthRatio` = width of the union bounding box of visible elements (skip `html`, `body`, zero-size elements) ÷ viewport width. **Pass** = no overflow at any width AND `contentWidthRatio ≥ 0.85` at 1280 and 1920.
- WS message after `versionCommitted` (best-effort; failures log and send nothing, never break generation):
  `{"type":"visualQa","variantIndex":0,"data":{"commitHash":str,"options":[{"index":int,"screenshot":str,"renderOk":bool,"error":str|null,"duplicateOf":int|null,"similarity":float|null,"responsive":{"pass":bool,"widths":[{"width":int,"contentWidthRatio":float,"horizontalOverflow":bool}]}}]}}` (`screenshot` = URL path of the 1280 PNG).
- Build: `POST /api/runs/{run_id}/build` body gains `options?: int[]` (0-based). Absent → every option that `qa.json` doesn't mark as a duplicate (no QA → all). The frontend sends `[selectedIndex]` by default, or all non-duplicates when the user ticks "Build all distinct options".
- After an option reaches `running`, the builder screenshots the app through the gateway (`GATEWAY_INTERNAL_URL`, default `http://host.docker.internal:3311`, header `Host: <APP_HOST>`; compose adds `extra_hosts: ["host.docker.internal:host-gateway"]` to the backend) and adds to `OptionStatus`: `screenshot: str|null` (app PNG URL), `parity: float|null` (similarity to the mock's 1280 screenshot), `responsive` (same shape), `render_ok: bool|null`. Parity < 0.80 → `step_message` "Running — differs from mock (parity 0.xx)". Never changes state to failed.

### Fluid layout policy (prompts)

Add to the generation system prompt (all stacks) and the Next.js migration prompt, as one triple-quoted block:
"Fluid, full-canvas layout: the page root fills the whole viewport width and at least its height (`w-full min-h-screen`); never wrap the page in a fixed or max-width container; sections span the full width and reflow to use extra space at `lg`/`xl`/`2xl` (more columns, larger gutters) and stack cleanly at 375 px with no horizontal scrolling; cap width only for long-form text blocks (`max-w-prose`), never for the layout itself."

### Models (backend registry)

- Add to `llm.py` + provider configs (API ids verified live 2026-10-09 with the user's keys): Anthropic `claude-fable-5-1` (effort low/medium/high/xhigh/max), `claude-opus-5-5` (low/medium/high/xhigh/max), `claude-sonnet-5-5`, `claude-haiku-5-5`; Gemini `gemini-3.8-flash` (minimal/low/high — mirror `GEMINI_3_FLASH_PREVIEW_*`); OpenAI `gpt-5.6-luna` if absent (mirror `GPT_5_6_SOL_*`). Keep old entries (evals use them).
- Choice sets (`routes/model_choice_sets.py`), quality-first, **a different provider per option so options differ**:
  - Image create (all keys): `CLAUDE_FABLE_5_1_HIGH, GEMINI_3_1_PRO_PREVIEW_HIGH, GPT_5_6_SOL_HIGH, CLAUDE_OPUS_5_5_MEDIUM`
  - Text create (all keys): `CLAUDE_FABLE_5_1_HIGH, GPT_5_6_SOL_HIGH, GEMINI_3_8_FLASH_HIGH, CLAUDE_OPUS_5_5_MEDIUM`
  - Update (all keys): `CLAUDE_OPUS_5_5_MEDIUM, GPT_5_6_SOL_HIGH`
  - Fallback sets: `CLAUDE_OPUS_4_8_*`/`CLAUDE_SONNET_4_6` → `CLAUDE_OPUS_5_5_MEDIUM`/`CLAUDE_SONNET_5_5`; `GEMINI_3_FLASH_PREVIEW_*` → `GEMINI_3_8_FLASH_*`. Update `tests/test_model_selection.py`.
  - Migration (`stack_generator/migrate.py`): Anthropic `CLAUDE_OPUS_5_5_MEDIUM`, OpenAI `GPT_5_6_SOL_HIGH`, Gemini `GEMINI_3_8_FLASH_HIGH`.
- Pricing: if `backend/costs/` has a price table, add the new models (unpriced models are not bounded by `GENERATION_MAX_COST_USD`). If the real price is unknown, use the closest sibling's price and say so in the report.

### Video → frames

- Frontend extracts frames in the browser (`<video>` + `<canvas>`): 1 frame/s, max 20 (always including first and last), longest side 1280 px, JPEG q=0.85. Sends `prompt.videoFrames: string[]` (data URLs) next to `prompt.videos`.
- Backend video model selection (2 variants):
  - Anthropic + Gemini: `[CLAUDE_FABLE_5_1_HIGH (frames), GEMINI_3_1_PRO_PREVIEW_HIGH (video)]`
  - Anthropic only: `[CLAUDE_FABLE_5_1_HIGH, CLAUDE_OPUS_5_5_MEDIUM]` (frames)
  - OpenAI only: `[GPT_5_6_SOL_HIGH, GPT_5_6_SOL_MEDIUM or closest]` (frames)
  - Gemini only: unchanged (video).
  - No frames and no Gemini key → the existing "Video mode requires a Gemini API key" error.
- Frames prompt (`prompts/create/video.py`): "These are N frames sampled at 1 fps from a screen recording of an app, in order. Reconstruct the app, including the states and interactions the frames show." Frame models get image parts; Gemini still gets the video.
- The run workspace saves frames as `uploads/screenshots/frame-<NN>.jpg`.

## Lanes and tasks

### Lane D — backend Visual QA
Files: `backend/stack_generator/visual_qa.py` (new), `backend/routes/runs.py` (QA route), `backend/routes/generate_code.py` (QA after versionCommitted), `backend/stack_generator/workspace.py` (`.gitignore` `qa/`), `backend/stack_generator/builder.py` (options + parity), `docker-compose.yml` (extra_hosts + `GATEWAY_INTERNAL_URL`).
1. `visual_qa.py`: `async capture(html: str, widths=(375,768,1280,1920)) -> CaptureResult`, `similarity(a: bytes, b: bytes) -> float`, `is_blank(png: bytes) -> bool`, `async run_version_qa(workspace, ui_commit_hash) -> dict` (the `visualQa.data` shape, also written to `qa.json`). Real-Chromium tests on tiny HTML: identical → ≥ 0.99; very different → < 0.8; blank → renderOk False; centred `max-w-sm` card → responsive.pass False with ratio < 0.5 at 1920; full-width grid → pass True; a `width:2000px` div → overflow at 375.
2. QA route + `qa/` gitignore + WS `visualQa` (best-effort, after `versionCommitted`; bounded ~20 s; skipped if it can't finish).
3. Builder `options` selection (default skips duplicates via `qa.json`) + post-run app screenshot/parity/responsive + compose wiring.

### Lane G — backend models, prompts, video frames
Files: `backend/llm.py`, `backend/agent/providers/*` configs, `backend/routes/model_choice_sets.py`, `backend/routes/generate_code.py` (model selection + `videoFrames` param), `backend/prompts/system_prompt.py`, `backend/prompts/create/video.py` (+ message builder/request parsing as needed), `backend/stack_generator/prompts.py` + `migrate.py` model constants, `backend/costs/`.
1. Registry + configs + choice sets + tests.
2. Fluid layout policy in the system prompt and migration prompt; tests that it's present for every stack and in the migration system prompt.
3. Video frames: parsing, per-model prompt (frames vs video), selection table, workspace saving; tests.

### Lane E — frontend
1. `visualQa` → store per commit (`commit.visualQa`); variant tiles show "≈ Option N (97%)", "⚠ not responsive", "⚠ blank render"; **the chat row** (sidebar assistant row for that version) shows the QA screenshot thumbnail(s) whenever an option fails a check, click to open full size.
2. Build panel: option checkboxes (default the selected option; "Build all distinct options" excludes duplicates); per option app screenshot + parity % + responsive badge; sends `options`.
3. Video frames: `lib/videoFrames.ts` (pure timestamp/limit helpers, unit-tested) + `<video>`/`<canvas>` extraction at upload; attach `videoFrames`; show "N frames extracted" in the upload preview.

### Coordinator — E2E
Rebuild the user's feature stack; text create + AI edit (expect visibly distinct edit options from two providers); check QA badges/thumbnails; build the selected option; check parity + responsive in the panel; short video upload (frames reach Claude). Report with screenshots.
