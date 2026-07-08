import type { NextConfig } from "next";
import path from "node:path";

// Yarn workspaces hoist dependencies to the repo root; Turbopack must use the
// same root (not infer it from stray package-lock.json files in the monorepo).
const monorepoRoot = path.resolve(process.cwd(), "..");
const isCommercial = process.env.APIOME_BUILD_PROFILE === "commercial";

const suiteHostAbsolute = isCommercial
  ? path.resolve(monorepoRoot, "private-suite/suite/host/src/index.ts")
  : path.resolve(__dirname, "lib/suite-stub/index.ts");

/** Turbopack resolveAlias must be project-relative, not absolute. */
const suiteHostTurbopackAlias = isCommercial
  ? "../private-suite/suite/host/src/index.ts"
  : "./lib/suite-stub/index.ts";

const suiteTranspilePackages = isCommercial ? ["@suite/host"] : [];

const nextConfig: NextConfig = {
  reactCompiler: true,
  // Enable standalone output for Docker
  output: "standalone",
  outputFileTracingRoot: monorepoRoot,
  transpilePackages: suiteTranspilePackages,
  turbopack: {
    root: monorepoRoot,
    resolveAlias: {
      "@suite/host": suiteHostTurbopackAlias,
    },
  },
  // Bound build-time parallelism. The static-generation worker pool defaults to
  // (CPU count - 1) workers — 19 on a 20-core box — and each worker loads the app,
  // so peak memory spikes hard. On the shared self-hosted CI runner that starves
  // the agent and it "loses communication" mid-build. Cap the pool and let Next
  // shrink it further when free memory is low.
  experimental: {
    cpus: 4,
    memoryBasedWorkersCount: true,
  },
  webpack(config) {
    config.resolve.alias = {
      ...config.resolve.alias,
      "@suite/host": suiteHostAbsolute,
    };
    return config;
  },
};

export default nextConfig;
