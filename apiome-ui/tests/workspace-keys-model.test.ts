/**
 * The one list of keys — `components/ade/apiKeys/workspaceKeysModel`.
 *
 * REST API keys and MCP server keys share one table on the API keys page. What this pins:
 *
 *   1. Both lists merge newest first, with ids that cannot collide across the two tables.
 *   2. One status vocabulary covers both: Disabled is REST-only, Revoked is MCP-only.
 *   3. Search, the Type filter, the status chips, sorting and the foot work across both kinds.
 *   4. Regenerate is offered on every live key, and refused — with a reason — on expired keys
 *      and revoked MCP keys.
 */

import type { McpApiKeyMetadata } from '../src/app/ade/dashboard/tenants/mcpKeysApi';
import type { ApiKeyRecord } from '../src/app/components/ade/apiKeys/apiKeysModel';
import {
  describeRegeneratedKey,
  describeWorkspaceKeyAccess,
  describeWorkspaceKeyBreakdown,
  matchesWorkspaceKeyFacet,
  matchesWorkspaceKeyType,
  searchWorkspaceKeys,
  sortWorkspaceKeys,
  toWorkspaceKeyRows,
  visibleWorkspaceKeyFacets,
  workspaceKeyFacetCounts,
  workspaceKeyName,
  workspaceKeyPrefix,
  workspaceKeyRegeneration,
  workspaceKeyRowId,
  workspaceKeyStatus,
  type WorkspaceKeyRow,
} from '../src/app/components/ade/apiKeys/workspaceKeysModel';

/** The moment every test judges against. */
const NOW = new Date('2026-08-17T12:00:00Z');

function restKey(over: Partial<ApiKeyRecord> = {}): ApiKeyRecord {
  return {
    id: 'k-1',
    tenant_id: 't-1',
    name: 'CI contract gate',
    description: 'Blocks merges on breaking classified diffs.',
    key_prefix: 'sk_9f31c2Qm...',
    scopes: ['diff:read'],
    last_used_at: '2026-08-15T08:02:00Z',
    expires_at: null,
    enabled: true,
    created_at: '2026-07-02T10:14:00Z',
    updated_at: '2026-07-02T10:14:00Z',
    ...over,
  };
}

function mcpKey(over: Partial<McpApiKeyMetadata> = {}): McpApiKeyMetadata {
  return {
    id: 'm-1',
    prefix: 'aB3dE5gH7jK9...',
    label: 'Claude Desktop',
    scope_json: { tenants: [], projects: [] },
    capability_mode: 'inherit',
    enabled_tools: [],
    created_at: '2026-08-01T10:00:00Z',
    expires_at: null,
    revoked_at: null,
    last_used_at: null,
    ...over,
  };
}

/** Four REST keys covering every REST status, and two MCP keys — one live, one revoked. */
const REST: ApiKeyRecord[] = [
  restKey({ id: 'k-active', name: 'CI contract gate', expires_at: '2027-01-02T00:00:00Z' }),
  restKey({
    id: 'k-disabled',
    name: 'Nightly lint',
    scopes: ['lint:read'],
    enabled: false,
    key_prefix: 'sk_2ab7e0Zz...',
    created_at: '2026-06-01T00:00:00Z',
  }),
  restKey({
    id: 'k-expired',
    name: 'Partner sync',
    scopes: ['*'],
    expires_at: '2026-08-01T00:00:00Z',
    key_prefix: 'sk_c41d88Aa...',
    created_at: '2026-05-01T00:00:00Z',
  }),
  restKey({
    id: 'k-both',
    name: 'Terraform',
    scopes: ['diff:read', 'lint:read'],
    last_used_at: null,
    expires_at: '2026-11-12T00:00:00Z',
    key_prefix: 'sk_77e0a1Bb...',
    created_at: '2026-04-01T00:00:00Z',
  }),
];
const MCP: McpApiKeyMetadata[] = [
  mcpKey({ id: 'm-claude' }),
  mcpKey({
    id: 'm-cursor',
    label: 'Cursor',
    prefix: 'zZ9yY8xX7wW6...',
    capability_mode: 'explicit',
    enabled_tools: ['spec_list', 'spec_describe'],
    revoked_at: '2026-08-10T00:00:00Z',
    created_at: '2026-03-01T00:00:00Z',
  }),
];
const ROWS = toWorkspaceKeyRows(REST, MCP);

