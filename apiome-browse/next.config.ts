import type { NextConfig } from "next";
import path from "node:path";
import { fileURLToPath } from "node:url";

// lib/tryit re-exports the shared Try-It modules in apiome-ui/lib/tryit (DWX-4.2), which sit outside
// this package. Pin Turbopack's root to the monorepo root so they resolve in a checkout and in the
// Docker image alike (the image has no root lockfile to infer it from), as apiome-ui does.
const packageRoot = path.dirname(fileURLToPath(import.meta.url));
const monorepoRoot = path.resolve(packageRoot, "..");

const nextConfig: NextConfig = {
  outputFileTracingRoot: monorepoRoot,
  turbopack: {
    root: monorepoRoot,
  },

  // Base path for hosting at a sub-path (e.g., /browse)
  // Set NEXT_PUBLIC_BASE_PATH environment variable to configure
  // Example: NEXT_PUBLIC_BASE_PATH=/browse
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",

  // Asset prefix for CDN or sub-path hosting
  assetPrefix: process.env.NEXT_PUBLIC_BASE_PATH || "",

  // Trailing slash configuration
  trailingSlash: false,
};

export default nextConfig;
