#!/usr/bin/env node
/**
 * Pull request check: a change under `apiome-cli/` must carry a changeset that releases
 * `@apiome/cli`, unless the pull request is labelled `no-cli-release` or is the changesets
 * release pull request itself. Run from the repository root by `apiome-cli-changeset.yml`.
 *
 * Usage: node apiome-cli/scripts/release/check-changeset.mjs --base <sha> [--head <ref>]
 * Environment:
 *   PR_LABELS    JSON array of label names (default `[]`)
 *   PR_HEAD_REF  Pull request head branch (default empty)
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { parseArgs } from "node:util";

import { checkChangeset } from "./lib.mjs";

const { values } = parseArgs({
  options: { base: { type: "string" }, head: { type: "string", default: "HEAD" } },
});
if (!values.base) {
  console.error("Usage: check-changeset.mjs --base <sha> [--head <ref>]");
  process.exit(2);
}

// `--name-status` keeps the status so a deleted changeset does not count; a rename lists the
// new path last.
const files = execFileSync("git", ["diff", "--name-status", values.base, values.head], {
  encoding: "utf8",
})
  .split("\n")
  .filter(Boolean)
  .map((line) => {
    const parts = line.split("\t");
    return { status: parts[0], path: parts[parts.length - 1] };
  });

const verdict = checkChangeset({
  files,
  labels: JSON.parse(process.env.PR_LABELS || "[]"),
  headRef: process.env.PR_HEAD_REF || "",
  readFile: (path) => readFileSync(path, "utf8"),
});

if (verdict.ok) {
  console.log(verdict.reason);
} else {
  console.error(`::error title=Missing changeset::${verdict.reason}`);
  process.exit(1);
}
