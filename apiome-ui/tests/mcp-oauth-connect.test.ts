/**
 * Unit tests for the MCP OAuth connect model (V2-MCP-20.4 / MCAT-6.4, #3680).
 */

import { describe, expect, it } from '@jest/globals';

import {
  MCP_OAUTH_CALLBACK_PATH,
  mcpOAuthAuthorizeBody,
  mcpOAuthCallbackParams,
  mcpOAuthExpiryLine,
  mcpOAuthRedirectUri,
  mcpOAuthReturnPath,
  mcpOAuthStatusFromCredential,
} from '../src/app/components/ade/dashboard/mcp/mcpOAuthConnect';

const DISCOVERED = {
  issuer: 'https://auth.example.com',
  authorization_endpoint: 'https://auth.example.com/authorize',
  token_endpoint: 'https://auth.example.com/token',
  registration_endpoint: 'https://auth.example.com/register',
  pkce_s256_supported: true,
};

describe('mcpOAuthStatusFromCredential', () => {
  it('reports nothing discovered for a plain credential', () => {
    const status = mcpOAuthStatusFromCredential({ auth_type: 'bearer', configured: true, oauth_metadata: {} });
    expect(status.discovered).toBe(false);
    expect(status.connected).toBe(false);
    expect(mcpOAuthStatusFromCredential(null).discovered).toBe(false);
  });

  it('reads a discovered but unconnected server', () => {
    const status = mcpOAuthStatusFromCredential({ auth_type: 'none', configured: false, oauth_metadata: DISCOVERED });
    expect(status).toMatchObject({
      discovered: true,
      issuer: 'https://auth.example.com',
      dynamicRegistration: true,
      pkceSupported: true,
      connected: false,
      lastRefreshError: null,
    });
  });

  it('reads a connected token summary and a refresh error', () => {
    const status = mcpOAuthStatusFromCredential({
      auth_type: 'oauth2',
      configured: true,
      oauth_metadata: {
        ...DISCOVERED,
        registration_endpoint: null,
        token: {
          client_id: 'client-1',
          scope: 'mcp:read',
          expires_at: '2026-11-08T13:00:00+00:00',
          refreshable: true,
          last_refresh_error: { code: 'token_error', message: 'token refresh returned HTTP 400 (invalid_grant)' },
        },
      },
    });
    expect(status).toMatchObject({
      connected: true,
      dynamicRegistration: false,
      clientId: 'client-1',
      scope: 'mcp:read',
      expiresAt: '2026-11-08T13:00:00+00:00',
      refreshable: true,
      lastRefreshError: 'token refresh returned HTTP 400 (invalid_grant)',
    });
  });
});

describe('request and redirect helpers', () => {
  it('builds the redirect URI from the origin', () => {
    expect(mcpOAuthRedirectUri('https://app.example.com/')).toBe(`https://app.example.com${MCP_OAUTH_CALLBACK_PATH}`);
  });

  it('adds a client id only when typed', () => {
    expect(mcpOAuthAuthorizeBody('https://x/cb', '  ')).toEqual({ redirect_uri: 'https://x/cb' });
    expect(mcpOAuthAuthorizeBody('https://x/cb', ' pre-1 ')).toEqual({ redirect_uri: 'https://x/cb', client_id: 'pre-1' });
  });

  it('reads the callback query', () => {
    expect(mcpOAuthCallbackParams('?code=c&state=s&iss=https%3A%2F%2Fauth.example.com')).toEqual({
      state: 's',
      code: 'c',
      error: null,
      error_description: null,
      iss: 'https://auth.example.com',
    });
    expect(mcpOAuthCallbackParams('?error=access_denied&state=s')?.error).toBe('access_denied');
    expect(mcpOAuthCallbackParams('?code=c')).toBeNull();
  });

  it('returns to the Settings tab', () => {
    expect(mcpOAuthReturnPath('abc')).toBe('/ade/dashboard/mcp/abc?tab=settings');
  });
});

describe('mcpOAuthExpiryLine', () => {
  const base = mcpOAuthStatusFromCredential({ auth_type: 'oauth2', configured: true, oauth_metadata: DISCOVERED });
  const fmt = (iso: string) => `<${iso}>`;

  it('is empty when not connected', () => {
    expect(mcpOAuthExpiryLine({ ...base, connected: false }, fmt)).toBeNull();
  });

  it('says whether the token renews', () => {
    expect(mcpOAuthExpiryLine({ ...base, expiresAt: 'T', refreshable: true }, fmt)).toBe('Expires <T> · renews automatically');
    expect(mcpOAuthExpiryLine({ ...base, expiresAt: null, refreshable: false }, fmt)).toBe(
      'No expiry reported · connect again when it expires',
    );
  });
});
