/**
 * Anchor label resolution for the Project Discussion panel (COL-1.3, #4515) —
 * `lib/db/comment-anchor-labels.ts`.
 *
 * Drives the resolver with an injected query runner, so it needs no database, and pins what
 * matters: every query is bound to the caller's tenant and the URL's project, only UUID ids reach
 * SQL, and labels are spelled the way apiome-db's V260 orphan triggers spell `anchor_label`.
 */

import {
  CLASS_LABEL_SQL,
  CLASS_PROPERTY_LABEL_SQL,
  LIBRARY_PROPERTY_LABEL_SQL,
  OPERATION_LABEL_SQL,
  PATH_LABEL_SQL,
  resolveCommentAnchorContexts,
  type AnchorLabelQuery,
  type AnchorRef,
} from '../lib/db/comment-anchor-labels';

const TENANT = '550e8400-e29b-41d4-a716-446655440000';
const PROJECT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const CLASS_ID = '11111111-1111-4111-8111-111111111111';
const PROPERTY_ID = '22222222-2222-4222-8222-222222222222';
const LIBRARY_ID = '33333333-3333-4333-8333-333333333333';
const PATH_ID = '44444444-4444-4444-8444-444444444444';
const OPERATION_ID = '55555555-5555-4555-8555-555555555555';

const ALL_SQL = [CLASS_LABEL_SQL, CLASS_PROPERTY_LABEL_SQL, LIBRARY_PROPERTY_LABEL_SQL, PATH_LABEL_SQL, OPERATION_LABEL_SQL];

/**
 * A query runner that answers each statement with fixed rows and records its calls.
 *
 * @param rowsBySql - Rows to return per statement.
 * @returns The runner and its recorded calls.
 */
function runner(rowsBySql: Map<string, Array<Record<string, unknown>>> = new Map()) {
  const calls: Array<{ sql: string; params: unknown[] }> = [];
  const query: AnchorLabelQuery = async (sql, params) => {
    calls.push({ sql, params });
    return { rows: rowsBySql.get(sql) ?? [] };
  };
  return { query, calls };
}

describe('SQL scoping', () => {
  it.each(ALL_SQL.map((sql, index) => [index, sql]))('statement %i is bound to the tenant and project', (_i, sql) => {
    const text = String(sql);
    expect(text).toContain('p.tenant_id::text = $1');
    expect(text).toContain('(p.id::text = $2 OR p.slug = $2)');
    expect(text).toMatch(/= ANY\(\$3::uuid\[\]\)/);
    expect(text).not.toContain('{versionColumn}');
  });

  it('reaches classes, paths and operations through their version and project', () => {
    expect(CLASS_LABEL_SQL).toContain('JOIN apiome.versions v ON v.id = c.version_id');
    expect(PATH_LABEL_SQL).toContain('JOIN apiome.versions v ON v.id = vp.version_id');
    expect(OPERATION_LABEL_SQL).toContain('JOIN apiome.version_path vp ON vp.id = po.version_path_id');
    expect(LIBRARY_PROPERTY_LABEL_SQL).toContain('JOIN apiome.projects p ON p.id = pr.project_id');
  });
});

