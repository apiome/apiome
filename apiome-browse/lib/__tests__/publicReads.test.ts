/**
 * The lean public reads (DBP-1.27, #7210): what the identity, project, version, product and MCP
 * statements read, and how their rows are shaped. The pool is a recorder; `routeBudget.test.ts`
 * counts the statements per route and `apiome-db plan-check` checks their plans.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { query, fetchRegistryServers } = vi.hoisted(() => ({ query: vi.fn(), fetchRegistryServers: vi.fn() }));

vi.mock('../db/db', () => ({ default: { query } }));

vi.mock('../mcp/registrySearch', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../mcp/registrySearch')>()),
  fetchRegistryServers,
}));

import {
  getPublicMcpCollection,
  getPublicMcpEndpointDetail,
  getPublicMcpEndpointsByHost,
  getPublicProjectsForTenant,
  searchRegistryForPublicCatalog,
} from '../db/helper';
import { getPublicProjectIdentity, getPublicTenantIdentity } from '../db/identity';
import { getPortalProduct } from '../db/products';
import { getTryItVersion, clearTryItCache } from '../db/tryIt';
import { VERSION_LIST_LIMIT, getPublicProjectWithFacts, getPublicVersionPage, listProjectVersions, listVersionLabels } from '../db/versions';
import { MCP_INDEX_PAGE_SIZE } from '../mcpSort';
import { MEMBER_PUBLIC_VERSIONS_SQL, MEMBER_VERSION_SCAN_LIMIT } from '../products/sql';

/** The SQL text of the nth recorded call. */
function textOf(n = 0): string {
  const first = query.mock.calls[n][0];
  return typeof first === 'string' ? first : (first as { text: string }).text;
}

/** The parameters of the nth recorded call. */
function valuesOf(n = 0): unknown[] {
  return query.mock.calls[n][1] as unknown[];
}

beforeEach(() => {
  query.mockReset();
  query.mockResolvedValue({ rows: [] });
  fetchRegistryServers.mockReset();
  clearTryItCache();
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});

describe('identity lookups', () => {
  it('find a public organization with an EXISTS probe, not a DISTINCT over its versions', async () => {
    query.mockResolvedValue({ rows: [{ id: 't1', name: 'Acme', slug: 'acme' }] });
    expect(await getPublicTenantIdentity('acme')).toMatchObject({ name: 'Acme' });
    const text = textOf();
    expect(valuesOf()).toEqual(['acme']);
    expect(text).toContain('AND EXISTS (SELECT 1 FROM apiome.browse_public_projects b WHERE b.tenant_id = t.id)');
    expect(text).toContain('t.deleted_at IS NULL');
    expect(text).not.toContain('DISTINCT');
    expect(text).not.toContain('apiome.versions');
  });

  it('find a public project through its summary row, without card facts', async () => {
    query.mockResolvedValue({ rows: [{ id: 'p1', name: 'Payments', version_count: 4 }] });
    expect(await getPublicProjectIdentity('acme', 'payments')).toMatchObject({ version_count: 4 });
    const text = textOf();
    expect(valuesOf()).toEqual(['acme', 'payments']);
    expect(text).toContain('JOIN apiome.browse_public_projects b ON b.project_id = p.id');
    expect(text).toContain('t.deleted_at IS NULL');
    expect(text).toContain('p.deleted_at IS NULL');
    for (const heavy of ['sdk_generation_settings', 'path_operation', 'apiome.classes', 'apiome.versions']) {
      expect(text).not.toContain(heavy);
    }
  });

  it('answer null for something that is not public', async () => {
    expect(await getPublicTenantIdentity('nope')).toBeNull();
    expect(await getPublicProjectIdentity('acme', 'nope')).toBeNull();
  });
});

