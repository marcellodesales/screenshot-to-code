import { DEFAULT_BUILD_SYSTEM, withDefaultBuildSystem } from "./settings";
import { Settings } from "../types";

describe("withDefaultBuildSystem", () => {
  it("back-fills pnpm for old settings without buildSystem", () => {
    expect(DEFAULT_BUILD_SYSTEM).toBe("pnpm");
    expect(withDefaultBuildSystem({}).buildSystem).toBe("pnpm");
  });

  it("keeps a stored build system", () => {
    expect(withDefaultBuildSystem({ buildSystem: "bun" }).buildSystem).toBe(
      "bun"
    );
  });

  it("replaces an unknown stored value with pnpm", () => {
    const stored = { buildSystem: "yarn" } as unknown as Partial<Settings>;
    expect(withDefaultBuildSystem(stored).buildSystem).toBe("pnpm");
  });

  it("keeps the other settings untouched", () => {
    const result = withDefaultBuildSystem({ openAiApiKey: "sk-test" });
    expect(result.openAiApiKey).toBe("sk-test");
  });
});