const ids = (rows: readonly WorkspaceKeyRow[]) => rows.map(workspaceKeyRowId);

describe('merging the two lists', () => {
  it('puts every key in one list, newest first', () => {
    expect(ids(ROWS)).toEqual([
      'mcp:m-claude',
      'rest:k-active',
      'rest:k-disabled',
      'rest:k-expired',
      'rest:k-both',
      'mcp:m-cursor',
    ]);
  });

  it('keeps ids apart when both tables use the same id', () => {
    const rows = toWorkspaceKeyRows([restKey({ id: 'same' })], [mcpKey({ id: 'same' })]);
    expect(new Set(ids(rows)).size).toBe(2);
  });

  it('reads a REST name and an MCP label as the name, and each table’s prefix', () => {
    const [mcp, rest] = ROWS;
    expect([workspaceKeyName(mcp), workspaceKeyPrefix(mcp)]).toEqual(['Claude Desktop', 'aB3dE5gH7jK9...']);
    expect([workspaceKeyName(rest), workspaceKeyPrefix(rest)]).toEqual(['CI contract gate', 'sk_9f31c2Qm...']);
  });
});

describe('status and access', () => {
  it('uses one vocabulary for both kinds', () => {
    expect(ROWS.map((row) => workspaceKeyStatus(row, NOW))).toEqual([
      'active',
      'active',
      'disabled',
      'expired',
      'active',
      'revoked',
    ]);
  });

  it('says what each kind may reach', () => {
    const access = Object.fromEntries(ROWS.map((row) => [row.key.id, describeWorkspaceKeyAccess(row)]));
    expect(access['k-expired']).toBe('Full access');
    expect(access['k-both']).toBe('diff:read, lint:read');
    expect(access['m-claude']).toBe('Workspace defaults');
    expect(access['m-cursor']).toBe('Custom · 2 tools');
  });
});

describe('searching and filtering', () => {
  it('matches a REST name, an MCP label and a prefix pasted with its ellipsis', () => {
    expect(ids(searchWorkspaceKeys(ROWS, 'terraform'))).toEqual(['rest:k-both']);
    expect(ids(searchWorkspaceKeys(ROWS, 'cursor'))).toEqual(['mcp:m-cursor']);
    expect(ids(searchWorkspaceKeys(ROWS, 'sk_c41d88…'))).toEqual(['rest:k-expired']);
    expect(ids(searchWorkspaceKeys(ROWS, 'aB3dE5'))).toEqual(['mcp:m-claude']);
  });

  it('returns everything for a blank query, without aliasing the input', () => {
    const all = searchWorkspaceKeys(ROWS, '   ');
    expect(all).toHaveLength(ROWS.length);
    expect(all).not.toBe(ROWS);
  });

  it('narrows to one kind with the Type filter', () => {
    expect(ROWS.filter((row) => matchesWorkspaceKeyType(row, 'mcp')).map((row) => row.key.id)).toEqual([
      'm-claude',
      'm-cursor',
    ]);
    expect(ROWS.filter((row) => matchesWorkspaceKeyType(row, 'rest'))).toHaveLength(4);
    expect(ROWS.filter((row) => matchesWorkspaceKeyType(row, 'all'))).toHaveLength(6);
  });

  it('counts every status chip, with All as the total', () => {
    expect(workspaceKeyFacetCounts(ROWS, NOW)).toEqual({
      all: 6,
      active: 3,
      disabled: 1,
      expired: 1,
      revoked: 1,
    });
    expect(ids(ROWS.filter((row) => matchesWorkspaceKeyFacet(row, 'revoked', NOW)))).toEqual([
      'mcp:m-cursor',
    ]);
  });

  it('draws only the chips some key is in, plus All, Active and the chip in use', () => {
    const restOnly = workspaceKeyFacetCounts(toWorkspaceKeyRows(REST, []), NOW);
    expect(visibleWorkspaceKeyFacets(restOnly, 'all')).toEqual(['all', 'active', 'disabled', 'expired']);
    const empty = workspaceKeyFacetCounts([], NOW);
    expect(visibleWorkspaceKeyFacets(empty, 'all')).toEqual(['all', 'active']);
    expect(visibleWorkspaceKeyFacets(empty, 'revoked')).toEqual(['all', 'active', 'revoked']);
  });
});