describe('project and version reads', () => {
  it('read a project\'s facts from the version its summary row names', async () => {
    await getPublicProjectWithFacts('acme', 'payments');
    const text = textOf();
    expect(text).toContain('f_v.id = b.latest_version_id');
    expect(text).toContain('b.version_count');
    // No search for the latest version: no ORDER BY … LIMIT 1 over the project's versions.
    expect(text).not.toMatch(/ORDER BY [a-z_]+\.published_at DESC NULLS LAST, [a-z_]+\.created_at DESC\s+LIMIT 1/);
  });

  it('list an organization\'s projects from the summary table', async () => {
    await getPublicProjectsForTenant('acme');
    const text = textOf();
    expect(text).toContain('JOIN apiome.browse_public_projects b ON b.tenant_id = t.id');
    expect(text).toContain('b.protocols, b.formats');
    expect(text).toContain('f_v.id = b.latest_version_id');
    expect(text).not.toContain('GROUP BY');
  });

  it('list a bounded number of versions, with the severity and no changelog payload', async () => {
    await listProjectVersions('p1');
    expect(valuesOf()).toEqual(['p1', VERSION_LIST_LIMIT]);
    expect(textOf()).toContain('vc.max_severity');
    expect(textOf()).not.toContain('changelog_json');
    expect(textOf()).toMatch(/ORDER BY v\.created_at DESC\s+LIMIT \$2/);

    await listVersionLabels('p1', 5);
    expect(valuesOf(1)).toEqual(['p1', 5]);
    expect(textOf(1)).toContain('SELECT v.id, v.version_id');
    expect(textOf(1)).not.toContain('description');
  });

  it('split the version page\'s one row into the version, the sidebar and the changelog', async () => {
    query.mockResolvedValue({
      rows: [
        {
          id: 'v1',
          version_id: '2.0.0',
          mock_enabled: true,
          project_name: 'Payments',
          operation_count: 12,
          published_at: new Date('2026-11-02T12:00:00Z'),
          published_revision_id: 'v1',
          version_label: '2.0.0',
          baseline_version_label: '1.0.0',
          max_severity: 'breaking',
          status: 'ready',
          changelog_json: { counts: { total: 3 }, fromVersion: '1.0.0', toVersion: '2.0.0' },
          sidebar_versions: [
            { id: 'v1', version_id: '2.0.0' },
            { id: 'v0', version_id: '1.0.0' },
          ],
        },
      ],
    });
    const page = await getPublicVersionPage('acme', 'payments', '2.0.0', false);
    expect(valuesOf()).toEqual(['acme', 'payments', '2.0.0', false]);
    expect(page?.version).toMatchObject({ id: 'v1', version_id: '2.0.0', mock_enabled: true, operation_count: 12 });
    // The changelog's columns are not left on the version row…
    expect(page?.version).not.toHaveProperty('changelog_json');
    expect(page?.version).not.toHaveProperty('sidebar_versions');
    expect(page?.version).not.toHaveProperty('status');
    // …they are the changelog row: its summary, without entries.
    expect(page?.changelog).toMatchObject({
      versionLabel: '2.0.0',
      baselineVersionLabel: '1.0.0',
      maxSeverity: 'breaking',
      status: 'ready',
      entriesOmitted: true,
    });
    expect(page?.changelog.changelog?.counts.total).toBe(3);
    expect(page?.versions).toEqual([
      { id: 'v1', version_id: '2.0.0' },
      { id: 'v0', version_id: '1.0.0' },
    ]);
  });

  it('bound the sidebar list and read three fields of each sibling version', async () => {
    await getPublicVersionPage('acme', 'payments', '2.0.0', true);
    const text = textOf();
    expect(text).toContain("json_build_object('id', s.id, 'version_id', s.version_id)");
    expect(text).toContain(`LIMIT ${VERSION_LIST_LIMIT}) s) AS sidebar_versions`);
    expect(text).toContain("AND sv.visibility = 'public'");
    expect(valuesOf()[3]).toBe(true);
  });

  it('read the Try It policy inputs and nothing else', async () => {
    query.mockResolvedValue({ rows: [{ version_id: '2.0.0', mock_enabled: true, servers: [{ url: 'https://api.acme.test', variables: null }] }] });
    const version = await getTryItVersion('acme', 'payments', '2.0.0');
    expect(version?.servers).toEqual([{ url: 'https://api.acme.test', variables: null }]);
    const text = textOf();
    expect(text).toContain('FROM apiome.version_server vs');
    expect(text).toContain('ORDER BY vs.sort_order, vs.url');
    expect(text).toContain("AND v.visibility = 'public'");
    for (const heavy of ['sdk_generation_settings', 'path_operation', 'apiome.classes']) expect(text).not.toContain(heavy);
  });

  it('remember an unknown version too, so a refused relay is not a statement per request', async () => {
    expect(await getTryItVersion('acme', 'payments', '9.9.9')).toBeNull();
    expect(await getTryItVersion('acme', 'payments', '9.9.9')).toBeNull();
    expect(query).toHaveBeenCalledTimes(1);
    // Another version is another lookup.
    await getTryItVersion('acme', 'payments', '2.0.0');
    expect(query).toHaveBeenCalledTimes(2);
  });
});

