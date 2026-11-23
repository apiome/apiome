/**
 * The SQL shape of the UI's bounded lists (DBP-1.13, #7196).
 *
 * Three kinds of list, each pinned here against a mocked pool:
 *
 * - **Paged** — the Published list and the admin console's lists read `limit + 1` rows after a
 *   keyset cursor and answer `{ hasMore, nextCursor }`.
 * - **Capped** — lists nothing pages carry `LIMIT` with `MAX_UNPAGED_ROWS` as a bind value.
 * - **Narrow** — none of them selects `*`, and the columns a caller must never receive (a
 *   password hash, a key hash, the embedding) are not in any projection.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

const mockQuery =
  jest.fn<(sql: string, params?: unknown[]) => Promise<{ rows: unknown[]; rowCount?: number }>>();
jest.mock('../lib/db/db', () => ({
  query: (sql: string, params?: unknown[]) => mockQuery(sql, params),
}));

import * as admin from '../lib/db/admin-helper';
import * as helper from '../lib/db/helper';
import {
  DEFAULT_LIST_ROWS,
  MAX_LIST_ROWS,
  MAX_UNPAGED_ROWS,
  decodeKeyCursor,
  decodeTimeIdCursor,
  encodeKeyCursor,
  encodeTimeIdCursor,
} from '../lib/db/list-bounds';

const TENANT = '7d1f5a52-0d8e-4e5c-9f5e-3a1f0f6f1a01';
const ID_A = '0b9f6c0e-6f0a-4a57-9a55-0e7b2f8f3c11';
const ID_B = '1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f';
const STAMP = '2026-01-02T03:04:05.678901Z';

/** The single statement a call ran, whitespace-collapsed, with its parameters. */
function onlyCall(): { sql: string; params: unknown[] } {
  expect(mockQuery).toHaveBeenCalledTimes(1);
  const [sql, params] = mockQuery.mock.calls[0];
  return { sql: String(sql).replace(/\s+/g, ' ').trim(), params: params ?? [] };
}

/** `count` rows shaped like a `(timestamp, id)` page read. */
const timeRows = (count: number) =>
  Array.from({ length: count }, (_, index) => ({
    id: `id-${index}`,
    name: `Row ${index}`,
    cursor_ts: `2026-01-02T03:04:05.${String(900000 - index).padStart(6, '0')}Z`,
    cursor_id: `id-${index}`,
  }));

beforeEach(() => {
  mockQuery.mockReset();
  mockQuery.mockResolvedValue({ rows: [], rowCount: 0 });
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
});

/* ------------------------------------------------------------------------------------------
   The Published list
   ------------------------------------------------------------------------------------------ */

