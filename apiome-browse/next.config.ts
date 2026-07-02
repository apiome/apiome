import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
