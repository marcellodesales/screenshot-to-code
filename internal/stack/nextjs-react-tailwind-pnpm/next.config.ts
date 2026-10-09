import type { NextConfig } from "next";

// Overlay for create-next-app@16.4.0 (template nextjs-react-tailwind-pnpm).
// Keeps the scaffold's defaults and adds what the container image needs.
const nextConfig: NextConfig = {
  // Emit .next/standalone (server.js + traced node_modules) for the Dockerfile
  // runner stage: no pnpm, no devDependencies in the final image.
  output: "standalone",
  // Served behind Traefik; don't advertise the framework.
  poweredByHeader: false,

  // --- scaffold defaults (create-next-app@16.4.0) ---
  cacheComponents: true,
  partialPrefetching: true,
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