describe('getPublishedVersionsForTenant', () => {
  const publishedRows = (count: number) =>
    Array.from({ length: count }, (_, index) => ({
      id: `v-${index}`,
      version_id: `1.0.${index}`,
      cursor_published_at: `2026-02-01 10:00:00.${String(500000 - index).padStart(6, '0')}+00`,
      cursor_created_at: '2026-01-01 09:00:00.000001+00',
    }));

  test('the first page reads limit + 1 rows in keyset order, with no cursor predicate', async () => {
    await helper.getPublishedVersionsForTenant(TENANT);
    const { sql, params } = onlyCall();

    expect(params).toEqual([TENANT, null, DEFAULT_LIST_ROWS + 1]);
    expect(sql).toContain(
      "ORDER BY COALESCE(v.published_at, 'infinity'::timestamptz) DESC, " +
        "COALESCE(v.created_at, 'infinity'::timestamptz) DESC, v.id DESC LIMIT $3",
    );
    expect(sql).not.toContain('< ($3::timestamptz');
    expect(sql).not.toMatch(/SELECT \*|\bv\.\*|mcp_public_embedding/);
  });

  test('a short read is the last page', async () => {
    mockQuery.mockResolvedValue({ rows: publishedRows(3) });
    const page = JSON.parse(await helper.getPublishedVersionsForTenant(TENANT, null, { limit: 3 }));

    expect(page).toEqual({
      success: true,
      versions: [
        { id: 'v-0', version_id: '1.0.0' },
        { id: 'v-1', version_id: '1.0.1' },
        { id: 'v-2', version_id: '1.0.2' },
      ],
      hasMore: false,
      nextCursor: null,
    });
  });

  test('a limit + 1 read is cut to the limit; the cursor names the last row kept', async () => {
    mockQuery.mockResolvedValue({ rows: publishedRows(3) });
    const page = JSON.parse(await helper.getPublishedVersionsForTenant(TENANT, null, { limit: 2 }));

    expect(page.versions.map((row: { id: string }) => row.id)).toEqual(['v-0', 'v-1']);
    expect(page.hasMore).toBe(true);
    // The sort key as PostgreSQL printed it — microseconds intact — then the id.
    expect(decodeKeyCursor(page.nextCursor, 3)).toEqual([
      '2026-02-01 10:00:00.499999+00',
      '2026-01-01 09:00:00.000001+00',
      'v-1',
    ]);
    // The cursor-only columns never reach the screen.
    expect(JSON.stringify(page.versions)).not.toContain('cursor_');
  });

  test('the next page continues after the cursor with a row-value comparison', async () => {
    const cursor = encodeKeyCursor(['2026-02-01 10:00:00.499999+00', 'infinity', ID_A]);
    await helper.getPublishedVersionsForTenant(TENANT, 'payments', { limit: 25, cursor });
    const { sql, params } = onlyCall();

    expect(params).toEqual([
      TENANT,
      'payments',
      '2026-02-01 10:00:00.499999+00',
      'infinity',
      ID_A,
      26,
    ]);
    expect(sql).toContain(
      "AND (COALESCE(v.published_at, 'infinity'::timestamptz), " +
        "COALESCE(v.created_at, 'infinity'::timestamptz), v.id) " +
        '< ($3::timestamptz, $4::timestamptz, $5::uuid)',
    );
    expect(sql).toMatch(/v\.id DESC LIMIT \$6$/);
  });

  test('the page size is clamped to the hard maximum', async () => {
    await helper.getPublishedVersionsForTenant(TENANT, null, { limit: 100_000 });
    expect(onlyCall().params).toEqual([TENANT, null, MAX_LIST_ROWS + 1]);
  });

  test.each([
    ['garbage', 'not-a-cursor'],
    ['a cursor of another list', encodeTimeIdCursor(STAMP, ID_A)],
    ['a key cursor of the wrong size', encodeKeyCursor(['a', ID_A])],
    ['a key cursor holding a non-text value', encodeKeyCursor([1, 2, ID_A])],
  ])('%s is refused before any statement runs', async (_label, cursor) => {
    const page = JSON.parse(await helper.getPublishedVersionsForTenant(TENANT, null, { cursor }));
    expect(page).toEqual({ success: false, error: 'Invalid cursor' });
    expect(mockQuery).not.toHaveBeenCalled();
  });

  test('a failed read is still an error, never an empty list', async () => {
    mockQuery.mockRejectedValue(new Error('connection refused'));
    expect(JSON.parse(await helper.getPublishedVersionsForTenant(TENANT))).toEqual({
      success: false,
      error: 'connection refused',
    });
  });
});

/* ------------------------------------------------------------------------------------------
   The admin console's lists
   ------------------------------------------------------------------------------------------ */

