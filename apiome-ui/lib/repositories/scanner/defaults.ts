/**
 * Repository scanner defaults — REPO-2.2 (#2763).
 *
 * The paths every repository scan skips before indexing, whatever the repository's own
 * `.apiome/repo.yaml` says. A manifest's `ignore:` patterns are added to these, and its
 * `specs:` entries are indexed even when one of these patterns matches them.
 *
 * The scanner itself runs in apiome-rest (`app/repository_scan_ignore.py`,
 * `DEFAULT_SCAN_IGNORE_PATTERNS`); this copy is what the UI shows, and a REST test keeps the
 * two lists equal.
 *
 * Patterns are repository-relative globs: `*` stays inside one path segment and `**` spans
 * any number of segments, so `**\/node_modules/**` matches `node_modules/x.js` and
 * `web/node_modules/a/b.js` alike.
 */

/** The ignore patterns applied to every repository scan, in the scanner's order. */
export const DEFAULT_REPOSITORY_SCAN_IGNORE_PATTERNS = [
  "**/.git/**",
  "**/node_modules/**",
  "**/vendor/**",
  "**/dist/**",
  "**/build/**",
  "**/coverage/**",
  "**/__pycache__/**",
] as const;

/** One of {@link DEFAULT_REPOSITORY_SCAN_IGNORE_PATTERNS}. */
export type DefaultRepositoryScanIgnorePattern =
  (typeof DEFAULT_REPOSITORY_SCAN_IGNORE_PATTERNS)[number];

/** Where the scanner reads per-repository `ignore:` / `specs:` overrides. */
export const REPOSITORY_SCAN_MANIFEST_PATH = ".apiome/repo.yaml";
