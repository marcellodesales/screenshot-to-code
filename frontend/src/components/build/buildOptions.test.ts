import { Commit } from "../commits/types";
import { buildOptionsFor } from "./buildOptions";

function aiCommit(hash: string, optionCount: number, selected: number): Commit {
  return {
    hash,
    parentHash: null,
    dateCreated: new Date(0),
    isCommitted: true,
    type: "ai_create",
    inputs: { text: "", images: [] },
    selectedVariantIndex: selected,
    variants: Array.from({ length: optionCount }, () => ({
      code: "<html/>",
      history: [],
    })),
  };
}

function manualEdit(hash: string, parentHash: string, optionIndex: number): Commit {
  return {
    hash,
    parentHash,
    dateCreated: new Date(0),
    isCommitted: false,
    type: "code_edit",
    inputs: null,
    optionIndex,
    selectedVariantIndex: 0,
    variants: [{ code: "<b/>", history: [] }],
  };
}

describe("buildOptionsFor", () => {
  it("uses the version's options and selected option", () => {
    const qa = { commitHash: "v1", options: [] };
    const commits = { v1: { ...aiCommit("v1", 4, 2), visualQa: qa } };
    expect(buildOptionsFor(commits, "v1")).toEqual({
      optionCount: 4,
      selectedIndex: 2,
      visualQa: qa,
    });
  });

  it("a manual edit carries its AI ancestor's options and selects the edited one", () => {
    const commits = {
      v1: aiCommit("v1", 2, 0),
      e1: manualEdit("e1", "v1", 1),
      e2: manualEdit("e2", "e1", 1),
    };
    expect(buildOptionsFor(commits, "e2")).toEqual({
      optionCount: 2,
      selectedIndex: 1,
      visualQa: undefined,
    });
  });

  it("covers the edited option even if the ancestor had fewer options", () => {
    const commits = { v1: aiCommit("v1", 1, 0), e1: manualEdit("e1", "v1", 2) };
    expect(buildOptionsFor(commits, "e1").optionCount).toBe(3);
  });

  it("falls back to a single option for unknown versions", () => {
    expect(buildOptionsFor({}, "missing")).toEqual({
      optionCount: 1,
      selectedIndex: 0,
      visualQa: undefined,
    });
  });
});
