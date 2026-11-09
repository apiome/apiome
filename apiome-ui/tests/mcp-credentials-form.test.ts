/**
 * Unit tests for the Credentials tab's pure helpers (V2-MCP-24.6 / MCAT-10.6, #3702):
 * reading the redacted status, validating the form the way apiome-rest will, building the request
 * body the Add MCP server dialog also sends, and the summary lines the panel shows.
 */

import { describe, expect, it } from '@jest/globals';

import {
  MCP_CREDENTIAL_AUTH_OPTIONS,
  MCP_CREDENTIAL_MASK,
  MCP_CREDENTIAL_NONE,
  buildMcpCredentialBody,
  emptyMcpCredentialForm,
  mcpCredentialAuthLabel,
  mcpCredentialMetaLine,
  mcpCredentialSecretLabel,
  mcpCredentialStatusFromPayload,
  mcpCredentialSummary,
  validateMcpCredentialForm,
} from '../src/app/components/ade/dashboard/mcp/mcpCredentialsForm';
import { buildCredentialBody, emptyMcpImportForm } from '../src/app/components/ade/dashboard/mcp/mcpImportFlow';

describe('MCP_CREDENTIAL_AUTH_OPTIONS', () => {
  it('offers every scheme the Add MCP server dialog does, except anonymous', () => {
    expect(MCP_CREDENTIAL_AUTH_OPTIONS.map((o) => o.value)).toEqual(['bearer', 'header', 'oauth2']);
    expect(MCP_CREDENTIAL_AUTH_OPTIONS.map((o) => o.label)).toEqual([
      'Bearer token',
      'Custom header',
      'OAuth 2.1 access token',
    ]);
  });

  it('draws a mask that is not a secret', () => {
    expect(MCP_CREDENTIAL_MASK).toBe('••••••••');
  });
});

describe('mcpCredentialStatusFromPayload', () => {
  it('reads the redacted status out of the route envelope', () => {
    const status = mcpCredentialStatusFromPayload({
      success: true,
      credential: {
        endpoint_id: 'ep-1',
        auth_type: 'bearer',
        configured: true,
        masked_secret: '********',
        key_version: 3,
        oauth_metadata: { issuer: 'https://auth.example' },
        last_refreshed_at: null,
        created_at: '2026-11-01T00:00:00Z',
        updated_at: '2026-11-08T12:00:00Z',
      },
    });
    expect(status).toEqual({
      endpointId: 'ep-1',
      authType: 'bearer',
      configured: true,
      keyVersion: 3,
      oauthMetadata: { issuer: 'https://auth.example' },
      lastRefreshedAt: null,
      createdAt: '2026-11-01T00:00:00Z',
      updatedAt: '2026-11-08T12:00:00Z',
    });
  });

  it('accepts a bare credential object and reads the anonymous state', () => {
    expect(mcpCredentialStatusFromPayload({ auth_type: 'none', configured: false })).toEqual({
      ...MCP_CREDENTIAL_NONE,
    });
  });

  it('has no field a secret could arrive in', () => {
    const status = mcpCredentialStatusFromPayload({
      credential: { auth_type: 'bearer', configured: true, token: 'sk-live-should-never-be-here', encrypted_payload: 'xx' },
    });
    expect(JSON.stringify(status)).not.toContain('sk-live');
    expect(JSON.stringify(status)).not.toContain('encrypted_payload');
  });

  it('ignores a key version when nothing is configured', () => {
    expect(mcpCredentialStatusFromPayload({ auth_type: 'none', configured: false, key_version: 4 })?.keyVersion).toBeNull();
  });

  it('returns null for a body that is not a credential status', () => {
    expect(mcpCredentialStatusFromPayload({ success: true })).toBeNull();
    expect(mcpCredentialStatusFromPayload(null)).toBeNull();
    expect(mcpCredentialStatusFromPayload('nope')).toBeNull();
  });
});

describe('mcpCredentialAuthLabel', () => {
  it('names every scheme as the dialog does', () => {
    expect(mcpCredentialAuthLabel('bearer')).toBe('Bearer token');
    expect(mcpCredentialAuthLabel('header')).toBe('Custom header');
    expect(mcpCredentialAuthLabel('oauth2')).toBe('OAuth 2.1');
    expect(mcpCredentialAuthLabel('env')).toBe('Environment variables');
    expect(mcpCredentialAuthLabel('none')).toBe('None (anonymous)');
    expect(mcpCredentialAuthLabel(null)).toBe('None (anonymous)');
    expect(mcpCredentialAuthLabel('mtls')).toBe('mtls');
  });
});

