/**
 * Repository scanner defaults — REPO-2.2 (#2763).
 *
 * The REST suite proves this list equals the scanner's own; this one pins its shape.
 */

import {
  DEFAULT_REPOSITORY_SCAN_IGNORE_PATTERNS,
  REPOSITORY_SCAN_MANIFEST_PATH,
} from "../lib/repositories/scanner/defaults";

describe("repository scanner defaults", () => {
  it("ignores the usual vendored, build and cache trees at any depth", () => {
    for (const name of [
      ".git",
      "node_modules",
      "vendor",
      "dist",
      "build",
      "coverage",
      "__pycache__",
    ]) {
      expect(DEFAULT_REPOSITORY_SCAN_IGNORE_PATTERNS).toContain(
        `**/${name}/**`,
      );
    }
  });

  it("lists each pattern once", () => {
    expect(new Set(DEFAULT_REPOSITORY_SCAN_IGNORE_PATTERNS).size).toBe(
      DEFAULT_REPOSITORY_SCAN_IGNORE_PATTERNS.length,
    );
  });

  it("names the manifest the scanner reads overrides from", () => {
    expect(REPOSITORY_SCAN_MANIFEST_PATH).toBe(".apiome/repo.yaml");
  });
});
