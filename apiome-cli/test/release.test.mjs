import assert from "node:assert";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  changesetReleasesCli,
  checkChangeset,
  isChangesetFile,
  nextVersion,
  releaseTag,
  releaseTitle,
  semverToPep440,
  setPyprojectVersion,
  setUvLockVersion,
} from "../scripts/release/lib.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = join(root, "..");

const CLI_CHANGESET = '---\n"@apiome/cli": patch\n---\n\nFix the thing.\n';

/** A pull request that changes one CLI source file plus the given extra files. */
const pr = (extra = [], overrides = {}) => ({
  files: [{ status: "M", path: "apiome-cli/src/apiome_cli/main.py" }, ...extra],
  labels: [],
  headRef: "ticket-1",
  readFile: () => CLI_CHANGESET,
  ...overrides,
});

test("semverToPep440 passes stable versions through", () => {
  assert.strictEqual(semverToPep440("0.142.0"), "0.142.0");
});

test("semverToPep440 maps changesets prerelease tags to PEP 440", () => {
  assert.strictEqual(semverToPep440("1.0.0-rc.0"), "1.0.0rc0");
  assert.strictEqual(semverToPep440("1.0.0-rc.12"), "1.0.0rc12");
  assert.strictEqual(semverToPep440("1.0.0-beta.2"), "1.0.0b2");
  assert.strictEqual(semverToPep440("1.0.0-alpha.1"), "1.0.0a1");
});

test("semverToPep440 rejects versions Python cannot spell", () => {
  assert.throws(() => semverToPep440("1.0"), /Not a semver version/);
  assert.throws(() => semverToPep440("1.0.0-next.0"), /no PEP 440 form/);
  assert.throws(() => semverToPep440("1.0.0-rc"), /no PEP 440 form/);
});

test("setPyprojectVersion changes only the [project] version", () => {
  const text = [
    "[project]",
    'name = "apiome-cli"',
    'version = "0.141.0"',
    "",
    "[tool.other]",
    'version = "9.9.9"',
    "",
  ].join("\n");
  const updated = setPyprojectVersion(text, "0.142.0");
  assert.match(updated, /\[project\]\nname = "apiome-cli"\nversion = "0\.142\.0"/);
  assert.match(updated, /\[tool\.other\]\nversion = "9\.9\.9"/);
});

test("setPyprojectVersion fails loudly without a [project] version", () => {
  assert.throws(() => setPyprojectVersion('[tool]\nversion = "1"\n', "1.0.0"), /no \[project\]/);
  assert.throws(
    () => setPyprojectVersion('[project]\nname = "x"\n[tool]\nversion = "1"\n', "1.0.0"),
    /no version line/,
  );
});

test("setUvLockVersion changes only the apiome-cli entry", () => {
  const text = [
    "[[package]]",
    'name = "anyio"',
    'version = "4.0.0"',
    "",
    "[[package]]",
    'name = "apiome-cli"',
    'version = "0.141.0"',
    'source = { editable = "." }',
    "",
  ].join("\n");
  const updated = setUvLockVersion(text, "0.142.0rc0");
  assert.match(updated, /name = "anyio"\nversion = "4\.0\.0"/);
  assert.match(updated, /name = "apiome-cli"\nversion = "0\.142\.0rc0"/);
  assert.throws(() => setUvLockVersion('[[package]]\nname = "anyio"\n', "1.0.0"), /no apiome-cli/);
});

test("release tag and pull request title carry the version", () => {
  assert.strictEqual(releaseTag("0.142.0"), "cli-v0.142.0");
  assert.strictEqual(releaseTag("1.0.0-rc.1"), "cli-v1.0.0-rc.1");
  assert.throws(() => releaseTag("v1.0.0"), /Not a semver version/);
  assert.strictEqual(releaseTitle("0.142.0"), "Release: apiome-cli v0.142.0");
});

test("nextVersion reads @apiome/cli from changeset status output", () => {
  const status = {
    releases: [
      { name: "other", newVersion: "9.0.0" },
      { name: "@apiome/cli", newVersion: "0.142.0" },
    ],
  };
  assert.strictEqual(nextVersion(status), "0.142.0");
  assert.strictEqual(nextVersion({ releases: [] }), null);
  assert.strictEqual(nextVersion({}), null);
});

