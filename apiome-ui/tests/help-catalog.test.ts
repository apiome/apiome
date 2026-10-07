/**
 * The guide set and the search over it (HIVE-4.9, #5303).
 *
 * Two questions, and the first is the one that keeps the page honest:
 *
 *   1. **Does the catalog still describe the docs site?** The listing is compiled into the
 *      bundle rather than read from disk (see `helpCatalog.ts`), which buys an instant,
 *      offline search at the cost of a listing that can fall behind the site. So this suite
 *      reads the real `apiome-docs/docs` tree and fails when a guide is missing from the catalog, or
 *      when the catalog names a page that no longer exists. That is the ticket's *"guide
 *      search returns results and links out correctly"* reduced to something a test can hold.
 *   2. **Does a search behave like a search?** Terms narrow rather than widen, the ranking is
 *      stable, a task word finds the page that answers it, and a query that matches nothing
 *      says so rather than falling back to everything.
 */

import { existsSync, readdirSync } from 'node:fs';
import { basename, join, relative } from 'node:path';

import {
  GUIDE_ENTRIES,
  GUIDE_QUERY_MIN_LENGTH,
  GUIDE_RESULT_LIMIT,
  GUIDE_SECTION_LABELS,
  guideHref,
  searchGuides,
  type GuideEntry,
} from '@/app/components/ade/help/helpCatalog';

/** The repository root, two levels above this package's `tests` directory. */
const REPO_ROOT = join(__dirname, '..', '..');

/** The docs site's page tree the catalog claims to describe. */
const SITE_DOCS_DIR = join(REPO_ROOT, 'apiome-docs', 'docs');

/** The site's home page, catalogued as the guide index (`README`, its old file name). */
const SITE_HOME = 'apiome-docs/docs/getting-started/index.mdx';

/**
 * Every page source under a directory, recursively, as repository-relative paths.
 *
 * @param dir Absolute directory to walk.
 * @returns `.md` / `.mdx` paths, skipping `_`-prefixed partials.
 */
function sitePages(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((item) => {
    if (item.name.startsWith('_')) return [];
    const full = join(dir, item.name);
    if (item.isDirectory()) return sitePages(full);
    return /\.mdx?$/.test(item.name) ? [relative(REPO_ROOT, full).split('\\').join('/')] : [];
  });
}

/**
 * The guide pages the catalog must list: every page except the group landing pages
 * (`<group>/index.mdx`), which only list the pages under them — plus the site home.
 */
const GUIDE_PAGES = sitePages(SITE_DOCS_DIR)
  .filter((page) => !/\/index\.mdx?$/.test(page) || page === SITE_HOME)
  .sort();

/**
 * Find one entry by id.
 *
 * @param id The entry's id, which is also its file's basename.
 * @returns The entry.
 */
function entry(id: string): GuideEntry {
  const found = GUIDE_ENTRIES.find((candidate) => candidate.id === id);
  if (!found) throw new Error(`The guide catalog has no entry \`${id}\``);
  return found;
}

/**
 * The ids a query returns, in order.
 *
 * @param query What a reader typed.
 * @returns The matching ids, best match first.
 */
function ids(query: string): string[] {
  return searchGuides(query).map((result) => result.id);
}

/* -------------------------------------------------------------------------
   1. The catalog still describes the directory
   ------------------------------------------------------------------------- */

describe('the guide catalog', () => {
  it('has an entry for every guide page on the docs site', () => {
    const catalogued = GUIDE_ENTRIES.map((guide) => guide.page).sort();
    expect(catalogued).toEqual(GUIDE_PAGES);
  });

  it('names only pages that exist on disk', () => {
    const missing = GUIDE_ENTRIES.filter((guide) => !existsSync(join(REPO_ROOT, guide.page)));
    expect(missing.map((guide) => guide.page)).toEqual([]);
  });

  it('names every page after its entry id, so the two cannot drift', () => {
    for (const guide of GUIDE_ENTRIES) {
      if (guide.page === SITE_HOME) continue;
      expect(basename(guide.page).replace(/\.mdx?$/, '')).toBe(guide.id);
    }
  });

  it('gives every entry a unique id', () => {
    expect(new Set(GUIDE_ENTRIES.map((guide) => guide.id)).size).toBe(GUIDE_ENTRIES.length);
  });

  it('gives every entry a title, a summary and at least one keyword', () => {
    for (const guide of GUIDE_ENTRIES) {
      expect(guide.title.trim().length).toBeGreaterThan(0);
      expect(guide.summary.trim().length).toBeGreaterThan(0);
      expect(guide.keywords.length).toBeGreaterThan(0);
    }
  });

  it('sorts every entry into one of the two sections the guide index has', () => {
    for (const guide of GUIDE_ENTRIES) {
      expect(GUIDE_SECTION_LABELS[guide.section]).toBeTruthy();
    }
    // Both sections are populated: a label nothing uses is a label that goes stale unnoticed.
    expect(new Set(GUIDE_ENTRIES.map((guide) => guide.section))).toEqual(
      new Set(['spine', 'reference'])
    );
  });

  it('spends no keyword on a word the title already carries', () => {
    // A duplicate would score twice for the same reason and quietly out-rank a better match.
    const offenders = GUIDE_ENTRIES.map((guide) => ({
      id: guide.id,
      redundant: guide.keywords.filter((keyword) =>
        guide.title.toLowerCase().includes(keyword.toLowerCase())
      ),
    })).filter((guide) => guide.redundant.length > 0);
    expect(offenders).toEqual([]);
  });
});

