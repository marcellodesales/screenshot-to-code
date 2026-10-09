jest.mock("../config", () => ({ HTTP_BACKEND_URL: "http://backend.test/" }));

import {
  normalizeResponsive,
  normalizeVisualQa,
  qaAssetUrl,
  qaFailures,
  qaIssues,
  VisualQaOption,
} from "./visualQa";

const SHOT = (n: number) => `/api/runs/run_1/qa/abc/op${n}-1280.png`;

const wsPayload = {
  commitHash: "abc",
  options: [
    {
      index: 0,
      screenshot: SHOT(0),
      renderOk: true,
      error: null,
      duplicateOf: null,
      similarity: null,
      responsive: {
        pass: true,
        widths: [
          { width: 375, contentWidthRatio: 1, horizontalOverflow: false },
          { width: 1920, contentWidthRatio: 0.97, horizontalOverflow: false },
        ],
      },
    },
    {
      index: 1,
      screenshot: SHOT(1),
      renderOk: true,
      error: null,
      duplicateOf: 0,
      similarity: 0.9712,
      responsive: {
        pass: false,
        widths: [
          { width: 1920, contentWidthRatio: 0.21, horizontalOverflow: false },
        ],
      },
    },
    {
      index: 2,
      screenshot: SHOT(2),
      renderOk: false,
      error: "ReferenceError: x is not defined",
      duplicateOf: null,
      similarity: null,
      responsive: null,
    },
  ],
};

function option(overrides: Partial<VisualQaOption> = {}): VisualQaOption {
  return {
    index: 0,
    screenshot: SHOT(0),
    renderOk: true,
    error: null,
    duplicateOf: null,
    similarity: null,
    responsive: { pass: true, widths: [] },
    ...overrides,
  };
}

describe("normalizeVisualQa", () => {
  it("parses the visualQa WS payload", () => {
    const data = normalizeVisualQa(wsPayload);
    expect(data?.commitHash).toBe("abc");
    expect(data?.options).toHaveLength(3);
    expect(data?.options[1]).toEqual({
      index: 1,
      screenshot: SHOT(1),
      renderOk: true,
      error: null,
      duplicateOf: 0,
      similarity: 0.9712,
      responsive: {
        pass: false,
        widths: [
          { width: 1920, contentWidthRatio: 0.21, horizontalOverflow: false },
        ],
      },
    });
    expect(data?.options[2].responsive).toBeNull();
    expect(data?.options[2].error).toBe("ReferenceError: x is not defined");
  });

  it("accepts snake_case too", () => {
    const data = normalizeVisualQa({
      commit_hash: "abc",
      options: [
        {
          index: 0,
          screenshot: SHOT(0),
          render_ok: false,
          duplicate_of: 3,
          similarity: 0.99,
          responsive: {
            pass: true,
            widths: [
              { width: 375, content_width_ratio: 0.9, horizontal_overflow: true },
            ],
          },
        },
      ],
    });
    expect(data?.options[0]).toMatchObject({
      renderOk: false,
      duplicateOf: 3,
      responsive: {
        pass: true,
        widths: [{ width: 375, contentWidthRatio: 0.9, horizontalOverflow: true }],
      },
    });
  });

  it("uses the position when an option has no index and defaults renderOk to true", () => {
    const data = normalizeVisualQa({ commitHash: "h", options: [{}, {}] });
    expect(data?.options.map((o) => o.index)).toEqual([0, 1]);
    expect(data?.options[0]).toEqual({
      index: 0,
      screenshot: null,
      renderOk: true,
      error: null,
      duplicateOf: null,
      similarity: null,
      responsive: null,
    });
  });

  it("returns null without a commit hash or for garbage", () => {
    expect(normalizeVisualQa({ options: [] })).toBeNull();
    expect(normalizeVisualQa(null)).toBeNull();
    expect(normalizeVisualQa("nope")).toBeNull();
  });
});

describe("normalizeResponsive", () => {
  it("returns null for missing / non-object values", () => {
    expect(normalizeResponsive(undefined)).toBeNull();
    expect(normalizeResponsive(null)).toBeNull();
    expect(normalizeResponsive(3)).toBeNull();
  });
});

describe("qaIssues", () => {
  it("is empty for a passing option", () => {
    expect(qaIssues(option())).toEqual([]);
  });

  it("labels a duplicate with the original option and similarity %", () => {
    expect(qaIssues(option({ index: 1, duplicateOf: 0, similarity: 0.9712 }))).toEqual([
      { kind: "duplicate", label: "≈ Option 1 (97%)" },
    ]);
  });

  it("omits the percentage when the similarity is unknown", () => {
    expect(qaIssues(option({ index: 2, duplicateOf: 1, similarity: null }))).toEqual([
      { kind: "duplicate", label: "≈ Option 2" },
    ]);
  });

  it("labels non-responsive and blank renders", () => {
    expect(
      qaIssues(
        option({
          renderOk: false,
          responsive: { pass: false, widths: [] },
        })
      )
    ).toEqual([
      { kind: "blank_render", label: "⚠ blank render" },
      { kind: "not_responsive", label: "⚠ not responsive" },
    ]);
  });

  it("does not flag an option whose responsive check did not run", () => {
    expect(qaIssues(option({ responsive: null }))).toEqual([]);
  });
});

describe("qaFailures", () => {
  it("lists only failing options with their screenshot URL and labels", () => {
    const data = normalizeVisualQa(wsPayload)!;
    expect(qaFailures(data, "http://backend.test")).toEqual([
      {
        index: 1,
        screenshotUrl: `http://backend.test${SHOT(1)}`,
        labels: ["≈ Option 1 (97%)", "⚠ not responsive"],
      },
      {
        index: 2,
        screenshotUrl: `http://backend.test${SHOT(2)}`,
        labels: ["⚠ blank render"],
      },
    ]);
  });

  it("is empty when there is no QA data", () => {
    expect(qaFailures(undefined)).toEqual([]);
  });
});

describe("qaAssetUrl", () => {
  it("prefixes backend-relative paths with HTTP_BACKEND_URL", () => {
    expect(qaAssetUrl(SHOT(0))).toBe(`http://backend.test${SHOT(0)}`);
    expect(qaAssetUrl("api/x.png", "http://b/")).toBe("http://b/api/x.png");
  });

  it("keeps absolute and data URLs, and maps empty to null", () => {
    expect(qaAssetUrl("https://cdn/x.png")).toBe("https://cdn/x.png");
    expect(qaAssetUrl("data:image/png;base64,AA")).toBe(
      "data:image/png;base64,AA"
    );
    expect(qaAssetUrl(null)).toBeNull();
    expect(qaAssetUrl("")).toBeNull();
  });
});
