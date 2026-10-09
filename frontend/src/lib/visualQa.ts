import { HTTP_BACKEND_URL } from "../config";

// Visual QA of a version's options (backend → UI `visualQa` WS message).
// Screenshot paths are relative to HTTP_BACKEND_URL
// (`/api/runs/{runId}/qa/{commitHash}/op<N>-1280.png`).

export interface ResponsiveWidth {
  width: number;
  contentWidthRatio: number;
  horizontalOverflow: boolean;
}

export interface ResponsiveResult {
  pass: boolean;
  widths: ResponsiveWidth[];
}

export interface VisualQaOption {
  index: number;
  screenshot: string | null;
  renderOk: boolean;
  error: string | null;
  duplicateOf: number | null;
  similarity: number | null;
  responsive: ResponsiveResult | null;
}

export interface VisualQaData {
  commitHash: string;
  options: VisualQaOption[];
}

export type QaIssueKind = "duplicate" | "blank_render" | "not_responsive";

export interface QaIssue {
  kind: QaIssueKind;
  label: string;
}

export interface QaFailure {
  index: number;
  screenshotUrl: string | null;
  labels: string[];
}

type JsonObject = Record<string, unknown>;

function asObject(value: unknown): JsonObject | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}

// Accept camelCase (the WS contract) and snake_case (dataclass JSON).
function pick(obj: JsonObject, camel: string, snake: string): unknown {
  return obj[camel] ?? obj[snake];
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function strOrNull(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function normalizeResponsive(raw: unknown): ResponsiveResult | null {
  const obj = asObject(raw);
  if (!obj) return null;
  const widths = Array.isArray(obj.widths) ? obj.widths : [];
  return {
    pass: obj.pass === true,
    widths: widths.map((rawWidth) => {
      const w = asObject(rawWidth) ?? {};
      return {
        width: num(w.width) ?? 0,
        contentWidthRatio:
          num(pick(w, "contentWidthRatio", "content_width_ratio")) ?? 0,
        horizontalOverflow:
          pick(w, "horizontalOverflow", "horizontal_overflow") === true,
      };
    }),
  };
}

export function normalizeVisualQa(raw: unknown): VisualQaData | null {
  const obj = asObject(raw);
  if (!obj) return null;
  const commitHash = strOrNull(pick(obj, "commitHash", "commit_hash"));
  if (!commitHash) return null;
  const options = Array.isArray(obj.options) ? obj.options : [];
  return {
    commitHash,
    options: options.map((rawOption, position) => {
      const o = asObject(rawOption) ?? {};
      return {
        index: num(o.index) ?? position,
        screenshot: strOrNull(o.screenshot),
        renderOk: pick(o, "renderOk", "render_ok") !== false,
        error: strOrNull(o.error),
        duplicateOf: num(pick(o, "duplicateOf", "duplicate_of")),
        similarity: num(o.similarity),
        responsive: normalizeResponsive(o.responsive),
      };
    }),
  };
}

export function formatPercent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

// Checks an option fails; empty for a passing option (no noise).
export function qaIssues(option: VisualQaOption): QaIssue[] {
  const issues: QaIssue[] = [];
  if (option.duplicateOf !== null) {
    const pct =
      option.similarity !== null ? ` (${formatPercent(option.similarity)})` : "";
    issues.push({
      kind: "duplicate",
      label: `≈ Option ${option.duplicateOf + 1}${pct}`,
    });
  }
  if (!option.renderOk) {
    issues.push({ kind: "blank_render", label: "⚠ blank render" });
  }
  if (option.responsive && !option.responsive.pass) {
    issues.push({ kind: "not_responsive", label: "⚠ not responsive" });
  }
  return issues;
}

export function qaAssetUrl(
  path: string | null | undefined,
  base: string = HTTP_BACKEND_URL
): string | null {
  if (!path) return null;
  if (/^(https?:|data:|blob:)/i.test(path)) return path;
  const root = base.replace(/\/+$/, "");
  return `${root}${path.startsWith("/") ? path : `/${path}`}`;
}

export function qaFailures(
  data: VisualQaData | null | undefined,
  base: string = HTTP_BACKEND_URL
): QaFailure[] {
  if (!data) return [];
  const failures: QaFailure[] = [];
  for (const option of data.options) {
    const issues = qaIssues(option);
    if (issues.length === 0) continue;
    failures.push({
      index: option.index,
      screenshotUrl: qaAssetUrl(option.screenshot, base),
      labels: issues.map((issue) => issue.label),
    });
  }
  return failures;
}

// QA for one option of a version, if the backend sent it.
export function qaForOption(
  data: VisualQaData | null | undefined,
  index: number
): VisualQaOption | null {
  return data?.options.find((option) => option.index === index) ?? null;
}
