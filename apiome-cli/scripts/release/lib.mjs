/**
 * Pure helpers for the apiome-cli release tooling (#3269).
 *
 * Changesets owns the version in `apiome-cli/package.json`; these helpers carry it to the
 * Python packaging files, name the release tag and pull request, and decide whether a pull
 * request needs a changeset. They do no I/O so `test/release.test.mjs` can cover them directly;
 * the scripts beside this file do the reading, writing and git calls.
 */

/** npm package name changesets versions. */
export const PACKAGE_NAME = "@apiome/cli";

/** Python distribution name in `pyproject.toml` and `uv.lock`. */
export const PYTHON_NAME = "apiome-cli";

/** Label that lets a pull request change `apiome-cli/` without a changeset. */
export const SKIP_LABEL = "no-cli-release";

/** Branch prefix of the changesets bot pull request (it consumes changesets, it adds none). */
export const RELEASE_BRANCH_PREFIX = "changeset-release/";

/** Git tag prefix that triggers the publish workflow (12.2, #3268). */
export const TAG_PREFIX = "cli-v";

const SEMVER = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/;

/** Semver prerelease identifier → PEP 440 pre-release segment. */
const PEP440_PRE = { alpha: "a", a: "a", beta: "b", b: "b", rc: "rc" };

/**
 * Convert a semver version to the PEP 440 form Python packaging uses.
 *
 * Stable versions pass through. Prereleases from `changeset pre enter <tag>` look like
 * `1.2.0-rc.0`; PEP 440 spells that `1.2.0rc0` (and `alpha` / `beta` as `a` / `b`).
 *
 * @param {string} version - Semver version, e.g. `0.142.0` or `1.0.0-rc.2`.
 * @returns {string} PEP 440 version, e.g. `0.142.0` or `1.0.0rc2`.
 * @throws {Error} When `version` is not semver, or its prerelease tag has no PEP 440 form.
 */
export function semverToPep440(version) {
  const match = SEMVER.exec(version);
  if (!match) {
    throw new Error(`Not a semver version: ${JSON.stringify(version)}`);
  }
  const [, major, minor, patch, pre] = match;
  const base = `${major}.${minor}.${patch}`;
  if (!pre) {
    return base;
  }
  const preMatch = /^([A-Za-z]+)\.(\d+)$/.exec(pre);
  const segment = preMatch && PEP440_PRE[preMatch[1].toLowerCase()];
  if (!segment) {
    throw new Error(
      `Prerelease "${pre}" has no PEP 440 form; use \`changeset pre enter rc\` (or alpha / beta).`,
    );
  }
  return `${base}${segment}${preMatch[2]}`;
}

/**
 * Replace the `version = "…"` line of the `[project]` table in a `pyproject.toml`.
 *
 * @param {string} text - Contents of `pyproject.toml`.
 * @param {string} version - PEP 440 version to write.
 * @returns {string} The updated contents.
 * @throws {Error} When the `[project]` table has no `version` line.
 */
export function setPyprojectVersion(text, version) {
  const project = /^\[project\]\s*$/m.exec(text);
  if (!project) {
    throw new Error("pyproject.toml has no [project] table");
  }
  const start = project.index + project[0].length;
  const nextTable = text.slice(start).search(/^\[/m);
  const end = nextTable === -1 ? text.length : start + nextTable;
  const table = text.slice(start, end);
  const line = /^version\s*=\s*"[^"]*"/m;
  if (!line.test(table)) {
    throw new Error("pyproject.toml [project] table has no version line");
  }
  return text.slice(0, start) + table.replace(line, `version = "${version}"`) + text.slice(end);
}

/**
 * Replace the version of the `apiome-cli` package entry in a `uv.lock`.
 *
 * @param {string} text - Contents of `uv.lock`.
 * @param {string} version - PEP 440 version to write.
 * @returns {string} The updated contents.
 * @throws {Error} When the lock has no `apiome-cli` package entry.
 */
export function setUvLockVersion(text, version) {
  const entry = new RegExp(`(\\[\\[package\\]\\]\\r?\\nname = "${PYTHON_NAME}"\\r?\\nversion = )"[^"]*"`);
  if (!entry.test(text)) {
    throw new Error(`uv.lock has no ${PYTHON_NAME} package entry`);
  }
  return text.replace(entry, `$1"${version}"`);
}