describe('product members', () => {
  it('reads one label for a latest member and a bounded list for a pinned one', async () => {
    query
      .mockResolvedValueOnce({ rows: [{ id: 'prod', tenant_id: 't1', slug: 'gold', name: 'Gold', state: 'published', tenant_slug: 'acme', tenant_name: 'Acme' }] })
      .mockResolvedValueOnce({
        rows: [
          { kind: 'project_latest', ref: 'p1', name: 'Payments', project_slug: 'payments', mcp_slug: null, version_selector: null, environment: null, mcp_public: false },
          { kind: 'project_version', ref: 'p2', name: 'Orders', project_slug: 'orders', mcp_slug: null, version_selector: '1.x', environment: null, mcp_public: false },
          { kind: 'project_version', ref: 'p1', name: 'Payments', project_slug: 'payments', mcp_slug: null, version_selector: '2.x', environment: null, mcp_public: false },
          { kind: 'mcp_server', ref: 'e1', name: 'Docs', project_slug: null, mcp_slug: 'docs', version_selector: null, environment: null, mcp_public: true },
        ],
      })
      .mockResolvedValueOnce({ rows: [] })
      .mockResolvedValueOnce({ rows: [{ project_id: 'p1', label: '2.1.0' }] });
    const product = await getPortalProduct('acme', 'gold');
    expect(product?.members).toHaveLength(4);
    expect(query).toHaveBeenCalledTimes(4);
    expect(textOf(3)).toBe(MEMBER_PUBLIC_VERSIONS_SQL);
    // p1 is both a latest and a pinned member: the larger need wins. The MCP server needs none.
    expect(valuesOf(3)).toEqual([
      ['p1', 'p2'],
      [MEMBER_VERSION_SCAN_LIMIT, MEMBER_VERSION_SCAN_LIMIT],
    ]);
  });

  it('asks for a single label when every member follows the latest version', async () => {
    query
      .mockResolvedValueOnce({ rows: [{ id: 'prod', tenant_id: 't1', slug: 'gold', name: 'Gold', state: 'published', tenant_slug: 'acme', tenant_name: 'Acme' }] })
      .mockResolvedValueOnce({ rows: [{ kind: 'project_latest', ref: 'p1', name: 'Payments', project_slug: 'payments', mcp_slug: null, version_selector: null, environment: null, mcp_public: false }] })
      .mockResolvedValueOnce({ rows: [] })
      .mockResolvedValueOnce({ rows: [{ project_id: 'p1', label: '2.1.0' }] });
    const product = await getPortalProduct('acme', 'gold');
    expect(valuesOf(3)).toEqual([['p1'], [1]]);
    expect(product?.members[0]).toMatchObject({ versionLabel: '2.1.0', href: '/tenant/acme/payments/2.1.0' });
  });

  it('skips the versions statement for a product of MCP servers only', async () => {
    query
      .mockResolvedValueOnce({ rows: [{ id: 'prod', tenant_id: 't1', slug: 'gold', name: 'Gold', state: 'published', tenant_slug: 'acme', tenant_name: 'Acme' }] })
      .mockResolvedValueOnce({ rows: [{ kind: 'mcp_server', ref: 'e1', name: 'Docs', project_slug: null, mcp_slug: 'docs', version_selector: null, environment: null, mcp_public: true }] })
      .mockResolvedValueOnce({ rows: [] });
    await getPortalProduct('acme', 'gold');
    expect(query).toHaveBeenCalledTimes(3);
  });

  it('bounds the versions read per project in SQL', () => {
    expect(MEMBER_PUBLIC_VERSIONS_SQL).toContain('FROM unnest($1::uuid[], $2::int[]) AS m(project_id, wanted)');
    expect(MEMBER_PUBLIC_VERSIONS_SQL).toContain('LIMIT m.wanted');
    expect(MEMBER_PUBLIC_VERSIONS_SQL).not.toContain('= ANY($1::uuid[])');
  });
});

