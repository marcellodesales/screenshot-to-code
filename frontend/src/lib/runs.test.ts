jest.mock("../config", () => ({ HTTP_BACKEND_URL: "http://backend.test" }));

import {
  BuildJob,
  buildStartBody,
  enabledBuildSystems,
  getBuild,
  isBuildFinished,
  listStacks,
  RunsApiError,
  saveVersion,
  startBuild,
} from "./runs";

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

const RUN = "run_20261008_101500_ab12cd34";

const backendJob = {
  run_id: RUN,
  ui_commit_hash: "h1",
  build_system: "pnpm",
  template_id: "static-pnpm-html",
  options: [
    {
      index: 0,
      state: "running",
      step_message: "Running",
      url: "http://run-20261008-101500-ab12cd34-op1.localhost:3311/",
      error: null,
    },
    {
      index: 1,
      state: "failed",
      step_message: "Migrating",
      url: null,
      error: "boom",
    },
  ],
};

describe("startBuild", () => {
  it("POSTs the version, build system and keys and returns the job", async () => {
    const calls: FetchCall[] = [];
    const job = await startBuild(
      RUN,
      {
        commitHash: "h1",
        buildSystem: "pnpm",
        openAiApiKey: "sk-o",
        anthropicApiKey: null,
        geminiApiKey: "g",
      },
      fakeFetcher(200, backendJob, calls)
    );

    expect(calls[0].url).toBe(`http://backend.test/api/runs/${RUN}/build`);
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      commitHash: "h1",
      buildSystem: "pnpm",
      openAiApiKey: "sk-o",
      anthropicApiKey: null,
      geminiApiKey: "g",
    });
    expect(job.runId).toBe(RUN);
    expect(job.templateId).toBe("static-pnpm-html");
    expect(job.options[0]).toEqual({
      index: 0,
      state: "running",
      stepMessage: "Running",
      url: "http://run-20261008-101500-ab12cd34-op1.localhost:3311/",
      error: null,
    });
    expect(job.options[1].error).toBe("boom");
  });

  it("surfaces the 403 detail when the stack generator is disabled", async () => {
    const detail =
      "Stack generator disabled (set STACK_GENERATOR_ENABLED=true)";
    const promise = startBuild(
      RUN,
      { commitHash: "h1", buildSystem: "pnpm" },
      fakeFetcher(403, { detail }, [])
    );
    await expect(promise).rejects.toBeInstanceOf(RunsApiError);
    await expect(promise).rejects.toMatchObject({ status: 403, message: detail });
  });
});

describe("getBuild", () => {
  it("GETs the run build job", async () => {
    const calls: FetchCall[] = [];
    const job = await getBuild(RUN, fakeFetcher(200, backendJob, calls));
    expect(calls[0].url).toBe(`http://backend.test/api/runs/${RUN}/build`);
    expect(calls[0].init?.method ?? "GET").toBe("GET");
    expect(job?.options).toHaveLength(2);
  });

  it("returns null when the run has no build", async () => {
    const job = await getBuild(
      RUN,
      fakeFetcher(404, { detail: "No build" }, [])
    );
    expect(job).toBeNull();
  });

  it("accepts camelCase job JSON too", async () => {
    const job = await getBuild(
      RUN,
      fakeFetcher(
        200,
        {
          runId: RUN,
          uiCommitHash: "h1",
          buildSystem: "pnpm",
          templateId: "t",
          options: [{ index: 0, state: "queued", stepMessage: "Queued" }],
        },
        []
      )
    );
    expect(job?.uiCommitHash).toBe("h1");
    expect(job?.options[0]).toEqual({
      index: 0,
      state: "queued",
      stepMessage: "Queued",
      url: null,
      error: null,
    });
  });
});

describe("isBuildFinished", () => {
  const option = (state: BuildJob["options"][number]["state"]) => ({
    index: 0,
    state,
    stepMessage: "",
    url: null,
    error: null,
  });
  const job = (states: BuildJob["options"][number]["state"][]): BuildJob => ({
    runId: RUN,
    uiCommitHash: "h1",
    buildSystem: "pnpm",
    templateId: "t",
    options: states.map(option),
  });

  it("is finished when every option is running or failed", () => {
    expect(isBuildFinished(job(["running", "failed"]))).toBe(true);
  });

  it("is not finished while an option is still in progress", () => {
    expect(isBuildFinished(job(["running", "migrating"]))).toBe(false);
    expect(isBuildFinished(job([]))).toBe(false);
  });
});

describe("stacks catalog", () => {
  const stacks = [
    {
      id: "static-pnpm-html",
      source_stacks: ["html_tailwind", "react_tailwind"],
      build_system: "pnpm",
      phase: 1,
      status: "available",
    },
    {
      id: "nextjs-npm-react-tailwind",
      source_stacks: ["react_tailwind"],
      build_system: "npm",
      phase: 4,
      status: "planned",
    },
    {
      id: "static-bun-html",
      source_stacks: ["vue_tailwind"],
      build_system: "bun",
      phase: 4,
      status: "available",
    },
  ];

  it("listStacks GETs /api/stacks", async () => {
    const calls: FetchCall[] = [];
    const result = await listStacks(fakeFetcher(200, stacks, calls));
    expect(calls[0].url).toBe("http://backend.test/api/stacks");
    expect(result).toHaveLength(3);
  });

  it("enables only build systems with an available entry for the stack", () => {
    expect([...enabledBuildSystems(stacks, "react_tailwind")]).toEqual([
      "pnpm",
    ]);
    expect([...enabledBuildSystems(stacks, "vue_tailwind")]).toEqual(["bun"]);
    expect([...enabledBuildSystems(stacks, "bootstrap")]).toEqual([]);
  });
});

describe("buildStartBody", () => {
  it("sends the version, build system and only the keys that are set", () => {
    expect(
      buildStartBody("h1", {
        buildSystem: "bun",
        openAiApiKey: "sk-o",
        anthropicApiKey: "",
        geminiApiKey: null,
      })
    ).toEqual({ commitHash: "h1", buildSystem: "bun", openAiApiKey: "sk-o" });
  });
});