/**
 * Name the git tag for a release.
 *
 * @param {string} version - Semver version from `apiome-cli/package.json`.
 * @returns {string} Tag name, e.g. `cli-v0.142.0`.
 * @throws {Error} When `version` is not semver.
 */
export function releaseTag(version) {
  if (!SEMVER.test(version)) {
    throw new Error(`Not a semver version: ${JSON.stringify(version)}`);
  }
  return `${TAG_PREFIX}${version}`;
}

/**
 * Title of the changesets bot pull request.
 *
 * @param {string} version - Version the pull request releases.
 * @returns {string} e.g. `Release: apiome-cli v0.142.0`.
 */
export function releaseTitle(version) {
  return `Release: ${PYTHON_NAME} v${version}`;
}

/**
 * Read the next apiome-cli version from `changeset status --output` JSON.
 *
 * @param {{releases?: Array<{name: string, newVersion: string}>}} status - Parsed status file.
 * @returns {string | null} The version changesets will bump to, or `null` when nothing is pending.
 */
export function nextVersion(status) {
  const release = (status.releases ?? []).find((r) => r.name === PACKAGE_NAME);
  return release ? release.newVersion : null;
}

/**
 * Whether a changeset file's front matter releases `@apiome/cli`.
 *
 * An empty changeset (`changeset add --empty`) or one for another package does not count.
 *
 * @param {string} text - Contents of a `.changeset/*.md` file.
 * @returns {boolean} True when the front matter bumps `@apiome/cli` by patch, minor or major.
 */
export function changesetReleasesCli(text) {
  const front = /^---\r?\n([\s\S]*?)\r?\n?---/.exec(text);
  if (!front) {
    return false;
  }
  const line = /^\s*["']?@apiome\/cli["']?\s*:\s*["']?(patch|minor|major)["']?\s*$/m;
  return line.test(front[1]);
}

/**
 * Whether a path is a changeset a contributor writes (not the README, config or pre-mode state).
 *
 * @param {string} path - Repository-relative path.
 * @returns {boolean} True for `.changeset/<name>.md` other than `README.md`.
 */
export function isChangesetFile(path) {
  return /^\.changeset\/[^/]+\.md$/.test(path) && path !== ".changeset/README.md";
}

/**
 * Decide whether a pull request passes the changeset check.
 *
 * @param {object} pr
 * @param {Array<{status: string, path: string}>} pr.files - Changed files from
 *   `git diff --name-status` (status `A`, `M`, `D`, `R…`; for a rename, the new path).
 * @param {string[]} pr.labels - Pull request label names.
 * @param {string} pr.headRef - Pull request head branch.
 * @param {(path: string) => string} pr.readFile - Reads a changed file at the pull request head.
 * @returns {{ok: boolean, reason: string}} The verdict and a one-line explanation.
 */
export function checkChangeset({ files, labels, headRef, readFile }) {
  if (headRef.startsWith(RELEASE_BRANCH_PREFIX)) {
    return { ok: true, reason: "The changesets release pull request needs no changeset." };
  }
  if (!files.some((f) => f.path.startsWith("apiome-cli/"))) {
    return { ok: true, reason: "No apiome-cli/ files changed." };
  }
  if (labels.includes(SKIP_LABEL)) {
    return { ok: true, reason: `Labelled ${SKIP_LABEL}: no release needed.` };
  }
  const changesets = files.filter((f) => !f.status.startsWith("D") && isChangesetFile(f.path));
  const found = changesets.find((f) => changesetReleasesCli(readFile(f.path)));
  if (found) {
    return { ok: true, reason: `${found.path} releases ${PACKAGE_NAME}.` };
  }
  return {
    ok: false,
    reason:
      `apiome-cli/ changed but no changeset releases ${PACKAGE_NAME}. ` +
      `Run \`npx changeset\` in apiome-cli/ and commit the file, ` +
      `or add the \`${SKIP_LABEL}\` label for a docs-only or test-only change.`,
  };
}
