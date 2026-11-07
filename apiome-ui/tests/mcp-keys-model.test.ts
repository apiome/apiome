/**
 * The MCP tab's derivations — `components/ade/apiKeys/mcpKeysModel`.
 */

import type { McpApiKeyMetadata } from '../src/app/ade/dashboard/tenants/mcpKeysApi';
import {
  describeCreatedMcpKey,
  describeMcpKeyBreakdown,
  describeMcpKeyCapabilities,
  mcpKeyExpiresAt,
  mcpKeyFacetCounts,
  mcpKeyStatus,
  searchMcpKeys,
  sortMcpKeys,
  validateMcpKeyDraft,
} from '../src/app/components/ade/apiKeys/mcpKeysModel';

const NOW = new Date('2026-11-07T12:00:00Z');

function key(overrides: Partial<McpApiKeyMetadata>): McpApiKeyMetadata {
  return {
    id: 'm-1',
    prefix: 'aB3dE5gH7jK9...',
    label: 'Claude Desktop',
    scope_json: { tenants: [], projects: [] },
    capability_mode: 'inherit',
    enabled_tools: [],
    created_at: '2026-10-01T10:00:00Z',
    expires_at: null,
    revoked_at: null,
    last_used_at: null,
    ...overrides,
  };
}

describe('mcpKeyStatus', () => {
  it('is active with no expiry and no revocation', () => {
    expect(mcpKeyStatus(key({}), NOW)).toBe('active');
  });

  it('is expired once the expiry has passed', () => {
    expect(mcpKeyStatus(key({ expires_at: '2026-11-01T00:00:00Z' }), NOW)).toBe('expired');
    expect(mcpKeyStatus(key({ expires_at: '2026-12-01T00:00:00Z' }), NOW)).toBe('active');
  });

  it('ranks revoked above expired', () => {
    expect(
      mcpKeyStatus(key({ revoked_at: '2026-10-10T00:00:00Z', expires_at: '2026-11-01T00:00:00Z' }), NOW)
    ).toBe('revoked');
  });

  it('does not retire a key over an unparseable expiry', () => {
    expect(mcpKeyStatus(key({ expires_at: 'not a date' }), NOW)).toBe('active');
  });
});

describe('describeMcpKeyCapabilities', () => {
  it('names an inheriting key by the workspace defaults', () => {
    expect(describeMcpKeyCapabilities(key({}))).toBe('Workspace defaults');
  });

  it('counts a custom set', () => {
    expect(
      describeMcpKeyCapabilities(key({ capability_mode: 'explicit', enabled_tools: ['spec.list'] }))
    ).toBe('Custom · 1 tool');
    expect(
      describeMcpKeyCapabilities(
        key({ capability_mode: 'explicit', enabled_tools: ['spec.list', 'version.export'] })
      )
    ).toBe('Custom · 2 tools');
  });
});

describe('search, counts and order', () => {
  const keys = [
    key({ id: 'a', label: 'Claude Desktop', prefix: 'aB3dE5gH7jK9...' }),
    key({ id: 'b', label: 'Cursor', prefix: 'zZ9yY8xX7wW6...', revoked_at: '2026-10-02T00:00:00Z' }),
    key({ id: 'c', label: 'Nightly agent', prefix: 'qQ1rR2sS3tT4...', expires_at: '2026-11-01T00:00:00Z' }),
  ];

  it('matches a label or a prefix pasted with its ellipsis', () => {
    expect(searchMcpKeys(keys, 'cursor').map((k) => k.id)).toEqual(['b']);
    expect(searchMcpKeys(keys, 'qQ1rR2…').map((k) => k.id)).toEqual(['c']);
    expect(searchMcpKeys(keys, '  ')).toHaveLength(3);
  });

  it('counts each status', () => {
    expect(mcpKeyFacetCounts(keys, NOW)).toEqual({ all: 3, active: 1, revoked: 1, expired: 1 });
    expect(describeMcpKeyBreakdown(keys, NOW)).toBe('3 keys · 1 active · 1 revoked · 1 expired');
    expect(describeMcpKeyBreakdown([keys[0]], NOW)).toBe('1 key · 1 active');
  });

  it('sorts by label and leaves the server order alone without a sort', () => {
    expect(sortMcpKeys(keys, null, NOW).map((k) => k.id)).toEqual(['a', 'b', 'c']);
    expect(
      sortMcpKeys(keys, { column: 'label', direction: 'desc' }, NOW).map((k) => k.id)
    ).toEqual(['c', 'b', 'a']);
  });

  it('sorts a key that never expires last, ascending', () => {
    expect(
      sortMcpKeys(keys, { column: 'expires', direction: 'asc' }, NOW).map((k) => k.id)[0]
    ).toBe('c');
  });
});

describe('the create form', () => {
  it('requires a label', () => {
    expect(validateMcpKeyDraft({ label: '  ', expiresInDays: '' })).toBe('Label is required');
  });

  it('refuses the expiries the REST form refuses', () => {
    expect(validateMcpKeyDraft({ label: 'x', expiresInDays: '0' })).not.toBeNull();
    expect(validateMcpKeyDraft({ label: 'x', expiresInDays: '1.5' })).not.toBeNull();
    expect(validateMcpKeyDraft({ label: 'x', expiresInDays: '90' })).toBeNull();
    expect(validateMcpKeyDraft({ label: 'x', expiresInDays: '' })).toBeNull();
  });

  it('turns days into the expires_at the server wants', () => {
    expect(mcpKeyExpiresAt('', NOW)).toBeNull();
    expect(mcpKeyExpiresAt('30', NOW)).toBe('2026-12-07T12:00:00.000Z');
  });

  it('summarises what was created', () => {
    expect(describeCreatedMcpKey({ label: ' Claude Desktop ', expiresInDays: '' })).toBe(
      '“Claude Desktop” · workspace default tools · expires never'
    );
    expect(describeCreatedMcpKey({ label: 'Cursor', expiresInDays: '1' })).toBe(
      '“Cursor” · workspace default tools · expires in 1 day'
    );
  });
});
