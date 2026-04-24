export const DEFAULT_REPOSITORY_SCAN_IGNORE_PATTERNS = [
  ".git/**",
  "node_modules/**",
  "vendor/**",
  "dist/**",
  "build/**",
  "coverage/**",
  "**/__pycache__/**",
] as const;
