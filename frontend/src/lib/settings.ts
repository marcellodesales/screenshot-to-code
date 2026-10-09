import { BuildSystem, Settings } from "../types";

export const BUILD_SYSTEMS: BuildSystem[] = ["pnpm", "npm", "bun"];
export const DEFAULT_BUILD_SYSTEM: BuildSystem = "pnpm";

export function isBuildSystem(value: unknown): value is BuildSystem {
  return (
    typeof value === "string" &&
    (BUILD_SYSTEMS as readonly string[]).includes(value)
  );
}

// Settings persisted before `buildSystem` existed (or with an unknown value)
// get the default.
export function withDefaultBuildSystem(s: Partial<Settings>): Settings {
  return {
    ...s,
    buildSystem: isBuildSystem(s.buildSystem)
      ? s.buildSystem
      : DEFAULT_BUILD_SYSTEM,
  } as Settings;
}
