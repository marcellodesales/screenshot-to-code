import { Commit, VariantStatus } from "../components/commits/types";
import { useAppStore } from "./app-store";
import { useProjectStore } from "./project-store";

function createGeneratingCommit(): Commit {
  return {
    hash: "timed-commit",
    parentHash: null,
    dateCreated: new Date(1_000),
    isCommitted: false,
    variants: [{ code: "", history: [] }],
    selectedVariantIndex: 0,
    type: "ai_create",
    inputs: { text: "Create a page", images: [] },
  };
}

describe("version navigation", () => {
  const selectedElement = { tagName: "BUTTON" } as HTMLElement;

  beforeEach(() => {
    useProjectStore.setState({ head: "latest" });
    useAppStore.setState({
      inSelectAndEditMode: true,
      selectedElement,
    });
  });

  afterEach(() => {
    useAppStore.setState({
      inSelectAndEditMode: false,
      selectedElement: null,
    });
  });

  it("exits select-and-edit and clears its target when the head changes", () => {
    useProjectStore.getState().setHead("previous");

    expect(useProjectStore.getState().head).toBe("previous");
    expect(useAppStore.getState().inSelectAndEditMode).toBe(false);
    expect(useAppStore.getState().selectedElement).toBeNull();
  });

  it("does not exit select-and-edit when the requested head is already active", () => {
    useProjectStore.getState().setHead("latest");

    expect(useAppStore.getState().inSelectAndEditMode).toBe(true);
    expect(useAppStore.getState().selectedElement).toBe(selectedElement);
  });
});

