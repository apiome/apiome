/**
 * Statement budget per route (DBP-1.27, #7210).
 *
 * The acceptance criterion: the statements each route runs are recorded and enforced, each at or
 * below its target, with no query repeated within a render. Every page and route handler reads
 * through one loader (`lib/db/routeLoaders.ts`, `lib/feed/changelogFeedRoute.ts`,
 * `lib/db/tryIt.ts`); this test runs each loader against a recording pool and holds it to the
 * number in `lib/db/statementBudgets.json`.
 *
 * React's `cache()` only memoizes inside a Server Component render, so it is replaced here by the
 * same thing made explicit: a memo that lasts for one "request" and is emptied between them.
 * A route whose page and `generateMetadata` both load is rendered by calling both.
 *
 * What each statement costs is checked on the scale database by `apiome-db plan-check`
 * (`plan-check/hot-queries.json`, the `browse.*` entries).
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { query, requestMemos } = vi.hoisted(() => ({
  query: vi.fn(),
  requestMemos: [] as Map<string, unknown>[],
}));

vi.mock('../db/db', () => ({
  default: { query },
  isStatementTimeout: (err: unknown) => (err as { code?: string } | null)?.code === '57014',
}));

vi.mock('react', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react')>()),
  cache: <A extends unknown[], R>(fn: (...args: A) => R) => {
    const memo = new Map<string, unknown>();
    requestMemos.push(memo);
    return (...args: A): R => {
      const key = JSON.stringify(args);
      if (!memo.has(key)) memo.set(key, fn(...args));
      return memo.get(key) as R;
    };
  },
}));

import budgets from '../db/statementBudgets.json';
import { getPublicVersionChangelog } from '../db/changelogs';
import { DatabaseUnavailableError } from '../db/errors';
import { getPublicMcpEndpointsByHost } from '../db/helper';
import { getPublicProjectIdentity } from '../db/identity';
import {
  loadChangelogPage,
  loadComparePage,
  loadMcpCollectionPage,
  loadMcpEndpointPage,
  loadProductPage,
  loadProjectPage,
  loadTenantPage,
  loadVersionPage,
} from '../db/routeLoaders';
import { clearTryItCache, getTryItVersion } from '../db/tryIt';
import { renderChangelogRss } from '../feed/changelog-feed';
import { serveChangelogFeed, type FeedFormat } from '../feed/changelogFeedRoute';

/** One row with every column any loader reads, so each statement finds what it looks for. */
const ROW = {
  id: 'id-1',
  name: 'Payments',
  slug: 'payments',
  description: null,
  tenant_id: 'tenant-1',
  tenant_slug: 'acme',
  tenant_name: 'Acme',
  state: 'published',
  version_id: '2.0.0',
  version_count: 2,
  mock_enabled: false,
  servers: [],
  sidebar_versions: [{ id: 'id-1', version_id: '2.0.0' }],
  published_revision_id: 'id-1',
  version_label: '2.0.0',
  published_at: null,
  baseline_version_label: null,
  max_severity: null,
  status: null,
  changelog_json: null,
  rows: [],
  version_labels: ['2.0.0', '1.0.0'],
  versions_in_range: 2,
  path_groups: [],
  since_not_found: false,
  project_id: 'id-1',
  project_name: 'Payments',
  changed_at: '2026-11-20T10:00:00.000000Z',
  kind: 'project_latest',
  ref: 'id-1',
  project_slug: 'payments',
  mcp_slug: null,
  version_selector: null,
  environment: null,
  mcp_public: false,
  current_version_id: 'snapshot-1',
  item_type: 'tool',
  label: '2.0.0',
  total_endpoints: 1,
  total_hosts: 1,
  host: 'mcp.example.com',
};

const RSS: FeedFormat = { extension: 'xml', contentType: 'application/rss+xml', render: renderChangelogRss };
const FEED_URL = 'https://browse.example.com/tenant/acme/payments/changelog.xml';

/** The SQL text and parameters of a recorded call. */
function statementOf(call: unknown[]): string {
  const first = call[0];
  const text = typeof first === 'string' ? first : (first as { text: string }).text;
  const values = typeof first === 'string' ? call[1] : (first as { values?: unknown[] }).values;
  return `${text}\n${JSON.stringify(values ?? [])}`;
}

/** Begin a new request: empty every per-request memo and the recorder. */
function newRequest(): void {
  for (const memo of requestMemos) memo.clear();
  query.mockClear();
}

