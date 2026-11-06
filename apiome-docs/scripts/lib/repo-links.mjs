/**
 * Where a repository file is read on the docs site — the docs never link to GitHub.
 *
 * Some repository files have a page on the site that says the same thing (the CLI README is the
 * CLI reference, an action's README is its CI page). A link to one of them becomes a link to that
 * page. A link to any other repository file — a runbook, an `.env.example`, a design note — has no
 * page to go to, so the link is dropped and its text kept: a reader with a checkout can still find
 * the file by the name it gives.
 */

/**
 * Repository files (or folders) whose content the site carries, and the page that carries it,
 * relative to `apiome-docs/docs/`. A folder entry ends in `/` and covers everything inside it.
 *
 * @type {ReadonlyArray<readonly [string, string]>}
 */
export const SITE_EQUIVALENTS = Object.freeze([
  ['apiome-cli/README.md', 'reference/cli/index.mdx'],
  ['apiome-mcp/README.md', 'reference/mcp-quickstart.md'],
  ['apiome-mcp/docs/CONFIGURATION.md', 'reference/mcp-quickstart.md'],
  ['diff-action/recipes/', 'reference/ci/ci-gitlab-bitbucket.md'],
  ['diff-action/', 'reference/ci/diff-action.md'],
  ['mock-action/', 'reference/ci/mock-action.md'],
  ['docs/GOLDEN_PATH.md', 'getting-started/index.mdx'],
]);

/**
 * README sections that have a page of their own, keyed `file#anchor`.
 *
 * @type {Readonly<Record<string, string>>}
 */
export const SECTION_EQUIVALENTS = Object.freeze({
  'apiome-cli/README.md#export-a-version-to-a-target-format': 'reference/cli/export.md',
  'apiome-cli/README.md#classified-diff-ci-gate': 'reference/cli/diff.md',
});

/**
 * The docs page that carries a repository file, if any.
 *
 * @param {string} repoPath - The file or folder, relative to the repository root (`diff-action/`,
 *   `apiome-cli/README.md`). A trailing slash is optional.
 * @param {string} [anchor] - The section the link points at, without `#`.
 * @returns {string | null} The page relative to `apiome-docs/docs/`, or `null` when the site has
 *   no page for it (the caller then keeps the link's text and drops the link).
 */
export function sitePageForRepoPath(repoPath, anchor = '') {
  const file = repoPath.replace(/^\.\//, '');
  if (anchor && SECTION_EQUIVALENTS[`${file}#${anchor}`]) return SECTION_EQUIVALENTS[`${file}#${anchor}`];
  const asFolder = file.endsWith('/') ? file : `${file}/`;
  for (const [source, page] of SITE_EQUIVALENTS) {
    if (source.endsWith('/') ? asFolder.startsWith(source) || file === source.slice(0, -1) : file === source) {
      return page;
    }
  }
  return null;
}