describe('the (timestamp, id) admin lists', () => {
  test.each([
    ['getAllUsers', () => admin.getAllUsers(), 'users', 'FROM apiome.users', 'created_at', 'id'],
    [
      'getAllTenants',
      () => admin.getAllTenants(),
      'tenants',
      'FROM apiome.tenants',
      'created_at',
      'id',
    ],
    [
      'getTenantStats',
      () => admin.getTenantStats(),
      'tenants',
      'FROM apiome.tenants t',
      't.created_at',
      't.id',
    ],
  ] as const)(
    '%s reads the first page newest first, limit + 1',
    async (_name, call, key, from, stamp, id) => {
      const page = JSON.parse(await call());
      const { sql, params } = onlyCall();

      expect(sql).toContain(from);
      expect(sql).toContain(
        `ORDER BY COALESCE(${stamp}, 'epoch'::timestamptz) DESC, ${id} DESC LIMIT $1`,
      );
      expect(params).toEqual([DEFAULT_LIST_ROWS + 1]);
      expect(sql).not.toMatch(/SELECT \*|\b[a-z]+\.\*/);
      expect(page).toEqual({ success: true, [key]: [], hasMore: false, nextCursor: null });
    },
  );

  test('getAllUsers never selects the password hash', async () => {
    await admin.getAllUsers();
    expect(onlyCall().sql).not.toMatch(/password/);
  });

  test('a full page carries a {"t","i"} cursor built from the microsecond text', async () => {
    mockQuery.mockResolvedValue({ rows: timeRows(3) });
    const page = JSON.parse(await admin.getAllUsers({ limit: 2 }));

    expect(page.users).toEqual([
      { id: 'id-0', name: 'Row 0' },
      { id: 'id-1', name: 'Row 1' },
    ]);
    expect(page.hasMore).toBe(true);
    expect(decodeTimeIdCursor(page.nextCursor)).toEqual({
      t: '2026-01-02T03:04:05.899999Z',
      i: 'id-1',
    });
  });

  test('the next page is a row-value comparison below the cursor, then the search', async () => {
    await admin.getAllUsers({
      limit: 10,
      cursor: encodeTimeIdCursor(STAMP, ID_A),
      search: ' Ada_ ',
    });
    const { sql, params } = onlyCall();

    expect(params).toEqual(['%Ada\\_%', STAMP, ID_A, 11]);
    expect(sql).toContain('(name ILIKE $1 OR email ILIKE $1)');
    expect(sql).toContain(
      "(COALESCE(created_at, 'epoch'::timestamptz), id) < ($2::timestamptz, $3::uuid)",
    );
    expect(sql).toMatch(/LIMIT \$4$/);
  });

  test('getTenantStats counts per tenant with correlated subqueries, not a three-way join', async () => {
    await admin.getTenantStats({ search: 'acme' });
    const { sql, params } = onlyCall();

    expect(sql).toContain(
      '(SELECT COUNT(DISTINCT tu.user_id) FROM apiome.tenant_users tu WHERE tu.tenant_id = t.id) as user_count',
    );
    expect(sql).toContain('(t.name ILIKE $1 OR t.slug ILIKE $1)');
    expect(sql).not.toMatch(/GROUP BY|LEFT JOIN/);
    expect(params).toEqual(['%acme%', DEFAULT_LIST_ROWS + 1]);
  });

  test('getTenantStats adds the totals, counted in SQL, only when asked', async () => {
    mockQuery.mockResolvedValueOnce({ rows: timeRows(1) }).mockResolvedValueOnce({
      rows: [{ tenant_count: 201, active_count: 190, user_count: 2001, admin_count: 201 }],
    });
    const page = JSON.parse(await admin.getTenantStats({ includeTotals: true }));

    expect(mockQuery).toHaveBeenCalledTimes(2);
    expect(String(mockQuery.mock.calls[1][0])).toMatch(
      /COUNT\(\*\) FROM apiome\.tenants t WHERE t\.deleted_at IS NULL/,
    );
    expect(page.totals).toEqual({
      tenant_count: 201,
      active_count: 190,
      user_count: 2001,
      admin_count: 201,
    });
    expect(page.tenants).toHaveLength(1);
  });

  test('getTenantUsers pages one tenant by when each member was added', async () => {
    await admin.getTenantUsers(TENANT, { cursor: encodeTimeIdCursor(STAMP, ID_A), limit: 5 });
    const { sql, params } = onlyCall();

    expect(params).toEqual([TENANT, STAMP, ID_A, 6]);
    expect(sql).toContain('tu.tenant_id = $1 AND u.deleted_at IS NULL');
    expect(sql).toContain(
      "(COALESCE(tu.created_at, 'epoch'::timestamptz), u.id) < ($2::timestamptz, $3::uuid)",
    );
    expect(sql).toContain(
      "ORDER BY COALESCE(tu.created_at, 'epoch'::timestamptz) DESC, u.id DESC LIMIT $4",
    );
  });
});