/** The statements one render ran, after checking that none of them ran twice. */
function recorded(): string[] {
  const statements = query.mock.calls.map(statementOf);
  expect(new Set(statements).size, 'a statement ran twice in one render').toBe(statements.length);
  return statements;
}

beforeEach(() => {
  query.mockReset();
  query.mockImplementation(async () => ({ rows: [ROW] }));
  clearTryItCache();
  newRequest();
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});

describe('statement budget per route', () => {
  it('organization page: the organization, its projects, its products', async () => {
    expect(await loadTenantPage('acme')).not.toBeNull();
    expect(recorded()).toHaveLength(budgets.tenantPage);
    expect(budgets.tenantPage).toBe(3);
  });

  it('project page: the project with its facts, then its versions with their severity', async () => {
    expect(await loadProjectPage('acme', 'payments')).not.toBeNull();
    const statements = recorded();
    expect(statements).toHaveLength(budgets.projectPage);
    expect(budgets.projectPage).toBe(2);
    // No changelog payload is read for a severity pill.
    expect(statements.join('\n')).not.toContain('changelog_json');
  });

  it('version page: one statement, without the changelog entries', async () => {
    const page = await loadVersionPage('acme', 'payments', '2.0.0', false);
    expect(page?.versions).toEqual([{ id: 'id-1', version_id: '2.0.0' }]);
    const statements = recorded();
    expect(statements).toHaveLength(budgets.versionPage);
    expect(budgets.versionPage).toBe(1);
    expect(statements[0]).toContain("ELSE vc.changelog_json - 'entries' END");
    expect(JSON.parse(statements[0].slice(statements[0].lastIndexOf('\n') + 1))[3]).toBe(false);
  });

  it('version page opened on the Changes tab: still one statement, with the entries', async () => {
    await loadVersionPage('acme', 'payments', '2.0.0', true);
    const statements = recorded();
    expect(statements).toHaveLength(budgets.versionPage);
    expect(JSON.parse(statements[0].slice(statements[0].lastIndexOf('\n') + 1))[3]).toBe(true);
  });

  it('Changes tab opened later: one statement for the entries', async () => {
    await getPublicVersionChangelog('acme', 'payments', '2.0.0');
    expect(recorded()).toHaveLength(budgets.versionChanges);
  });

  it('changelog page with its metadata: the project once, one changelog page, lifecycle news', async () => {
    await getPublicProjectIdentity('acme', 'payments'); // generateMetadata
    expect(await loadChangelogPage('acme', 'payments', { severity: 'breaking' })).not.toBeNull();
    expect(recorded()).toHaveLength(budgets.changelogPage);
    expect(budgets.changelogPage).toBe(3);
  });

  it('compare page: the project, its version labels, one changelog row for the pair', async () => {
    const data = await loadComparePage('acme', 'payments', '1.0.0', '2.0.0');
    expect(data?.changelogs).toHaveLength(1);
    const statements = recorded();
    expect(statements).toHaveLength(budgets.comparePage);
    expect(budgets.comparePage).toBe(3);
    // The pair's row comes without its entries.
    expect(statements[2]).toContain("vc.changelog_json - 'entries' AS changelog_json");
  });

  it('product page with its metadata: the product once', async () => {
    await loadProductPage('acme', 'gold'); // generateMetadata
    expect(await loadProductPage('acme', 'gold')).not.toBeNull();
    expect(recorded()).toHaveLength(budgets.productPage);
    expect(budgets.productPage).toBe(4);
  });

  it('MCP endpoint page: the endpoint, then its capability items — read once', async () => {
    const detail = await loadMcpEndpointPage('acme', 'docs');
    expect(detail?.endpoint.tool_count).toBe(1);
    const statements = recorded();
    expect(statements).toHaveLength(budgets.mcpEndpointPage);
    expect(statements.filter((s) => s.includes('apiome.mcp_capability_items'))).toHaveLength(1);
  });

  it('MCP collection page with its metadata: the collection once', async () => {
    await loadMcpCollectionPage('acme', 'starter'); // generateMetadata
    expect(await loadMcpCollectionPage('acme', 'starter')).not.toBeNull();
    expect(recorded()).toHaveLength(budgets.mcpCollectionPage);
    expect(budgets.mcpCollectionPage).toBe(2);
  });

  it('MCP index: one statement for a page of endpoints', async () => {
    const index = await getPublicMcpEndpointsByHost(2);
    expect(index.page).toBe(2);
    const statements = recorded();
    expect(statements).toHaveLength(budgets.mcpIndexPage);
    expect(statements[0]).toContain('LIMIT $1 OFFSET $2');
    expect(statements[0]).toContain('[100,100]');
  });

  it('changelog feed: two statements, and one when it has not changed', async () => {
    const first = await serveChangelogFeed(new Request(FEED_URL), 'acme', 'payments', RSS);
    expect(first.status).toBe(200);
    expect(recorded()).toHaveLength(budgets.changelogFeed);
    const etag = first.headers.get('etag') as string;

    newRequest();
    const second = await serveChangelogFeed(
      new Request(FEED_URL, { headers: { 'If-None-Match': etag } }),
      'acme',
      'payments',
      RSS
    );
    expect(second.status).toBe(304);
    const statements = recorded();
    expect(statements).toHaveLength(budgets.changelogFeedUnchanged);
    expect(budgets.changelogFeedUnchanged).toBe(1);
    // The one statement reads no changelog payload.
    expect(statements[0]).not.toContain('changelog_json');
  });

  it('Try It relay: one statement, and none for the requests that follow', async () => {
    expect(await getTryItVersion('acme', 'payments', '2.0.0')).toMatchObject({ version_id: '2.0.0' });
    expect(recorded()).toHaveLength(budgets.tryIt);
    expect(budgets.tryIt).toBe(1);

    newRequest();
    await getTryItVersion('acme', 'payments', '2.0.0');
    await getTryItVersion('acme', 'payments', '2.0.0');
    expect(recorded()).toHaveLength(budgets.tryItRepeat);
  });
});

