import { HTTP_BACKEND_URL } from "../config";

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

function runUrl(runId: string, suffix: string) {
  return `${HTTP_BACKEND_URL.replace(/\/$/, "")}/api/runs/${encodeURIComponent(
    runId
  )}${suffix}`;
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