describe('the sort-key admin lists', () => {
  /** `count` rows shaped like a `(name, id)` page read. */
  const nameRows = (count: number) =>
    Array.from({ length: count }, (_, index) => ({
      id: `id-${index}`,
      name: `User ${index}`,
      cursor_k0: `User ${index}`,
      cursor_k1: `id-${index}`,
    }));

  test('getUsersNotInTenant pages by (name, id) and searches in SQL', async () => {
    mockQuery.mockResolvedValue({ rows: nameRows(3) });
    const page = JSON.parse(
      await admin.getUsersNotInTenant(TENANT, {
        limit: 2,
        cursor: encodeKeyCursor(['Grace', ID_A]),
        search: 'gr',
      }),
    );
    const { sql, params } = onlyCall();

    expect(params).toEqual([TENANT, '%gr%', 'Grace', ID_A, 3]);
    expect(sql).toContain(
      'NOT EXISTS (SELECT 1 FROM apiome.tenant_users tu WHERE tu.tenant_id = $1 AND tu.user_id = u.id)',
    );
    expect(sql).toContain('(u.name ILIKE $2 OR u.email ILIKE $2)');
    expect(sql).toContain('(u.name, u.id) > ($3::text, $4::uuid)');
    expect(sql).toMatch(/ORDER BY u\.name, u\.id LIMIT \$5$/);
    expect(page.users).toEqual([
      { id: 'id-0', name: 'User 0' },
      { id: 'id-1', name: 'User 1' },
    ]);
    expect(decodeKeyCursor(page.nextCursor, 2)).toEqual(['User 1', 'id-1']);
  });

  test('getAllUsersWithLicenses pages by (name, id)', async () => {
    await admin.getAllUsersWithLicenses({ cursor: encodeKeyCursor(['Grace', ID_A]) });
    const { sql, params } = onlyCall();

    expect(params).toEqual(['Grace', ID_A, DEFAULT_LIST_ROWS + 1]);
    expect(sql).toContain('u.deleted_at IS NULL AND (u.name, u.id) > ($1::text, $2::uuid)');
    expect(sql).toMatch(/ORDER BY u\.name, u\.id LIMIT \$3$/);
    expect(sql).not.toMatch(/SELECT \*|\bu\.\*|u\.password/);
  });

  test('getAllUsersWithLicenses counts the licensed users only when asked', async () => {
    mockQuery
      .mockResolvedValueOnce({ rows: nameRows(1) })
      .mockResolvedValueOnce({ rows: [{ assigned_count: 17 }] });
    const page = JSON.parse(await admin.getAllUsersWithLicenses({ includeTotals: true }));

    expect(mockQuery).toHaveBeenCalledTimes(2);
    expect(page.totals).toEqual({ assigned_count: 17 });
  });

  test('getAllPropertyTemplates keeps its order — system first, category, name — as one keyset', async () => {
    await admin.getAllPropertyTemplates({
      cursor: encodeKeyCursor(['false', 'identifiers', 'UUID', ID_B]),
      limit: 20,
    });
    const { sql, params } = onlyCall();

    expect(params).toEqual(['false', 'identifiers', 'UUID', ID_B, 21]);
    expect(sql).toContain(
      '((NOT pt.is_system), pt.category, pt.name, pt.id) > ($1::boolean, $2::text, $3::text, $4::uuid)',
    );
    expect(sql).toMatch(
      /ORDER BY \(NOT pt\.is_system\), pt\.category, pt\.name, pt\.id LIMIT \$5$/,
    );
    expect(sql).not.toMatch(/SELECT \*|\bpt\.\*/);
  });

  test('getAllPropertyTemplates applies the screen filters in SQL', async () => {
    await admin.getAllPropertyTemplates({
      search: 'email',
      category: ' contact ',
      scope: 'tenant',
    });
    const { sql, params } = onlyCall();

    expect(params).toEqual(['contact', '%email%', DEFAULT_LIST_ROWS + 1]);
    expect(sql).toContain('pt.category = $1 AND NOT pt.is_system');
    expect(sql).toContain(
      "(pt.name ILIKE $2 OR pt.description ILIKE $2 OR array_to_string(pt.tags, ' ') ILIKE $2)",
    );

    mockQuery.mockClear();
    await admin.getAllPropertyTemplates({ scope: 'system' });
    expect(onlyCall().sql).toContain('pt.deleted_at IS NULL AND pt.is_system ORDER BY');
  });

  test.each([
    ['getAllUsers', () => admin.getAllUsers({ cursor: 'zzz' })],
    ['getAllTenants', () => admin.getAllTenants({ cursor: encodeKeyCursor(['a', ID_A]) })],
    ['getTenantStats', () => admin.getTenantStats({ cursor: 'zzz' })],
    ['getTenantUsers', () => admin.getTenantUsers(TENANT, { cursor: 'zzz' })],
    [
      'getUsersNotInTenant',
      () => admin.getUsersNotInTenant(TENANT, { cursor: encodeTimeIdCursor(STAMP, ID_A) }),
    ],
    [
      'getAllUsersWithLicenses',
      () => admin.getAllUsersWithLicenses({ cursor: encodeKeyCursor(['a']) }),
    ],
    [
      'getAllPropertyTemplates',
      () => admin.getAllPropertyTemplates({ cursor: encodeKeyCursor(['a', ID_A]) }),
    ],
  ] as const)(
    '%s refuses a cursor it did not issue, without touching the database',
    async (_name, call) => {
      expect(JSON.parse(await call())).toEqual({ success: false, error: 'Invalid cursor' });
      expect(mockQuery).not.toHaveBeenCalled();
    },
  );
});