describe('mcpCredentialSummary / mcpCredentialMetaLine', () => {
  const fmt = (iso: string) => `@${iso}`;

  it('explains the anonymous state', () => {
    expect(mcpCredentialSummary(MCP_CREDENTIAL_NONE)).toEqual({
      title: 'No credential stored',
      detail: 'Discovery, the scheduled sweep and Test calls reach this server anonymously.',
    });
    expect(mcpCredentialMetaLine(MCP_CREDENTIAL_NONE, fmt)).toBeNull();
  });

  it('names what is stored and how it is sent', () => {
    const bearer = { ...MCP_CREDENTIAL_NONE, authType: 'bearer', configured: true, keyVersion: 2, updatedAt: 'T1' };
    expect(mcpCredentialSummary(bearer).title).toBe('Bearer token stored');
    expect(mcpCredentialSummary(bearer).detail).toMatch(/Authorization header/);
    expect(mcpCredentialMetaLine(bearer, fmt)).toBe('Encrypted with key v2 · Updated @T1');

    const header = { ...bearer, authType: 'header', keyVersion: null, updatedAt: null, createdAt: 'T0' };
    expect(mcpCredentialSummary(header).title).toBe('Custom header stored');
    expect(mcpCredentialSummary(header).detail).toMatch(/named request header/);
    expect(mcpCredentialMetaLine(header, fmt)).toBe('Updated @T0');

    const oauth = { ...bearer, authType: 'oauth2' };
    expect(mcpCredentialSummary(oauth).title).toBe('OAuth 2.1 token stored');
    expect(mcpCredentialSummary(oauth).detail).toMatch(/bearer token/);
  });

  it('says nothing under the mask when there is nothing to say', () => {
    expect(mcpCredentialMetaLine({ ...MCP_CREDENTIAL_NONE, authType: 'bearer', configured: true }, fmt)).toBeNull();
  });
});

describe('validateMcpCredentialForm', () => {
  it('requires the token for bearer and OAuth', () => {
    expect(validateMcpCredentialForm(emptyMcpCredentialForm('bearer'))).toMatch(/Enter the access token/);
    expect(validateMcpCredentialForm(emptyMcpCredentialForm('oauth2'))).toMatch(/Enter the access token/);
    expect(validateMcpCredentialForm({ ...emptyMcpCredentialForm('bearer'), secret: '   ' })).toMatch(/Enter the access token/);
    expect(validateMcpCredentialForm({ ...emptyMcpCredentialForm('bearer'), secret: 'tok' })).toBeNull();
  });

  it('requires both halves of a header, and a header name apiome-rest will accept', () => {
    expect(validateMcpCredentialForm(emptyMcpCredentialForm('header'))).toBe('Enter the header value.');
    expect(validateMcpCredentialForm({ authType: 'header', secret: 'v', headerName: '' })).toBe('Enter the header name.');
    expect(validateMcpCredentialForm({ authType: 'header', secret: 'v', headerName: 'X Api Key' })).toMatch(/letters, digits/);
    expect(validateMcpCredentialForm({ authType: 'header', secret: 'v', headerName: 'X-Api-Key:' })).toMatch(/letters, digits/);
    expect(validateMcpCredentialForm({ authType: 'header', secret: 'v', headerName: 'X-Api-Key' })).toBeNull();
  });

  it('refuses the injection apiome-rest refuses, before the request', () => {
    expect(validateMcpCredentialForm({ authType: 'bearer', secret: 'a\r\nX-Evil: 1', headerName: '' })).toBe(
      'The secret cannot contain line breaks.',
    );
    expect(validateMcpCredentialForm({ authType: 'header', secret: 'v', headerName: 'X\nY' })).toMatch(/letters, digits/);
  });

  it('points an Authorization header at the bearer scheme', () => {
    expect(validateMcpCredentialForm({ authType: 'header', secret: 'v', headerName: 'authorization' })).toMatch(
      /Bearer token auth type/,
    );
  });
});

describe('buildMcpCredentialBody', () => {
  it('sends the same body as the Add MCP server dialog, trimmed', () => {
    expect(buildMcpCredentialBody({ authType: 'bearer', secret: ' tok ', headerName: '' })).toEqual({
      auth_type: 'bearer',
      payload: { token: 'tok' },
    });
    expect(buildMcpCredentialBody({ authType: 'header', secret: 'v', headerName: ' X-Api-Key ' })).toEqual({
      auth_type: 'header',
      payload: { name: 'X-Api-Key', value: 'v' },
    });
    expect(buildMcpCredentialBody({ authType: 'oauth2', secret: 'at', headerName: '' })).toEqual({
      auth_type: 'oauth2',
      payload: { access_token: 'at' },
    });
  });

  it('is the dialog’s builder, not a copy of it', () => {
    const viaDialog = buildCredentialBody({ ...emptyMcpImportForm(), authType: 'header', authToken: 'v', authHeaderName: 'X-K' });
    expect(buildMcpCredentialBody({ authType: 'header', secret: 'v', headerName: 'X-K' })).toEqual(viaDialog);
  });
});

describe('mcpCredentialSecretLabel', () => {
  it('labels the secret field by scheme', () => {
    expect(mcpCredentialSecretLabel('bearer')).toBe('Access token');
    expect(mcpCredentialSecretLabel('oauth2')).toBe('Access token');
    expect(mcpCredentialSecretLabel('header')).toBe('Header value');
  });
});
