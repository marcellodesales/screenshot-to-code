jest.mock("../config", () => ({ HTTP_BACKEND_URL: "http://backend.test" }));

import { saveVersion } from "./runs";

type FetchCall = { url: string; init?: RequestInit };

function fakeFetcher(status: number, payload: unknown, calls: FetchCall[]) {
  return (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
}

describe("saveVersion", () => {
  it("PUTs the edited option code to the run version", async () => {
    const calls: FetchCall[] = [];
    const sha = "c".repeat(40);
    const result = await saveVersion(
      "run_20261008_101500_ab12cd34",
      "commitHash1",
      { parentCommitHash: "parent1", optionIndex: 1, code: "<html/>" },
      fakeFetcher(200, { gitSha: sha }, calls)
    );

    expect(result).toEqual({ gitSha: sha });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(
      "http://backend.test/api/runs/run_20261008_101500_ab12cd34/versions/commitHash1"
    );
    expect(calls[0].init?.method).toBe("PUT");
    expect(
      (calls[0].init?.headers as Record<string, string>)["Content-Type"]
    ).toBe("application/json");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      parentCommitHash: "parent1",
      optionIndex: 1,
      code: "<html/>",
    });
  });

  it("URL-encodes path segments", async () => {
    const calls: FetchCall[] = [];
    await saveVersion(
      "run/../x",
      "a b",
      { parentCommitHash: null, optionIndex: 0, code: "" },
      fakeFetcher(200, { gitSha: "d".repeat(40) }, calls)
    );
    expect(calls[0].url).toBe(
      "http://backend.test/api/runs/run%2F..%2Fx/versions/a%20b"
    );
  });

  it("throws with the backend detail on error", async () => {
    await expect(
      saveVersion(
        "run_20261008_101500_ab12cd34",
        "h",
        { parentCommitHash: null, optionIndex: 0, code: "x" },
        fakeFetcher(404, { detail: "Unknown run" }, [])
      )
    ).rejects.toThrow("Unknown run");
  });
});
