#!/usr/bin/env node
/**
 * Push the `cli-v<version>` tag for the version in `apiome-cli/package.json`, unless it exists.
 *
 * No workflow runs this: releases are published on GitHub, which creates the tag. Run it by hand
 * on `main`, after the `Release: apiome-cli vX.Y.Z` pull request merged, to create the tag from a
 * terminal instead. Running it again is harmless: an existing tag is left alone.
 *
 * Usage: node scripts/release/tag-release.mjs [--dry-run]
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { releaseTag } from "./lib.mjs";

const cliRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const dryRun = process.argv.includes("--dry-run");

const { version } = JSON.parse(readFileSync(join(cliRoot, "package.json"), "utf8"));
const tag = releaseTag(version);

const git = (...args) => execFileSync("git", args, { encoding: "utf8" }).trim();

if (git("ls-remote", "--tags", "origin", `refs/tags/${tag}`)) {
  console.log(`${tag} already exists; nothing to tag.`);
} else if (dryRun) {
  console.log(`Would create and push ${tag}.`);
} else {
  git("tag", "-a", tag, "-m", `apiome-cli v${version}`);
  git("push", "origin", `refs/tags/${tag}`);
  console.log(`Pushed ${tag}.`);
}
