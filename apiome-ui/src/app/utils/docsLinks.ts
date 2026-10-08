/**
 * Where a written guide lives, spelled once (HIVE-4.9, #5303; DOCS-1.2, #5619).
 *
 * The guide is the Docusaurus site built from `apiome-docs/docs/` and published at
 * {@link DOCS_SITE_BASE}. Every "read the guide" affordance — the lint rule catalog, the
 * governance axis panels, the Help & docs page — names a page by its **repository path**
 * (that is also what the REST API returns in its `docsPage` fields) and resolves it here:
 *
 * - `apiome-docs/docs/<group>/<page>.md(x)` → the page on the site;
 * - `docs/guide/<page>.md`, the folder the guide moved out of, → the page it moved to, so a
 *   path stored before the move (an old lint result, a cached payload) still lands somewhere;
 * - anything else in the repository (`docs/runbooks/…`, a package README) → GitHub.
 *
 * The two callers that predate this module keep their own exported builders
 * (`buildLintRuleDocsHref`, `buildGovernanceDocsHref`), because each applies its own default
 * page before delegating here; what they no longer keep is the URL.
 */

/** The published documentation site. Every guide link hangs off it. */
export const DOCS_SITE_BASE = 'https://apiome.github.io/apiome/';

/** Repository directory holding the site's pages; a path under it is a page on the site. */
export const DOCS_SITE_PAGES_ROOT = 'apiome-docs/docs/';

/** Blob root of the default branch, for repository files that are not site pages. */
export const GITHUB_DOCS_BASE = 'https://github.com/apiome/apiome/blob/main/';

/**
 * Where each page of the old `docs/guide/` folder lives on the site, by file name.
 *
 * Mirrors the path map in `docs/guide/README.md`; `tests/docs-links.test.ts` checks that every
 * route here is a page that exists under `apiome-docs/docs/`.
 */
export const LEGACY_GUIDE_ROUTES: Readonly<Record<string, string>> = {
  README: '',
  'import-a-spec': 'bring-in/import-a-spec',
  'supported-formats': 'bring-in/supported-formats',
  'catalog-format-details': 'bring-in/catalog-format-details',
  'convert-to-openapi': 'bring-in/convert-to-openapi',
  'spectral-import': 'bring-in/spectral-import',
  'schematron-import': 'bring-in/schematron-import',
  'edit-classes-and-properties': 'build/edit-classes-and-properties',
  'edit-paths': 'build/edit-paths',
  'lint-and-quality': 'build/lint-and-quality',
  'axis-score': 'build/axis-score',
  'custom-rules': 'build/custom-rules',
  'lint-rules': 'build/lint-rules',
  'cut-a-version': 'ship/cut-a-version',
  'publish-a-version': 'ship/publish-a-version',
  'browse-published-specs': 'ship/browse-published-specs',
  'export-a-spec': 'ship/export-a-spec',
  'export-fidelity': 'ship/export-fidelity',
  'one-mock-engine': 'reference/mock-runtime/one-mock-engine',
  'mock-bundle-format': 'reference/mock-runtime/mock-bundle-format',
  'portable-mock-runtime': 'reference/mock-runtime/portable-mock-runtime',
  'mock-fixture-packs': 'reference/mock-runtime/mock-fixture-packs',
  'mock-callbacks': 'reference/mock-runtime/mock-callbacks',
  'mock-response-correlation': 'reference/mock-runtime/mock-response-correlation',
  'mock-response-preview': 'reference/mock-runtime/mock-response-preview',
  'mock-proxy-capture': 'reference/mock-runtime/mock-proxy-capture',
  'serverless-mock-adapter': 'reference/mock-runtime/serverless-mock-adapter',
  'mock-release-attestation': 'reference/mock-runtime/mock-release-attestation',
  'style-guide-revisions': 'govern/style-guide-revisions',
  'mcp-conformance-rules': 'govern/mcp-conformance-rules',
  'mcp-surface-lint-rules': 'govern/mcp-surface-lint-rules',
  'mcp-trust-posture-rules': 'govern/mcp-trust-posture-rules',
  'api-reference': 'reference/api-reference',
  'cli-quickstart': 'reference/cli-quickstart',
  'mcp-quickstart': 'reference/mcp-quickstart',
  'ci-diff-gate': 'reference/ci/ci-diff-gate',
  'ci-gitlab-bitbucket': 'reference/ci/ci-gitlab-bitbucket',
  keyboard: 'workspace/keyboard',
  accessibility: 'workspace/accessibility',
  'content-voice': 'reference/content-voice',
};

/** `docs/guide/<name>.md` — a path into the folder the guide moved out of. */
const LEGACY_GUIDE_PATH = /^docs\/guide\/([^/]+)\.md$/;

/**
 * The site route of a page under {@link DOCS_SITE_PAGES_ROOT}.
 *
 * Docusaurus serves `build/lint-rules.md` at `build/lint-rules`, a group's `index.mdx` at the
 * group (`build/index.mdx` → `build`), and the getting-started index at the site root.
 *
 * @param sitePage Path relative to {@link DOCS_SITE_PAGES_ROOT}, e.g. `build/lint-rules.md`.
 * @returns The route without a leading slash; `''` for the site root.
 */
function siteRoute(sitePage: string): string {
  const route = sitePage.replace(/\.mdx?$/, '').replace(/(^|\/)index$/, '');
  return route === 'getting-started' ? '' : route;
}

/**
 * Build an external link to a documentation page.
 *
 * @param docsPage Repository-relative path, e.g. `apiome-docs/docs/build/lint-rules.md`. A
 *   leading slash is tolerated and stripped, since the REST API returns the path both ways. A
 *   `docs/guide/…` path from before the move resolves to the page's new home on the site.
 * @param docsAnchor Optional heading anchor within the page, without the `#`. Blank,
 *   whitespace-only and absent are all treated as "no anchor".
 * @returns The absolute URL — on the docs site for guide pages, on GitHub for any other
 *   repository file. Never relative: these open in a new tab, away from the app.
 */
export function buildDocsHref(docsPage: string, docsAnchor?: string | null): string {
  const page = docsPage.replace(/^\//, '');
  const anchor = (docsAnchor ?? '').trim();
  const suffix = anchor ? `#${anchor}` : '';

  if (page.startsWith(DOCS_SITE_PAGES_ROOT)) {
    return `${DOCS_SITE_BASE}${siteRoute(page.slice(DOCS_SITE_PAGES_ROOT.length))}${suffix}`;
  }

  const legacy = LEGACY_GUIDE_PATH.exec(page);
  if (legacy && Object.prototype.hasOwnProperty.call(LEGACY_GUIDE_ROUTES, legacy[1])) {
    return `${DOCS_SITE_BASE}${LEGACY_GUIDE_ROUTES[legacy[1]]}${suffix}`;
  }

  return `${GITHUB_DOCS_BASE}${page}${suffix}`;
}
