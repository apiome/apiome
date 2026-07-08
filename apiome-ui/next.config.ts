import type { NextConfig } from "next";
import path from "node:path";

// Yarn workspaces hoist dependencies to the repo root; Turbopack must use the
// same root (not infer it from stray package-lock.json files in the monorepo).
const monorepoRoot = path.resolve(process.cwd(), "..");
const isCommercial = process.env.APIOME_BUILD_PROFILE === "commercial";

const suiteHostAbsolute = isCommercial
  ? path.resolve(monorepoRoot, "private-suite/suite/host/src/index.ts")
  : path.resolve(__dirname, "lib/suite-stub/index.ts");

const suiteDesignerAbsolute = path.resolve(
  monorepoRoot,
  "private-suite/suite/designer/src"
);

const suiteDesignerRoutesAbsolute = isCommercial
  ? path.resolve(monorepoRoot, "private-suite/suite/designer/src/routes/index.ts")
  : path.resolve(__dirname, "lib/suite-designer-stub/routes.ts");

/** Turbopack resolveAlias must be project-relative, not absolute. */
const suiteHostTurbopackAlias = isCommercial
  ? "../private-suite/suite/host/src/index.ts"
  : "./lib/suite-stub/index.ts";

const suiteDesignerTurbopackAlias = "../private-suite/suite/designer/src";

const suiteDesignerRoutesTurbopackAlias = isCommercial
  ? "../private-suite/suite/designer/src/routes/index.ts"
  : "./lib/suite-designer-stub/routes.ts";

const suiteTranspilePackages = isCommercial ? ["@suite/host", "@suite/designer"] : [];

const hostResolveAliases = {
  "@": path.resolve(__dirname, "src"),
  "@lib": path.resolve(__dirname, "lib"),
  "@apiome/suite-contract": path.resolve(__dirname, "lib/suite-contract.ts"),
  "@suite/host": suiteHostAbsolute,
  "@suite/designer/routes": suiteDesignerRoutesAbsolute,
  ...(isCommercial
    ? {
        "@suite/designer": suiteDesignerAbsolute,
        "@suite/designer/": `${suiteDesignerAbsolute}/`,
      }
    : {}),
};

const hostTurbopackAliases: Record<string, string> = {
  "@suite/host": suiteHostTurbopackAlias,
  "@suite/designer/routes": suiteDesignerRoutesTurbopackAlias,
  ...(isCommercial
    ? {
        "@suite/designer": suiteDesignerTurbopackAlias,
        "@suite/designer/": `${suiteDesignerTurbopackAlias}/`,
      }
    : {}),
};

const nextConfig: NextConfig = {
  reactCompiler: true,
  // Enable standalone output for Docker
  output: "standalone",
  outputFileTracingRoot: monorepoRoot,
  transpilePackages: suiteTranspilePackages,
  turbopack: {
    root: monorepoRoot,
    resolveAlias: hostTurbopackAliases,
  },
  experimental: {
    cpus: 4,
    memoryBasedWorkersCount: true,
  },
  webpack(config) {
    config.resolve.alias = {
      ...config.resolve.alias,
      ...hostResolveAliases,
    };
    return config;
  },
};

export default nextConfig;