/* -------------------------------------------------------------------------
   2. Where a result goes
   ------------------------------------------------------------------------- */

describe('guideHref', () => {
  it('links out to the page on the documentation site', () => {
    expect(guideHref(entry('import-a-spec'))).toBe(
      'https://apiome.github.io/apiome/bring-in/import-a-spec'
    );
  });

  it('links the guide index to the site home', () => {
    expect(guideHref(entry('README'))).toBe('https://apiome.github.io/apiome/');
  });

  it('builds an absolute docs-site URL for every entry', () => {
    for (const guide of GUIDE_ENTRIES) {
      expect(guideHref(guide)).toMatch(/^https:\/\/apiome\.github\.io\/apiome\//);
    }
  });
});

/* -------------------------------------------------------------------------
   3. The search behaves like a search
   ------------------------------------------------------------------------- */

describe('searchGuides', () => {
  it('returns nothing until the query is long enough to mean something', () => {
    expect(searchGuides('')).toEqual([]);
    expect(searchGuides('p')).toEqual([]);
    expect(searchGuides('   ')).toEqual([]);
    expect('p'.length).toBeLessThan(GUIDE_QUERY_MIN_LENGTH);
  });

  it('finds the page that answers a task word, first', () => {
    expect(ids('publish')[0]).toBe('publish-a-version');
    expect(ids('import')[0]).toBe('import-a-spec');
  });

  it('matches a keyword the title never mentions', () => {
    // The X12 and copybook vocabulary is in the guide, not in its title.
    expect(ids('x12')).toContain('catalog-format-details');
    expect(ids('owasp')).toContain('mcp-trust-posture-rules');
    expect(ids('gitlab')).toContain('ci-gitlab-bitbucket');
  });

  it('narrows on a second term instead of widening', () => {
    const single = ids('mock');
    const pair = ids('mock fixture');
    expect(single.length).toBeGreaterThan(pair.length);
    // The fixture-packs page is the best match; pages that only mention fixtures follow it.
    expect(pair[0]).toBe('mock-fixture-packs');
  });

  it('ignores case and surrounding whitespace', () => {
    expect(ids('  PUBLISH  ')).toEqual(ids('publish'));
  });

  it('returns nothing at all when no guide matches', () => {
    expect(searchGuides('kubernetes helm chart')).toEqual([]);
  });

  it('never returns more than the result limit', () => {
    // `a` appears in nearly every summary, so this is the widest query the set can take.
    expect(searchGuides('ap').length).toBeLessThanOrEqual(GUIDE_RESULT_LIMIT);
  });

  it('is stable: the same query returns the same list', () => {
    expect(ids('version')).toEqual(ids('version'));
  });

  it('searches whatever set it is given, so the ranking can be tested in isolation', () => {
    const custom: GuideEntry[] = [
      {
        id: 'summary-hit',
        title: 'Something else',
        summary: 'Mentions widgets in passing.',
        page: 'docs/guide/summary-hit.md',
        section: 'reference',
        keywords: [],
      },
      {
        id: 'title-hit',
        title: 'Widgets',
        summary: 'The page about them.',
        page: 'docs/guide/title-hit.md',
        section: 'spine',
        keywords: [],
      },
    ];
    // A title hit outranks a summary hit even when the summary entry is listed first.
    expect(searchGuides('widgets', custom).map((result) => result.id)).toEqual([
      'title-hit',
      'summary-hit',
    ]);
  });
});
