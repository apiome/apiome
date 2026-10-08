/**
 * The one spelling of a documentation link (HIVE-4.9, #5303; DOCS-1.2, #5619).
 *
 * `buildDocsHref` was extracted when the Help & docs page became the third caller that needed
 * a `docs/…` URL — after the lint rule catalog and the governance axis panels, each of which
 * carried its own copy of the base string. Those two keep their own exported builders (their
 * defaults differ) and their own suites; this pins the shared piece: a docs-site page resolves
 * to the site, a path from the old `docs/guide/` folder resolves to where that page moved, and
 * any other repository file still opens on GitHub — with and without the leading slash the REST
 * API sometimes sends.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import {
  DOCS_SITE_BASE,
  GITHUB_DOCS_BASE,
  LEGACY_GUIDE_ROUTES,
  buildDocsHref,
} from '@/app/utils/docsLinks';
import { buildLintRuleDocsHref } from '@/app/utils/lint-rule-catalog';
import { buildGovernanceDocsHref } from '@/app/utils/lint-axis-ui';

/** The repository root, two levels above this package's `tests` directory. */
const REPO_ROOT = join(__dirname, '..', '..');

describe('buildDocsHref', () => {
  it('serves a docs-site page from the site, without the extension', () => {
    expect(buildDocsHref('apiome-docs/docs/reference/cli-quickstart.md')).toBe(
      `${DOCS_SITE_BASE}reference/cli-quickstart`
    );
    expect(buildDocsHref('apiome-docs/docs/admin/docs-image.mdx')).toBe(
      `${DOCS_SITE_BASE}admin/docs-image`
    );
  });

  it('serves a group landing page at the group, and the getting-started index at the root', () => {
    expect(buildDocsHref('apiome-docs/docs/ship/index.mdx')).toBe(`${DOCS_SITE_BASE}ship`);
    expect(buildDocsHref('apiome-docs/docs/getting-started/index.mdx')).toBe(DOCS_SITE_BASE);
  });

  it('tolerates the leading slash the API sometimes sends', () => {
    expect(buildDocsHref('/apiome-docs/docs/reference/cli-quickstart.md')).toBe(
      buildDocsHref('apiome-docs/docs/reference/cli-quickstart.md')
    );
  });

  it('appends an anchor when there is one', () => {
    expect(
      buildDocsHref('apiome-docs/docs/build/lint-rules.md', 'naming-schema-pascal-case')
    ).toBe(`${DOCS_SITE_BASE}build/lint-rules#naming-schema-pascal-case`);
  });

  it('treats an absent, blank or whitespace-only anchor as no anchor', () => {
    for (const anchor of [undefined, null, '', '   ']) {
      expect(buildDocsHref('apiome-docs/docs/build/lint-rules.md', anchor)).toBe(
        `${DOCS_SITE_BASE}build/lint-rules`
      );
    }
  });

  it('sends a path from the old docs/guide folder to the page it moved to', () => {
    expect(buildDocsHref('docs/guide/lint-rules.md', 'naming-schema-pascal-case')).toBe(
      `${DOCS_SITE_BASE}build/lint-rules#naming-schema-pascal-case`
    );
    expect(buildDocsHref('/docs/guide/portable-mock-runtime.md')).toBe(
      `${DOCS_SITE_BASE}reference/mock-runtime/portable-mock-runtime`
    );
    expect(buildDocsHref('docs/guide/README.md')).toBe(DOCS_SITE_BASE);
  });

  it('leaves other repository files, and unknown guide names, on GitHub', () => {
    expect(buildDocsHref('docs/runbooks/PRODUCTION_DEPLOY.md')).toBe(
      `${GITHUB_DOCS_BASE}docs/runbooks/PRODUCTION_DEPLOY.md`
    );
    expect(buildDocsHref('docs/guide/no-such-page.md')).toBe(
      `${GITHUB_DOCS_BASE}docs/guide/no-such-page.md`
    );
    // An inherited object key is not a guide name.
    expect(buildDocsHref('docs/guide/toString.md')).toBe(
      `${GITHUB_DOCS_BASE}docs/guide/toString.md`
    );
  });

  it('is the base both older builders now resolve through', () => {
    // The point of the extraction: one URL to change if the site ever moves.
    expect(buildLintRuleDocsHref('', '')).toBe(`${DOCS_SITE_BASE}build/lint-rules`);
    expect(buildGovernanceDocsHref(null)).toBe(`${DOCS_SITE_BASE}build/axis-score`);
  });
});

describe('LEGACY_GUIDE_ROUTES', () => {
  it('points every old guide at a page that exists on the docs site', () => {
    const missing = Object.entries(LEGACY_GUIDE_ROUTES)
      .filter(([, route]) => route !== '')
      .filter(([, route]) => !existsSync(join(REPO_ROOT, 'apiome-docs', 'docs', `${route}.md`)))
      .map(([name]) => name);
    expect(missing).toEqual([]);
  });

  it('is the map docs/guide/README.md publishes', () => {
    const readme = readFileSync(join(REPO_ROOT, 'docs', 'guide', 'README.md'), 'utf8');
    for (const [name, route] of Object.entries(LEGACY_GUIDE_ROUTES)) {
      if (route === '') continue;
      expect(readme).toContain(`| \`${name}.md\` | [`);
      expect(readme).toContain(`(${DOCS_SITE_BASE}${route})`);
    }
  });
});
