/**
 * The MCP key derivations — `components/ade/apiKeys/mcpKeysModel`.
 */

import type { McpApiKeyMetadata } from '../src/app/ade/dashboard/tenants/mcpKeysApi';
import {
  describeCreatedMcpKey,
  describeMcpKeyCapabilities,
  mcpKeyExpiresAt,
  mcpKeyStatus,
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
