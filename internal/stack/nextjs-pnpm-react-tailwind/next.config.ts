import type { NextConfig } from "next";

// Overlay for create-next-app@16.4.0 (template nextjs-pnpm-react-tailwind).
// Keeps the scaffold's build setup and adds what the container image needs.
const nextConfig: NextConfig = {
  // Emit .next/standalone (server.js + traced node_modules) for the Dockerfile
  // runner stage: no pnpm, no devDependencies in the final image.
  output: "standalone",
  // Served behind Traefik; don't advertise the framework.
  poweredByHeader: false,

  // The scaffold enables `cacheComponents` (+ `partialPrefetching`, which
  // builds on it). With it, `next build` aborts prerendering when a Client
  // Component reads a non-deterministic value during render (`new Date()`,
  // `Date.now()`, `Math.random()`), e.g. a footer's
  // `{new Date().getFullYear()}` -- common in generated mocks. Generated apps
  // are static marketing pages, so we use classic static prerendering instead.
  cacheComponents: false,

  // --- scaffold defaults (create-next-app@16.4.0) ---
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
