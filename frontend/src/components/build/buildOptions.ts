import type { VisualQaData } from "../../lib/visualQa";
import { Commit, CommitHash } from "../commits/types";

export interface BuildOptionsInfo {
  // Number of options the backend version has (option files op1..opN).
  optionCount: number;
  // The option the user is looking at (default build selection).
  selectedIndex: number;
  visualQa: VisualQaData | undefined;
}

// Options of a version as the backend stores them. A manual edit is saved as
// its parent's options with the edited one replaced, so it carries the
// option count of its nearest AI / imported ancestor.
export function buildOptionsFor(
  commits: Record<CommitHash, Commit>,
  hash: CommitHash
): BuildOptionsInfo {
  const commit = commits[hash];
  if (!commit) return { optionCount: 1, selectedIndex: 0, visualQa: undefined };
  if (commit.type !== "code_edit") {
    return {
      optionCount: Math.max(1, commit.variants.length),
      selectedIndex: commit.selectedVariantIndex,
      visualQa: commit.visualQa,
    };
  }

  let ancestor: Commit | undefined = commit;
  const seen = new Set<CommitHash>();
  while (ancestor && ancestor.type === "code_edit" && !seen.has(ancestor.hash)) {
    seen.add(ancestor.hash);
    ancestor = ancestor.parentHash ? commits[ancestor.parentHash] : undefined;
  }
  const ancestorCount =
    ancestor && ancestor.type !== "code_edit" ? ancestor.variants.length : 1;
  return {
    optionCount: Math.max(ancestorCount, commit.optionIndex + 1),
    selectedIndex: commit.optionIndex,
    visualQa: commit.visualQa,
  };
}
