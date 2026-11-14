#!/usr/bin/env node
/**
 * Copy the version changesets wrote to `apiome-cli/package.json` into `pyproject.toml` and
 * `uv.lock`, so `apiome --version` (read from the installed Python metadata) matches the release.
 *
 * Run by `yarn workspace @apiome/cli release:version` right after `changeset version`.
 *
 * Usage: node scripts/release/sync-version.mjs [--check]
 *   --check  Change nothing; exit 1 when the three files disagree.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { semverToPep440, setPyprojectVersion, setUvLockVersion } from "./lib.mjs";

const cliRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const check = process.argv.includes("--check");

const { version } = JSON.parse(readFileSync(join(cliRoot, "package.json"), "utf8"));
const pep440 = semverToPep440(version);

let stale = false;
for (const [file, update] of [
  ["pyproject.toml", setPyprojectVersion],
  ["uv.lock", setUvLockVersion],
]) {
  const path = join(cliRoot, file);
  const before = readFileSync(path, "utf8");
  const after = update(before, pep440);
  if (before === after) {
    continue;
  }
  stale = true;
  if (check) {
    console.error(`${file} is not at ${pep440} (package.json ${version})`);
  } else {
    writeFileSync(path, after);
    console.log(`${file} → ${pep440}`);
  }
}

if (check && stale) {
  process.exit(1);
}