describe("variant completion timestamps", () => {
  beforeEach(() => {
    useProjectStore.setState({
      commits: {},
      head: null,
      latestCommitHash: null,
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test.each<VariantStatus>(["complete", "error", "cancelled"])(
    "records one stable timestamp when a variant becomes %s",
    (status) => {
      const now = jest.spyOn(Date, "now").mockReturnValue(116_000);
      const store = useProjectStore.getState();
      store.addCommit(createGeneratingCommit());
      store.updateVariantStatus("timed-commit", 0, status);

      expect(
        useProjectStore.getState().commits["timed-commit"].variants[0]
          .completedAt
      ).toBe(116_000);

      now.mockReturnValue(999_000);
      store.updateVariantStatus("timed-commit", 0, status);

      expect(
        useProjectStore.getState().commits["timed-commit"].variants[0]
          .completedAt
      ).toBe(116_000);
    }
  );
});

describe("run linkage", () => {
  beforeEach(() => {
    useProjectStore.setState({
      commits: {},
      head: null,
      latestCommitHash: null,
      runId: null,
    });
  });

  it("stores the run id sent by the backend", () => {
    useProjectStore.getState().setRunId("run_20261008_101500_ab12cd34");

    expect(useProjectStore.getState().runId).toBe(
      "run_20261008_101500_ab12cd34"
    );
  });

  it("setCommitGitSha sets gitSha on a committed commit", () => {
    const store = useProjectStore.getState();
    store.addCommit({ ...createGeneratingCommit(), hash: "v1" });
    // Adding a second commit marks v1 as committed.
    store.addCommit({ ...createGeneratingCommit(), hash: "v2" });
    expect(useProjectStore.getState().commits["v1"].isCommitted).toBe(true);

    store.setCommitGitSha("v1", "a".repeat(40));

    expect(useProjectStore.getState().commits["v1"].gitSha).toBe(
      "a".repeat(40)
    );
  });

  it("setCommitGitSha ignores unknown commits", () => {
    useProjectStore.getState().setCommitGitSha("missing", "b".repeat(40));

    expect(useProjectStore.getState().commits["missing"]).toBeUndefined();
  });

  it("reset (resetCommits) clears runId", () => {
    const store = useProjectStore.getState();
    store.setRunId("run_20261008_101500_ab12cd34");
    store.addCommit(createGeneratingCommit());

    store.resetCommits();

    expect(useProjectStore.getState().runId).toBeNull();
    expect(useProjectStore.getState().commits).toEqual({});
  });
});

describe("manual edits", () => {
  function committedVersion(hash: string, codes: string[], selected = 0): Commit {
    return {
      hash,
      parentHash: null,
      dateCreated: new Date(1_000),
      isCommitted: false,
      variants: codes.map((code) => ({ code, history: [] })),
      selectedVariantIndex: selected,
      type: "ai_create",
      inputs: { text: "Create a page", images: [] },
    };
  }

  beforeEach(() => {
    useProjectStore.setState({
      commits: {},
      head: null,
      latestCommitHash: null,
      runId: null,
    });
  });

  it("applyManualEdit creates code_edit once then updates it", () => {
    const store = useProjectStore.getState();
    store.addCommit(committedVersion("v1", ["<a/>", "<b/>"], 1));
    store.setHead("v1");

    const first = useProjectStore.getState().applyManualEdit("<b>1</b>");
    const afterFirst = useProjectStore.getState();
    expect(first).not.toBeNull();
    expect(first).not.toBe("v1");
    expect(afterFirst.head).toBe(first);
    const created = afterFirst.commits[first!];
    expect(created.type).toBe("code_edit");
    expect(created.parentHash).toBe("v1");
    expect(created.inputs).toBeNull();
    expect(created.variants).toHaveLength(1);
    expect(created.variants[0].code).toBe("<b>1</b>");
    expect(created.variants[0].status).toBe("complete");
    // The edited option of the parent version (used for backend saves).
    expect(created.type === "code_edit" && created.optionIndex).toBe(1);
    // The parent version is untouched.
    expect(afterFirst.commits["v1"].variants[1].code).toBe("<b/>");

    const second = useProjectStore.getState().applyManualEdit("<b>2</b>");
    const afterSecond = useProjectStore.getState();
    expect(second).toBe(first);
    expect(Object.keys(afterSecond.commits)).toHaveLength(2);
    expect(afterSecond.commits[first!].variants[0].code).toBe("<b>2</b>");
  });

  it("editing an older version forks a new code_edit from it", () => {
    const store = useProjectStore.getState();
    store.addCommit(committedVersion("v1", ["<a/>"]));
    store.setHead("v1");
    const edit1 = useProjectStore.getState().applyManualEdit("<a>1</a>")!;

    // Go back to v1 (now committed) and edit again: a sibling version.
    useProjectStore.getState().setHead("v1");
    const edit2 = useProjectStore.getState().applyManualEdit("<a>2</a>")!;

    const state = useProjectStore.getState();
    expect(edit2).not.toBe(edit1);
    expect(state.commits[edit2].parentHash).toBe("v1");
    expect(state.commits[edit1].variants[0].code).toBe("<a>1</a>");
    expect(state.commits[edit1].isCommitted).toBe(true);
  });

  it("a code_edit child of a code_edit keeps the original option index", () => {
    const store = useProjectStore.getState();
    store.addCommit(committedVersion("v1", ["<a/>", "<b/>", "<c/>"], 2));
    store.setHead("v1");
    const edit1 = useProjectStore.getState().applyManualEdit("<c>1</c>")!;
    // Committing edit1 (e.g. a later version was added) then editing it.
    store.addCommit({ ...committedVersion("v3", ["<x/>"]), parentHash: edit1 });
    useProjectStore.getState().setHead(edit1);
    const edit2 = useProjectStore.getState().applyManualEdit("<c>2</c>")!;

    const commit = useProjectStore.getState().commits[edit2];
    expect(commit.parentHash).toBe(edit1);
    expect(commit.type === "code_edit" && commit.optionIndex).toBe(2);
  });

  it("applyManualEdit without a head does nothing", () => {
    expect(useProjectStore.getState().applyManualEdit("<a/>")).toBeNull();
    expect(useProjectStore.getState().commits).toEqual({});
  });
});
