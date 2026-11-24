/**
 * Statement budget for the public directory (DBP-1.16, #7199).
 *
 * The acceptance criterion: a Browse page view with a warm cache runs no global aggregate. The
 * root layout reads the directory statistics on every page, and the home page reads four more
 * catalog-wide lists; with the cache warm, none of them may reach the database.
 *
 * The pool is replaced by a recorder, so the test counts statements without a database. What each
 * statement costs cold is checked on the scale database by `apiome-db plan-check`
 * (`plan-check/hot-queries.json`, the `browse.*` entries).
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { query } = vi.hoisted(() => ({ query: vi.fn() }));

vi.mock('../db/db', () => ({
  default: { query },
  isStatementTimeout: (err: unknown) => (err as { code?: string } | null)?.code === '57014',
}));

import {
  getDirectoryStats,
  getMostVersionedProjects,
  getNewestTenants,
  getPublicTenants,
  getRecentlyPublishedVersions,
} from '../db/helper';
import { clearBrowseCache } from '../db/ttlCache';

/** The SQL text of a recorded call, whether it was passed as text or as a named statement. */
function sqlOf(call: unknown[]): string {
  const first = call[0];
  return typeof first === 'string' ? first : (first as { text: string }).text;
}

/** Everything the root layout and the home page read from the catalog-wide tables. */
async function renderHome(sort: 'versions' | 'operations' | 'grade' = 'versions') {
  return Promise.all([
    getDirectoryStats(),
    getPublicTenants(),
    getRecentlyPublishedVersions(8),
    getMostVersionedProjects(8, sort),
    getNewestTenants(8),
  ]);
}

beforeEach(() => {
  clearBrowseCache();
  delete process.env.BROWSE_CACHE_TTL_SECONDS;
  query.mockReset();
  query.mockImplementation(async (statement: unknown) => {
    const text = sqlOf([statement]);
    if (text.includes('tenant_count')) return { rows: [{ tenant_count: 3, project_count: 5, version_count: 8 }] };
    return { rows: [{ id: 'row' }] };
  });
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});

describe('directory statement budget', () => {
  it('a cold home page runs each directory read once: five statements', async () => {
    const [stats, tenants, recent, rail, newest] = await renderHome();
    expect(query).toHaveBeenCalledTimes(5);
    expect(stats).toEqual({ tenant_count: 3, project_count: 5, version_count: 8 });
    for (const rows of [tenants, recent, rail, newest]) expect(rows).toEqual([{ id: 'row' }]);
  });

  it('a warm page view runs no statement at all — no global aggregate', async () => {
    await renderHome();
    query.mockClear();

    await renderHome();
    await getDirectoryStats(); // any other page: the layout only
    expect(query).not.toHaveBeenCalled();
  });

  it('concurrent cold page views share one statement per read', async () => {
    await Promise.all([renderHome(), renderHome(), renderHome()]);
    expect(query).toHaveBeenCalledTimes(5);
  });

  it('caches each project rail order separately', async () => {
    await renderHome('versions');
    query.mockClear();
    await renderHome('operations');
    expect(query).toHaveBeenCalledTimes(1);
    expect(sqlOf(query.mock.calls[0])).toContain('cf.operation_count DESC NULLS LAST');
    query.mockClear();
    await renderHome('operations');
    await renderHome('versions');
    expect(query).not.toHaveBeenCalled();
  });

  it('reads every statement again once the cache is switched off', async () => {
    process.env.BROWSE_CACHE_TTL_SECONDS = '0';
    await renderHome();
    await renderHome();
    expect(query).toHaveBeenCalledTimes(10);
  });

  it('does not cache a failed read: zeros now, the real counts on the next page view', async () => {
    query.mockRejectedValueOnce(new Error('connection refused'));
    expect(await getDirectoryStats()).toEqual({ tenant_count: 0, project_count: 0, version_count: 0 });
    expect(await getDirectoryStats()).toEqual({ tenant_count: 3, project_count: 5, version_count: 8 });
  });
});

describe('directory statements', () => {
  it('read the summary table, never the versions of the whole catalog (DBP-1.27)', async () => {
    await renderHome('operations');
    const byScope = (needle: string) => query.mock.calls.map(sqlOf).find((text) => text.includes(needle)) ?? '';
    for (const text of [byScope('tenant_count'), byScope('GROUP BY b.tenant_id'), byScope('ORDER BY t.created_at DESC')]) {
      expect(text).toContain('apiome.browse_public_projects b');
      expect(text).not.toContain('apiome.versions');
      expect(text).not.toContain('apiome.projects');
    }
  });

  it('pick every rail order from the summary table, then compute card facts for the winners only', async () => {
    for (const sort of ['versions', 'operations', 'grade'] as const) {
      query.mockClear();
      await getMostVersionedProjects(8, sort);
      const text = sqlOf(query.mock.calls[0]);
      const ranked = text.slice(text.indexOf('WITH ranked AS'), text.indexOf('SELECT p.id'));
      // The ranking pass reads the summary table alone and stops at the limit…
      expect(ranked).toContain('FROM apiome.browse_public_projects b');
      expect(ranked).toContain('LIMIT $1');
      expect(ranked).not.toContain('apiome.versions');
      expect(ranked).not.toContain('sdk_generation_settings');
      // …and the facts are joined for those projects' latest versions.
      const rest = text.slice(text.indexOf('SELECT p.id'));
      expect(rest).toContain('f_v.id = rk.latest_version_id');
      expect(rest).toContain('sdk_generation_settings');
    }
  });

  it('give the three rail orders the same shape, differing only in the ORDER BY', async () => {
    const shapes: string[] = [];
    for (const sort of ['versions', 'operations', 'grade'] as const) {
      query.mockClear();
      await getMostVersionedProjects(8, sort);
      shapes.push(sqlOf(query.mock.calls[0]).replace(/ORDER BY [^\n]+/g, 'ORDER BY …'));
    }
    expect(shapes[1]).toBe(shapes[0]);
    expect(shapes[2]).toBe(shapes[0]);
  });

  it('rank the operations rail by the stored operation count', async () => {
    await getMostVersionedProjects(8, 'operations');
    const text = sqlOf(query.mock.calls[0]);
    expect(text).toContain('ORDER BY b.operation_count DESC, b.version_count DESC, b.latest_published_at DESC NULLS LAST');
    expect(text).toContain('cf.operation_count DESC NULLS LAST');
  });

  it('find the newest organizations with an EXISTS probe of the summary table', async () => {
    await getNewestTenants(8);
    const text = sqlOf(query.mock.calls[0]);
    expect(text).toContain('AND EXISTS (SELECT 1 FROM apiome.browse_public_projects b WHERE b.tenant_id = t.id)');
    expect(text).not.toContain('DISTINCT');
    expect(text).toContain('ORDER BY t.created_at DESC');
  });

  it('roll the organization list up by tenant id before joining tenant rows', async () => {
    await getPublicTenants();
    const text = sqlOf(query.mock.calls[0]);
    expect(text).toContain('GROUP BY b.tenant_id');
    expect(text).not.toContain('GROUP BY t.id, t.name');
  });

  it('count the directory from the summary rows', async () => {
    await getDirectoryStats();
    const text = sqlOf(query.mock.calls[0]);
    expect(text).toContain('COUNT(DISTINCT b.tenant_id)::int as tenant_count');
    expect(text).toContain('COALESCE(SUM(b.version_count), 0)::int as version_count');
  });
});
