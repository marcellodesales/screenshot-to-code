import { HTTP_BACKEND_URL } from "../config";
import { BuildSystem } from "../types";
import {
  formatPercent,
  normalizeResponsive,
  ResponsiveResult,
  VisualQaData,
} from "./visualQa";

// Client for the backend run workspace routes (spec §2.2, §7).

export interface SaveVersionBody {
  parentCommitHash: string | null;
  optionIndex: number;
  code: string;
}

export class RunsApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "RunsApiError";
    this.status = status;
  }
}

function apiUrl(path: string) {
  return `${HTTP_BACKEND_URL.replace(/\/$/, "")}${path}`;
}

function runUrl(runId: string, suffix: string) {
  return apiUrl(`/api/runs/${encodeURIComponent(runId)}${suffix}`);
}

// FastAPI errors are `{"detail": "..."}` (or a validation list); fall back to
// the raw body / status text.
async function errorFrom(response: Response): Promise<RunsApiError> {
  const text = await response.text().catch(() => "");
  let message = text;
  try {
    const parsed: unknown = JSON.parse(text);
    if (
      parsed &&
      typeof parsed === "object" &&
      "detail" in parsed &&
      typeof parsed.detail === "string"
    ) {
      message = parsed.detail;
    }
  } catch {
    /* not JSON */
  }
  return new RunsApiError(
    response.status,
    message || `Request failed (${response.status})`
  );
}

async function requestJson<T>(
  fetcher: typeof fetch,
  url: string,
  init: RequestInit = {}
): Promise<T> {
  const response = await fetcher(url, init);
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as T;
}

