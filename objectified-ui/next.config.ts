import type { NextConfig } from "next";
import path from "node:path";

// Yarn workspaces hoist dependencies to the repo root; Turbopack must use the
// same root (not infer it from stray package-lock.json files in the monorepo).
const monorepoRoot = path.resolve(process.cwd(), "..");

const nextConfig: NextConfig = {
  reactCompiler: true,
  // Enable standalone output for Docker
  output: "standalone",
  outputFileTracingRoot: monorepoRoot,
  turbopack: {
    root: monorepoRoot,
  },
};

export default nextConfig;