describe('sorting', () => {
  it('leaves newest first alone when nothing is sorted', () => {
    expect(ids(sortWorkspaceKeys(ROWS, null, NOW))).toEqual(ids(ROWS));
  });

  it('sorts names across both kinds, case-insensitively', () => {
    const sorted = sortWorkspaceKeys(ROWS, { column: 'name', direction: 'asc' }, NOW);
    expect(sorted.map(workspaceKeyName)).toEqual([
      'CI contract gate',
      'Claude Desktop',
      'Cursor',
      'Nightly lint',
      'Partner sync',
      'Terraform',
    ]);
  });

  it('groups by type', () => {
    const sorted = sortWorkspaceKeys(ROWS, { column: 'type', direction: 'asc' }, NOW);
    expect(sorted.map((row) => row.kind)).toEqual(['mcp', 'mcp', 'rest', 'rest', 'rest', 'rest']);
  });

  it('sorts timestamps as instants, and a key that never expires last', () => {
    const sorted = sortWorkspaceKeys(ROWS, { column: 'expires', direction: 'asc' }, NOW);
    expect(workspaceKeyRowId(sorted[0])).toBe('rest:k-expired');
    expect(sorted.slice(-3).every((row) => row.key.expires_at === null)).toBe(true);
  });

  it('reverses on the second click and does not mutate its input', () => {
    const before = ids(ROWS);
    const asc = ids(sortWorkspaceKeys(ROWS, { column: 'name', direction: 'asc' }, NOW));
    const desc = ids(sortWorkspaceKeys(ROWS, { column: 'name', direction: 'desc' }, NOW));
    expect(desc).toEqual([...asc].reverse());
    expect(ids(ROWS)).toEqual(before);
  });
});

describe('the foot', () => {
  it('counts both kinds and every status they are in', () => {
    expect(describeWorkspaceKeyBreakdown(ROWS, NOW)).toBe(
      '6 keys · 4 REST API · 2 MCP server · 3 active · 1 disabled · 1 expired · 1 revoked'
    );
  });

  it('leaves out the per-kind counts when only one kind is present', () => {
    expect(describeWorkspaceKeyBreakdown(toWorkspaceKeyRows(REST, []), NOW)).toBe(
      '4 keys · 2 active · 1 disabled · 1 expired'
    );
    expect(describeWorkspaceKeyBreakdown([], NOW)).toBe('0 keys');
  });
});

describe('regenerating', () => {
  const row = (id: string) => ROWS.find((entry) => entry.key.id === id)!;

  it('is offered on every live key of either kind, a disabled REST key included', () => {
    for (const id of ['k-active', 'k-disabled', 'k-both', 'm-claude']) {
      expect(workspaceKeyRegeneration(row(id), NOW)).toEqual({ canRegenerate: true, reason: null });
    }
  });

  it('is refused on an expired key, which would come back already dead', () => {
    expect(workspaceKeyRegeneration(row('k-expired'), NOW)).toEqual({
      canRegenerate: false,
      reason: 'This key has expired. Create a new key instead.',
    });
    const expiredMcp = toWorkspaceKeyRows([], [mcpKey({ expires_at: '2026-01-01T00:00:00Z' })])[0];
    expect(workspaceKeyRegeneration(expiredMcp, NOW).canRegenerate).toBe(false);
  });

  it('is refused on a revoked MCP key, which is gone for good', () => {
    expect(workspaceKeyRegeneration(row('m-cursor'), NOW)).toEqual({
      canRegenerate: false,
      reason: 'This key is revoked. Create a new MCP key instead.',
    });
  });

  it('summarises what carried over for the reveal dialog', () => {
    expect(describeRegeneratedKey(row('k-active'))).toBe(
      '“CI contract gate” · REST API · same scopes and expiry'
    );
    expect(describeRegeneratedKey(row('m-claude'))).toBe(
      '“Claude Desktop” · MCP server · same tools and expiry'
    );
  });
});
