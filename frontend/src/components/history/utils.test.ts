import { renderHistory, shortSha } from "./utils";
import { Commit, CommitHash } from "../commits/types";

const basicLinearHistory: Record<CommitHash, Commit> = {
  "0": {
    hash: "0",
    dateCreated: new Date(),
    isCommitted: false,
    type: "ai_create",
    parentHash: null,
    variants: [{ code: "<html>1. create</html>", history: [] }],
    selectedVariantIndex: 0,
    inputs: { text: "", images: [""] },
  },
  "1": {
    hash: "1",
    dateCreated: new Date(),
    isCommitted: false,
    type: "ai_edit",
    parentHash: "0",
    variants: [{ code: "<html>2. edit with better icons</html>", history: [] }],
    selectedVariantIndex: 0,
    inputs: { text: "use better icons", images: [] },
  },
  "2": {
    hash: "2",
    dateCreated: new Date(),
    isCommitted: false,
    type: "ai_edit",
    parentHash: "1",
    variants: [{ code: "<html>3. edit with better icons and red text</html>", history: [] }],
    selectedVariantIndex: 0,
    inputs: { text: "make text red", images: [] },
  },
};

const basicLinearHistoryWithCode: Record<CommitHash, Commit> = {
  "0": {
    hash: "0",
    dateCreated: new Date(),
    isCommitted: false,
    type: "code_create",
    parentHash: null,
    variants: [{ code: "<html>1. create</html>", history: [] }],
    selectedVariantIndex: 0,
    inputs: null,
  },
  ...Object.fromEntries(Object.entries(basicLinearHistory).slice(1)),
};

const basicBranchingHistory: Record<CommitHash, Commit> = {
  ...basicLinearHistory,
  "3": {
    hash: "3",
    dateCreated: new Date(),
    isCommitted: false,
    type: "ai_edit",
    parentHash: "1",
    variants: [
      { code: "<html>4. edit with better icons and green text</html>", history: [] },
    ],
    selectedVariantIndex: 0,
    inputs: { text: "make text green", images: [] },
  },
};

describe("History Utils", () => {
  test("should correctly render the history tree", () => {
    expect(renderHistory(Object.values(basicLinearHistory))).toEqual([
      {
        ...basicLinearHistory["0"],
        type: "Create",
        summary: "Create",
        selectedElementTag: null,
        parentVersion: null,
        images: [""],
        videos: [],
      },
      {
        ...basicLinearHistory["1"],
        type: "Edit",
        summary: "use better icons",
        selectedElementTag: null,
        parentVersion: null,
        images: [],
        videos: [],
      },
      {
        ...basicLinearHistory["2"],
        type: "Edit",
        summary: "make text red",
        selectedElementTag: null,
        parentVersion: null,
        images: [],
        videos: [],
      },
    ]);

    // Render a history with code
    expect(renderHistory(Object.values(basicLinearHistoryWithCode))).toEqual([
      {
        ...basicLinearHistoryWithCode["0"],
        type: "Imported from code",
        summary: "Imported from code",
        selectedElementTag: null,
        parentVersion: null,
        images: [],
        videos: [],
      },
      {
        ...basicLinearHistoryWithCode["1"],
        type: "Edit",
        summary: "use better icons",
        selectedElementTag: null,
        parentVersion: null,
        images: [],
        videos: [],
      },
      {
        ...basicLinearHistoryWithCode["2"],
        type: "Edit",
        summary: "make text red",
        selectedElementTag: null,
        parentVersion: null,
        images: [],
        videos: [],
      },
    ]);

    // Render a non-linear history
    expect(renderHistory(Object.values(basicBranchingHistory))).toEqual([
      {
        ...basicBranchingHistory["0"],
        type: "Create",
        summary: "Create",
        selectedElementTag: null,
        parentVersion: null,
        images: [""],
        videos: [],
      },
      {
        ...basicBranchingHistory["1"],
        type: "Edit",
        summary: "use better icons",
        selectedElementTag: null,
        parentVersion: null,
        images: [],
        videos: [],
      },
      {
        ...basicBranchingHistory["2"],
        type: "Edit",
        summary: "make text red",
        selectedElementTag: null,
        parentVersion: null,
        images: [],
        videos: [],
      },
      {
        ...basicBranchingHistory["3"],
        type: "Edit",
        summary: "make text green",
        selectedElementTag: null,
        parentVersion: 2,
        images: [],
        videos: [],
      },
    ]);
  });
});

describe("shortSha", () => {
  test("returns the first 7 characters of a git SHA", () => {
    expect(shortSha("0123456789abcdef0123456789abcdef01234567")).toBe(
      "0123456"
    );
  });

  test("returns null when there is no SHA yet", () => {
    expect(shortSha(undefined)).toBeNull();
    expect(shortSha("")).toBeNull();
  });
});

describe("renderHistory git SHA", () => {
  test("carries the commit gitSha through to the rendered item", () => {
    const sha = "f".repeat(40);
    const rendered = renderHistory([
      { ...basicLinearHistory["0"], gitSha: sha },
    ]);
    expect(rendered[0].gitSha).toBe(sha);
  });
});

describe("manual edit versions", () => {
  test("labels code_edit versions as Manual edit", () => {
    const rendered = renderHistory([
      basicLinearHistory["0"],
      {
        hash: "m1",
        dateCreated: new Date(),
        isCommitted: false,
        type: "code_edit",
        parentHash: "0",
        variants: [{ code: "<html>edited</html>", history: [] }],
        selectedVariantIndex: 0,
        inputs: null,
        optionIndex: 0,
      },
    ]);
    expect(rendered[1].type).toBe("Manual edit");
    expect(rendered[1].summary).toBe("Manual edit");
    expect(rendered[1].images).toEqual([]);
    expect(rendered[1].selectedElementTag).toBeNull();
  });
});
