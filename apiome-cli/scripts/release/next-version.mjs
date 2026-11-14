#!/usr/bin/env node
/**
 * Print the version the pending changesets bump `@apiome/cli` to, read from a
 * `changeset status --output <file>` JSON file. Prints nothing when no changeset is pending.
 *
 * Usage: node scripts/release/next-version.mjs <status.json>
 */
import { readFileSync } from "node:fs";

import { nextVersion } from "./lib.mjs";

const file = process.argv[2];
if (!file) {
  console.error("Usage: next-version.mjs <status.json>");
  process.exit(2);
}
console.log(nextVersion(JSON.parse(readFileSync(file, "utf8"))) ?? "");