/* ------------------------------------------------------------------------------------------
   Capped lists and narrow projections
   ------------------------------------------------------------------------------------------ */

describe('lists nothing pages are capped at MAX_UNPAGED_ROWS', () => {
  test.each([
    [
      'getTenantsForUser',
      () => helper.getTenantsForUser('user-1'),
      ['user-1', MAX_UNPAGED_ROWS],
      2,
    ],
    [
      'getTenantsAdministratedByUser',
      () => helper.getTenantsAdministratedByUser('user-1'),
      ['user-1', MAX_UNPAGED_ROWS],
      2,
    ],
    ['getTenantUsers', () => helper.getTenantUsers(TENANT), [TENANT, MAX_UNPAGED_ROWS], 2],
    [
      'getProjectsForTenant',
      () => helper.getProjectsForTenant(TENANT),
      [TENANT, MAX_UNPAGED_ROWS],
      2,
    ],
    [
      'getVersionsForProject',
      () => helper.getVersionsForProject('proj-1'),
      ['proj-1', MAX_UNPAGED_ROWS],
      2,
    ],
    [
      'getApiKeysForTenant',
      () => helper.getApiKeysForTenant(TENANT),
      [TENANT, MAX_UNPAGED_ROWS],
      2,
    ],
    [
      'getTagsForProject',
      () => helper.getTagsForProject('proj-1'),
      ['proj-1', MAX_UNPAGED_ROWS],
      2,
    ],
  ] as const)('%s', async (_name, call, params, placeholder) => {
    await call();
    const read = onlyCall();
    expect(read.params).toEqual(params);
    expect(read.sql).toMatch(new RegExp(`LIMIT \\$${placeholder}$`));
    expect(read.sql).not.toMatch(/SELECT \*|\b[a-z]\.\*/);
  });

  test.each([
    ['listVersionBranches', () => helper.listVersionBranches('proj-1', TENANT)],
    ['listVersionTags', () => helper.listVersionTags('proj-1', TENANT)],
  ] as const)('%s', async (_name, call) => {
    mockQuery.mockResolvedValue({ rows: [{ '?column?': 1 }], rowCount: 1 });
    await call();
    const [sql, params] = mockQuery.mock.calls[1];
    expect(params).toEqual(['proj-1', TENANT, MAX_UNPAGED_ROWS]);
    expect(String(sql).trim()).toMatch(/LIMIT \$3$/);
  });
});

describe('narrow projections', () => {
  test('a version row never carries its search columns', async () => {
    await helper.getVersionsForProject('proj-1');
    const { sql } = onlyCall();
    expect(sql).toContain('v.id, v.project_id, v.creator_id, v.version_id');
    expect(sql).not.toMatch(/mcp_public_embedding|mcp_public_doc_tsv/);
  });

  test('a tenant row is the eight columns TenantRecord declares', async () => {
    await helper.getTenantsForUser('user-1');
    expect(onlyCall().sql).toContain(
      'SELECT DISTINCT a.id, a.name, a.description, a.slug, a.enabled, a.deleted_at, a.created_at, a.updated_at FROM',
    );
  });

  test('an API key row never carries the stored hash', async () => {
    await helper.getApiKeysForTenant(TENANT);
    const { sql } = onlyCall();
    expect(sql).toContain('SELECT id, tenant_id, name, description, key_prefix, scopes');
    expect(sql).not.toMatch(/key_hash/);
  });
});