function jsonInit(method: "PUT" | "POST", body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export function saveVersion(
  runId: string,
  commitHash: string,
  body: SaveVersionBody,
  fetcher: typeof fetch = fetch
): Promise<{ gitSha: string }> {
  return requestJson<{ gitSha: string }>(
    fetcher,
    runUrl(runId, `/versions/${encodeURIComponent(commitHash)}`),
    jsonInit("PUT", body)
  );
}

// ---- Build app (spec §7) ----

export type OptionState =
  | "queued"
  | "scaffolding"
  | "migrating"
  | "committing"
  | "starting"
  | "running"
  | "failed";

export interface OptionStatus {
  index: number;
  state: OptionState;
  stepMessage: string;
  url: string | null;
  error: string | null;
  // Set once the option is running: app screenshot URL (relative to
  // HTTP_BACKEND_URL), similarity to the mock's 1280 screenshot, responsive
  // check and render check.
  screenshot: string | null;
  parity: number | null;
  responsive: ResponsiveResult | null;
  renderOk: boolean | null;
}

export interface BuildJob {
  runId: string;
  uiCommitHash: string;
  buildSystem: string;
  templateId: string;
  options: OptionStatus[];
}

export interface StartBuildBody {
  commitHash: string;
  buildSystem: BuildSystem;
  openAiApiKey?: string | null;
  anthropicApiKey?: string | null;
  geminiApiKey?: string | null;
  // 0-based option indexes to build; absent → backend default (non-duplicates)
  options?: number[];
}

type JsonObject = Record<string, unknown>;

function asObject(value: unknown): JsonObject {
  return value && typeof value === "object" ? (value as JsonObject) : {};
}

// The backend serialises dataclasses (snake_case); accept camelCase as well.
function pick(obj: JsonObject, snake: string, camel: string): unknown {
  return obj[snake] ?? obj[camel];
}

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function strOrNull(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function numOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function boolOrNull(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

export function normalizeBuildJob(raw: unknown): BuildJob {
  const job = asObject(raw);
  const options = Array.isArray(job.options) ? job.options : [];
  return {
    runId: str(pick(job, "run_id", "runId")),
    uiCommitHash: str(pick(job, "ui_commit_hash", "uiCommitHash")),
    buildSystem: str(pick(job, "build_system", "buildSystem")),
    templateId: str(pick(job, "template_id", "templateId")),
    options: options.map((rawOption, position) => {
      const option = asObject(rawOption);
      return {
        index: typeof option.index === "number" ? option.index : position,
        state: str(option.state, "queued") as OptionState,
        stepMessage: str(pick(option, "step_message", "stepMessage")),
        url: strOrNull(option.url),
        error: strOrNull(option.error),
        screenshot: strOrNull(option.screenshot),
        parity: numOrNull(option.parity),
        responsive: normalizeResponsive(option.responsive),
        renderOk: boolOrNull(pick(option, "render_ok", "renderOk")),
      };
    }),
  };
}

export function isBuildFinished(job: BuildJob): boolean {
  return (
    job.options.length > 0 &&
    job.options.every(
      (option) => option.state === "running" || option.state === "failed"
    )
  );
}

export async function startBuild(
  runId: string,
  body: StartBuildBody,
  fetcher: typeof fetch = fetch
): Promise<BuildJob> {
  const raw = await requestJson<unknown>(
    fetcher,
    runUrl(runId, "/build"),
    jsonInit("POST", body)
  );
  return normalizeBuildJob(raw);
}

// null when the run has never been built (404).
export async function getBuild(
  runId: string,
  fetcher: typeof fetch = fetch
): Promise<BuildJob | null> {
  try {
    const raw = await requestJson<unknown>(fetcher, runUrl(runId, "/build"), {
      method: "GET",
    });
    return normalizeBuildJob(raw);
  } catch (error) {
    if (error instanceof RunsApiError && error.status === 404) return null;
    throw error;
  }
}

// ---- Stack catalog ----

export interface StackCatalogEntry {
  id: string;
  source_stacks: string[];
  build_system: string;
  phase: number;
  status: string;
}

export function listStacks(
  fetcher: typeof fetch = fetch
): Promise<StackCatalogEntry[]> {
  return requestJson<StackCatalogEntry[]>(fetcher, apiUrl("/api/stacks"), {
    method: "GET",
  });
}

// Build systems with an `available` catalog entry for the source stack.
export function enabledBuildSystems(
  stacks: StackCatalogEntry[],
  sourceStack: string
): Set<string> {
  const enabled = new Set<string>();
  for (const entry of stacks) {
    if (
      entry.status === "available" &&
      Array.isArray(entry.source_stacks) &&
      entry.source_stacks.includes(sourceStack)
    ) {
      enabled.add(entry.build_system);
    }
  }
  return enabled;
}

// Request body for "🚀 Build app": keys left empty in Settings are omitted so
// the backend falls back to its own environment.
export function buildStartBody(
  commitHash: string,
  settings: {
    buildSystem: BuildSystem;
    openAiApiKey: string | null;
    anthropicApiKey: string | null;
    geminiApiKey: string | null;
  },
  options?: number[]
): StartBuildBody {
  const body: StartBuildBody = {
    commitHash,
    buildSystem: settings.buildSystem,
  };
  if (options) body.options = [...new Set(options)].sort((a, b) => a - b);
  if (settings.openAiApiKey) body.openAiApiKey = settings.openAiApiKey;
  if (settings.anthropicApiKey) body.anthropicApiKey = settings.anthropicApiKey;
  if (settings.geminiApiKey) body.geminiApiKey = settings.geminiApiKey;
  return body;
}

// Options worth building: every option visual QA didn't mark as a duplicate
// (no QA → all of them).
export function distinctOptionIndices(
  optionCount: number,
  visualQa: VisualQaData | null | undefined
): number[] {
  const duplicates = new Set(
    (visualQa?.options ?? [])
      .filter((option) => option.duplicateOf !== null)
      .map((option) => option.index)
  );
  return Array.from({ length: optionCount }, (_, index) => index).filter(
    (index) => !duplicates.has(index)
  );
}

export const LOW_PARITY_THRESHOLD = 0.8;

export function parityLabel(parity: number): { text: string; isLow: boolean } {
  return {
    text: `matches mock ${formatPercent(parity)}`,
    isLow: parity < LOW_PARITY_THRESHOLD,
  };
}