test("changesetReleasesCli accepts only a bump of @apiome/cli", () => {
  assert.ok(changesetReleasesCli(CLI_CHANGESET));
  assert.ok(changesetReleasesCli("---\n'@apiome/cli': major\n---\nBreaking.\n"));
  assert.ok(changesetReleasesCli('---\r\n"@apiome/cli": minor\r\n---\r\n'));
  assert.ok(!changesetReleasesCli("---\n---\n\nEmpty changeset.\n"));
  assert.ok(!changesetReleasesCli('---\n"apiome-ui": minor\n---\n'));
  assert.ok(!changesetReleasesCli('"@apiome/cli": minor\n'));
  assert.ok(!changesetReleasesCli("---\nnote: \"@apiome/cli\": minor is mentioned\n---\n"));
});

test("isChangesetFile skips the README, config and pre-mode files", () => {
  assert.ok(isChangesetFile(".changeset/brave-lions-dance.md"));
  assert.ok(!isChangesetFile(".changeset/README.md"));
  assert.ok(!isChangesetFile(".changeset/config.json"));
  assert.ok(!isChangesetFile(".changeset/pre/brave-lions-dance.md"));
  assert.ok(!isChangesetFile("apiome-cli/.changeset/x.md"));
});

test("checkChangeset passes a pull request that does not touch apiome-cli/", () => {
  const verdict = checkChangeset(
    pr([], { files: [{ status: "M", path: "apiome-ui/src/page.tsx" }] }),
  );
  assert.deepStrictEqual(verdict.ok, true);
  assert.match(verdict.reason, /No apiome-cli/);
});

test("checkChangeset fails a CLI change without a changeset", () => {
  const verdict = checkChangeset(pr());
  assert.strictEqual(verdict.ok, false);
  assert.match(verdict.reason, /npx changeset/);
  assert.match(verdict.reason, /no-cli-release/);
});

test("checkChangeset passes a CLI change with a @apiome/cli changeset", () => {
  const verdict = checkChangeset(pr([{ status: "A", path: ".changeset/brave-lions-dance.md" }]));
  assert.strictEqual(verdict.ok, true);
  assert.match(verdict.reason, /brave-lions-dance/);
});

test("checkChangeset ignores deleted, empty and other-package changesets", () => {
  const deleted = checkChangeset(pr([{ status: "D", path: ".changeset/old.md" }]));
  assert.strictEqual(deleted.ok, false);
  const empty = checkChangeset(
    pr([{ status: "A", path: ".changeset/empty.md" }], { readFile: () => "---\n---\n" }),
  );
  assert.strictEqual(empty.ok, false);
  const readme = checkChangeset(pr([{ status: "M", path: ".changeset/README.md" }]));
  assert.strictEqual(readme.ok, false);
});

test("checkChangeset honours the no-cli-release label", () => {
  const verdict = checkChangeset(pr([], { labels: ["docs", "no-cli-release"] }));
  assert.strictEqual(verdict.ok, true);
  assert.match(verdict.reason, /no-cli-release/);
});

test("checkChangeset passes the changesets release pull request", () => {
  const verdict = checkChangeset(
    pr([{ status: "D", path: ".changeset/brave-lions-dance.md" }], {
      headRef: "changeset-release/main",
    }),
  );
  assert.strictEqual(verdict.ok, true);
});

test("changesets config releases only @apiome/cli", () => {
  const config = JSON.parse(readFileSync(join(repoRoot, ".changeset", "config.json"), "utf8"));
  assert.strictEqual(config.baseBranch, "main");
  assert.strictEqual(config.privatePackages.version, true);
  const rootPkg = JSON.parse(readFileSync(join(repoRoot, "package.json"), "utf8"));
  const names = rootPkg.workspaces
    .map((dir) => JSON.parse(readFileSync(join(repoRoot, dir, "package.json"), "utf8")).name)
    .filter((name) => name !== "@apiome/cli");
  assert.deepStrictEqual([...config.ignore].sort(), names.sort());
});

test("package.json exposes the release scripts and pins @changesets/cli", () => {
  const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  for (const name of ["changeset", "release:version", "release:sync-version", "release:tag"]) {
    assert.ok(pkg.scripts[name], `expected scripts.${name} to be defined`);
  }
  assert.match(pkg.devDependencies["@changesets/cli"], /^\d+\.\d+\.\d+$/);
  assert.ok(existsSync(join(root, "CHANGELOG.md")), "expected apiome-cli/CHANGELOG.md");
});

test("package.json, pyproject.toml and uv.lock agree on the version", () => {
  const result = spawnSync(process.execPath, ["scripts/release/sync-version.mjs", "--check"], {
    cwd: root,
    encoding: "utf8",
  });
  assert.strictEqual(result.status, 0, result.stderr);
});

test("release workflows exist", () => {
  for (const file of ["apiome-cli-release-pr.yml", "apiome-cli-changeset.yml"]) {
    assert.ok(existsSync(join(repoRoot, ".github", "workflows", file)), `expected ${file}`);
  }
});