describe('a database failure is an error, never "not found"', () => {
  const failing = () => query.mockRejectedValue(Object.assign(new Error('timeout exceeded when trying to connect'), {}));

  it.each([
    ['organization page', () => loadTenantPage('acme')],
    ['project page', () => loadProjectPage('acme', 'payments')],
    ['version page', () => loadVersionPage('acme', 'payments', '2.0.0', false)],
    ['changelog page', () => loadChangelogPage('acme', 'payments', {})],
    ['compare page', () => loadComparePage('acme', 'payments')],
    ['product page', () => loadProductPage('acme', 'gold')],
    ['MCP endpoint page', () => loadMcpEndpointPage('acme', 'docs')],
    ['MCP collection page', () => loadMcpCollectionPage('acme', 'starter')],
    ['MCP index', () => getPublicMcpEndpointsByHost()],
    ['Try It relay', () => getTryItVersion('acme', 'payments', '2.0.0')],
  ])('%s throws DatabaseUnavailableError with the pool exhausted', async (_name, load) => {
    failing();
    await expect(load()).rejects.toBeInstanceOf(DatabaseUnavailableError);
  });

  it.each([
    ['organization page', () => loadTenantPage('acme')],
    ['project page', () => loadProjectPage('acme', 'payments')],
    ['version page', () => loadVersionPage('acme', 'payments', '2.0.0', false)],
    ['changelog page', () => loadChangelogPage('acme', 'payments', {})],
    ['compare page', () => loadComparePage('acme', 'payments')],
    ['product page', () => loadProductPage('acme', 'gold')],
    ['MCP endpoint page', () => loadMcpEndpointPage('acme', 'docs')],
    ['MCP collection page', () => loadMcpCollectionPage('acme', 'starter')],
    ['Try It relay', () => getTryItVersion('acme', 'payments', '2.0.0')],
  ])('%s still answers null — 404 — when the row is simply not there', async (_name, load) => {
    query.mockImplementation(async () => ({ rows: [] }));
    expect(await load()).toBeNull();
  });

  it('a feed answers 503 with Retry-After, not 404', async () => {
    failing();
    const response = await serveChangelogFeed(new Request(FEED_URL), 'acme', 'payments', RSS);
    expect(response.status).toBe(503);
    expect(response.headers.get('retry-after')).toBe('5');
    expect(response.headers.get('cache-control')).toBe('no-store');
  });

  it('a feed answers 404 for a project that is not public', async () => {
    query.mockImplementation(async () => ({ rows: [] }));
    expect((await serveChangelogFeed(new Request(FEED_URL), 'acme', 'nope', RSS)).status).toBe(404);
  });

  it('the Try It relay never applies a remembered policy after its interval when the refresh fails', async () => {
    vi.useFakeTimers();
    try {
      await getTryItVersion('acme', 'payments', '2.0.0');
      vi.advanceTimersByTime(31_000);
      failing();
      await expect(getTryItVersion('acme', 'payments', '2.0.0')).rejects.toBeInstanceOf(DatabaseUnavailableError);
    } finally {
      vi.useRealTimers();
    }
  });
});