describe('resolveCommentAnchorContexts', () => {
  it('queries nothing without anchors, or without a scope', async () => {
    const { query, calls } = runner();
    expect((await resolveCommentAnchorContexts({ tenantId: TENANT, projectRef: PROJECT }, [], query)).size).toBe(0);
    const anchors: AnchorRef[] = [{ anchor_type: 'class', anchor_id: CLASS_ID }];
    expect((await resolveCommentAnchorContexts({ tenantId: '', projectRef: PROJECT }, anchors, query)).size).toBe(0);
    expect((await resolveCommentAnchorContexts({ tenantId: TENANT, projectRef: '' }, anchors, query)).size).toBe(0);
    expect(calls).toHaveLength(0);
  });

  it('skips version anchors and ids that are not UUIDs', async () => {
    const { query, calls } = runner();
    await resolveCommentAnchorContexts(
      { tenantId: TENANT, projectRef: PROJECT },
      [
        { anchor_type: 'version', anchor_id: CLASS_ID },
        { anchor_type: 'class', anchor_id: "1' OR '1'='1" },
        { anchor_type: 'path', anchor_id: 'not-a-uuid' },
      ],
      query
    );
    expect(calls).toHaveLength(0);
  });

  it('binds tenant, project and the de-duplicated ids of one kind', async () => {
    const { query, calls } = runner();
    await resolveCommentAnchorContexts(
      { tenantId: TENANT, projectRef: 'pets' },
      [
        { anchor_type: 'class', anchor_id: CLASS_ID },
        { anchor_type: 'class', anchor_id: CLASS_ID.toUpperCase() },
      ],
      query
    );
    expect(calls).toEqual([{ sql: CLASS_LABEL_SQL, params: [TENANT, 'pets', [CLASS_ID]] }]);
  });

  it('asks both property tables for a property id', async () => {
    const { query, calls } = runner();
    await resolveCommentAnchorContexts(
      { tenantId: TENANT, projectRef: PROJECT },
      [{ anchor_type: 'property', anchor_id: PROPERTY_ID }],
      query
    );
    expect(calls.map((call) => call.sql).sort()).toEqual([CLASS_PROPERTY_LABEL_SQL, LIBRARY_PROPERTY_LABEL_SQL].sort());
  });

  it('labels every kind the way V260 does', async () => {
    const { query } = runner(
      new Map([
        [CLASS_LABEL_SQL, [{ id: CLASS_ID, class_name: 'Customer' }]],
        [CLASS_PROPERTY_LABEL_SQL, [{ id: PROPERTY_ID, property_name: 'email', class_name: 'Customer' }]],
        [LIBRARY_PROPERTY_LABEL_SQL, [{ id: LIBRARY_ID, property_name: 'createdAt' }]],
        [PATH_LABEL_SQL, [{ id: PATH_ID, pathname: '/customers/{id}' }]],
        [OPERATION_LABEL_SQL, [{ id: OPERATION_ID, method: 'get', pathname: '/customers/{id}' }]],
      ])
    );
    const contexts = await resolveCommentAnchorContexts(
      { tenantId: TENANT, projectRef: PROJECT },
      [
        { anchor_type: 'class', anchor_id: CLASS_ID },
        { anchor_type: 'property', anchor_id: PROPERTY_ID },
        { anchor_type: 'property', anchor_id: LIBRARY_ID },
        { anchor_type: 'path', anchor_id: PATH_ID },
        { anchor_type: 'operation', anchor_id: OPERATION_ID },
      ],
      query
    );
    expect(contexts.get(`class:${CLASS_ID}`)).toEqual({ label: 'Customer', className: 'Customer' });
    expect(contexts.get(`property:${PROPERTY_ID}`)).toEqual({
      label: 'Customer.email',
      className: 'Customer',
      propertyName: 'email',
    });
    expect(contexts.get(`property:${LIBRARY_ID}`)).toEqual({
      label: 'createdAt',
      className: null,
      propertyName: 'createdAt',
    });
    expect(contexts.get(`path:${PATH_ID}`)).toEqual({ label: '/customers/{id}', pathname: '/customers/{id}' });
    expect(contexts.get(`operation:${OPERATION_ID}`)).toEqual({
      label: 'GET /customers/{id}',
      method: 'get',
      pathname: '/customers/{id}',
    });
  });

  it('prefers the class property when both tables answer for one id', async () => {
    const { query } = runner(
      new Map([
        [CLASS_PROPERTY_LABEL_SQL, [{ id: PROPERTY_ID, property_name: 'email', class_name: 'Customer' }]],
        [LIBRARY_PROPERTY_LABEL_SQL, [{ id: PROPERTY_ID, property_name: 'email' }]],
      ])
    );
    const contexts = await resolveCommentAnchorContexts(
      { tenantId: TENANT, projectRef: PROJECT },
      [{ anchor_type: 'property', anchor_id: PROPERTY_ID }],
      query
    );
    expect(contexts.get(`property:${PROPERTY_ID}`)?.label).toBe('Customer.email');
  });

  it('leaves out elements that no longer exist or have unusable rows', async () => {
    const { query } = runner(
      new Map([
        [CLASS_LABEL_SQL, [{ id: CLASS_ID, class_name: null }]],
        [OPERATION_LABEL_SQL, [{ id: OPERATION_ID, method: 'GET', pathname: '' }]],
      ])
    );
    const contexts = await resolveCommentAnchorContexts(
      { tenantId: TENANT, projectRef: PROJECT },
      [
        { anchor_type: 'class', anchor_id: CLASS_ID },
        { anchor_type: 'operation', anchor_id: OPERATION_ID },
        { anchor_type: 'path', anchor_id: PATH_ID },
      ],
      query
    );
    expect(contexts.size).toBe(0);
  });

  it('propagates a query failure to the caller', async () => {
    const failing: AnchorLabelQuery = async () => {
      throw new Error('connection refused');
    };
    await expect(
      resolveCommentAnchorContexts(
        { tenantId: TENANT, projectRef: PROJECT },
        [{ anchor_type: 'class', anchor_id: CLASS_ID }],
        failing
      )
    ).rejects.toThrow('connection refused');
  });
});