/** An endpoint row of the MCP index statement. */
function endpoint(id: string, host: string | null, extra: Record<string, unknown> = {}) {
  return { id, host, name: id, slug: id, current_version_id: `snap-${id}`, total_endpoints: 250, total_hosts: 40, tool_count: 2, ...extra };
}

describe('public MCP reads', () => {
  it('pages the index and counts capabilities for the page only', async () => {
    query.mockResolvedValue({ rows: [endpoint('a', 'a.example.com'), endpoint('b', 'a.example.com'), endpoint('c', null)] });
    const index = await getPublicMcpEndpointsByHost(2);
    expect(valuesOf()).toEqual([MCP_INDEX_PAGE_SIZE, MCP_INDEX_PAGE_SIZE]);
    expect(index).toMatchObject({ page: 2, pageSize: MCP_INDEX_PAGE_SIZE, totalEndpoints: 250, totalHosts: 40, hasNext: true });
    expect(index.groups.map((g) => [g.host, g.endpoints.length])).toEqual([
      ['a.example.com', 2],
      ['Unknown host', 1],
    ]);
    // The totals are not left on the endpoint rows.
    expect(index.groups[0].endpoints[0]).not.toHaveProperty('total_endpoints');

    const text = textOf();
    expect(text).toContain('FROM apiome.mcp_v_public_endpoints e');
    expect(text).toContain('LIMIT $1 OFFSET $2');
    expect(text).toContain('WHERE ci.version_id = pg.current_version_id');
    expect(text).not.toContain('GROUP BY e.id');
    expect(text).toContain('ORDER BY host ASC NULLS LAST, grade ASC NULLS LAST, score DESC NULLS LAST, name ASC, id');
  });

  it('treats a page number that is not one as the first page, and knows the last page', async () => {
    query.mockResolvedValue({ rows: [endpoint('a', 'a.example.com', { total_endpoints: 1, total_hosts: 1 })] });
    for (const page of [0, -3, 1.5, Number.NaN]) {
      const index = await getPublicMcpEndpointsByHost(page);
      expect(index.page).toBe(1);
      expect(index.hasNext).toBe(false);
    }
    expect(valuesOf()).toEqual([MCP_INDEX_PAGE_SIZE, 0]);
  });

  it('is an empty index, with zero totals, when nothing is public', async () => {
    expect(await getPublicMcpEndpointsByHost()).toEqual({
      groups: [],
      page: 1,
      pageSize: MCP_INDEX_PAGE_SIZE,
      totalEndpoints: 0,
      totalHosts: 0,
      hasNext: false,
    });
  });

  it('counts an endpoint\'s capabilities from the items it lists, reading them once', async () => {
    query
      .mockResolvedValueOnce({ rows: [{ id: 'e1', name: 'Docs', current_version_id: 'snap-1' }] })
      .mockResolvedValueOnce({
        rows: [
          { id: 'i1', item_type: 'tool' },
          { id: 'i2', item_type: 'tool' },
          { id: 'i3', item_type: 'resource' },
          { id: 'i4', item_type: 'prompt' },
        ],
      });
    const detail = await getPublicMcpEndpointDetail('acme', 'docs');
    expect(detail?.endpoint).toMatchObject({ tool_count: 2, resource_count: 1, resource_template_count: 0, prompt_count: 1 });
    expect(detail?.items).toHaveLength(4);
    expect(query).toHaveBeenCalledTimes(2);
    expect(textOf(0)).not.toContain('mcp_capability_items');
    expect(valuesOf(1)).toEqual(['snap-1']);
  });

  it('reads no items for an endpoint that was never discovered', async () => {
    query.mockResolvedValueOnce({ rows: [{ id: 'e1', name: 'Docs', current_version_id: null }] });
    const detail = await getPublicMcpEndpointDetail('acme', 'docs');
    expect(detail?.endpoint.tool_count).toBe(0);
    expect(detail?.items).toEqual([]);
    expect(query).toHaveBeenCalledTimes(1);
  });

  it('lists a collection\'s public endpoints with per-endpoint counts, not a GROUP BY', async () => {
    query.mockResolvedValueOnce({ rows: [{ id: 'c1', name: 'Starter', tenant_slug: 'acme' }] }).mockResolvedValueOnce({ rows: [endpoint('a', 'a.example.com')] });
    const collection = await getPublicMcpCollection('acme', 'starter');
    expect(collection?.endpoints).toHaveLength(1);
    expect(valuesOf(1)).toEqual(['c1']);
    expect(textOf(1)).toContain('JOIN apiome.mcp_v_public_endpoints e ON e.id = m.endpoint_id AND e.tenant_id = m.tenant_id');
    expect(textOf(1)).toContain('WHERE ci.version_id = e.current_version_id');
    expect(textOf(1)).not.toContain('GROUP BY');
  });

  it('de-duplicates registry entries with three index probes joined by UNION', async () => {
    fetchRegistryServers.mockResolvedValue([
      { source: 'registry', serverName: 'io.github.Acme/Weather', title: null, description: null, version: null, status: 'active', websiteUrl: null, remoteUrl: 'https://mcp.acme.test/mcp', transport: 'streamable_http', host: 'mcp.acme.test', remoteKeys: ['https://mcp.acme.test/mcp'] },
    ]);
    const result = await searchRegistryForPublicCatalog('weather', ['00000000-0000-0000-0000-000000000001']);
    expect(result.included).toBe(true);
    const text = textOf();
    expect(valuesOf()).toEqual([['io.github.acme/weather'], ['mcp.acme.test'], ['00000000-0000-0000-0000-000000000001']]);
    expect(text.match(/\bUNION\b/g)).toHaveLength(2);
    expect(text).not.toMatch(/\)\s+OR\s+lower/);
    expect(text).toContain("lower(n.registry_metadata->>'serverName') = ANY($1::text[])");
    expect(text).toContain('lower(h.host) = ANY($2::text[])');
    expect(text).toContain('i.id = ANY($3::uuid[])');
    // Every probe applies the public view's predicates, as the V431 partial indexes state them.
    for (const alias of ['n', 'h', 'i']) {
      expect(text).toContain(
        `${alias}.deleted_at IS NULL AND ${alias}.enabled IS TRUE AND ${alias}.published IS TRUE`
      );
      expect(text).toContain(`${alias}.visibility = 'public'::apiome.visibility_type`);
    }
  });
});
