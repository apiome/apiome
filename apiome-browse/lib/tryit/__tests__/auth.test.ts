import { afterEach, describe, expect, it } from 'vitest';
import {
  applyAuthToRequest,
  authSecretPlaceholders,
  authStorageKey,
  clearAuthCredentials,
  encodeBasicCredentials,
  extractSecuritySchemes,
  hasFilledCredentials,
  loadAuthCredentials,
  parseSecurityRequirements,
  resolveOperationAuth,
  saveAuthCredentials,
  shouldWarnProxyCredentials,
  type AuthCredentialsMap,
  type AuthStorage,
  type SupportedAuthScheme,
} from '../auth';

/** In-memory sessionStorage stand-in for unit tests. */
function memoryStorage(initial: Record<string, string> = {}): AuthStorage & {
  data: Record<string, string>;
} {
  const data = { ...initial };
  return {
    data,
    getItem(key: string) {
      return key in data ? data[key] : null;
    },
    setItem(key: string, value: string) {
      data[key] = value;
    },
    removeItem(key: string) {
      delete data[key];
    },
  };
}

const SPEC = {
  openapi: '3.0.3',
  security: [{ ApiKeyAuth: [] }],
  paths: {
    '/pets': {
      get: {
        security: [{ BearerAuth: [] }],
      },
      post: {
        // Inherits document-level ApiKeyAuth.
      },
      delete: {
        security: [],
      },
    },
    '/admin': {
      get: {
        security: [{ BearerAuth: [], ApiKeyAuth: [] }, { BasicAuth: [] }],
      },
    },
    '/oauth': {
      get: {
        security: [{ OAuth: [] }],
      },
    },
    '/optional': {
      get: {
        security: [{}],
      },
    },
  },
  components: {
    securitySchemes: {
      BearerAuth: {
        type: 'http',
        scheme: 'bearer',
        bearerFormat: 'JWT',
        description: 'JWT bearer token',
      },
      BasicAuth: {
        type: 'http',
        scheme: 'basic',
      },
      ApiKeyAuth: {
        type: 'apiKey',
        name: 'X-API-Key',
        in: 'header',
      },
      QueryKey: {
        type: 'apiKey',
        name: 'api_key',
        in: 'query',
      },
      CookieKey: {
        type: 'apiKey',
        name: 'session',
        in: 'cookie',
      },
      OAuth: {
        type: 'oauth2',
        flows: {
          implicit: {
            authorizationUrl: 'https://example.com/oauth',
            scopes: { read: 'Read' },
          },
        },
      },
      Digest: {
        type: 'http',
        scheme: 'digest',
      },
      RefBearer: { $ref: '#/components/securitySchemes/BearerAuth' },
    },
  },
};

describe('encodeBasicCredentials', () => {
  it('base64-encodes username:password', () => {
    expect(encodeBasicCredentials('user', 'pass')).toBe(
      Buffer.from('user:pass', 'utf8').toString('base64')
    );
  });

  it('handles empty password and non-ASCII', () => {
    expect(encodeBasicCredentials('alice', '')).toBe(
      Buffer.from('alice:', 'utf8').toString('base64')
    );
    expect(encodeBasicCredentials('üser', 'päss')).toBe(
      Buffer.from('üser:päss', 'utf8').toString('base64')
    );
  });
});

describe('extractSecuritySchemes', () => {
  it('classifies bearer, basic, and apiKey schemes as supported', () => {
    const { supported, unsupported } = extractSecuritySchemes(SPEC);
    const kinds = Object.fromEntries(supported.map((s) => [s.name, s.kind]));
    expect(kinds.BearerAuth).toBe('bearer');
    expect(kinds.BasicAuth).toBe('basic');
    expect(kinds.ApiKeyAuth).toBe('apiKey');
    expect(kinds.QueryKey).toBe('apiKey');
    expect(kinds.CookieKey).toBe('apiKey');
    expect(unsupported.map((u) => u.name).sort()).toEqual(['Digest', 'OAuth']);
  });

  it('resolves $ref security schemes', () => {
    const { supported } = extractSecuritySchemes(SPEC);
    expect(supported.find((s) => s.name === 'RefBearer')?.kind).toBe('bearer');
  });

  it('returns empty lists when components.securitySchemes is absent', () => {
    expect(extractSecuritySchemes({ openapi: '3.0.3' })).toEqual({
      supported: [],
      unsupported: [],
    });
  });
});

describe('parseSecurityRequirements', () => {
  it('returns null when security is undefined (caller falls back)', () => {
    expect(parseSecurityRequirements(undefined)).toBeNull();
  });

  it('parses OR-alternatives of AND-grouped scheme names', () => {
    expect(
      parseSecurityRequirements([{ a: [], b: [] }, { c: [] }, {}])
    ).toEqual([{ schemes: ['a', 'b'] }, { schemes: ['c'] }, { schemes: [] }]);
  });

  it('treats a non-array as no requirements', () => {
    expect(parseSecurityRequirements('nope')).toEqual([]);
  });
});

describe('resolveOperationAuth', () => {
  it('uses operation-level security when present', () => {
    const auth = resolveOperationAuth(SPEC, 'get', '/pets');
    expect(auth.applies).toBe(true);
    expect(auth.schemes.map((s) => s.name)).toEqual(['BearerAuth']);
    expect(auth.alternatives).toEqual([{ schemes: ['BearerAuth'] }]);
  });

  it('falls back to document-level security', () => {
    const auth = resolveOperationAuth(SPEC, 'post', '/pets');
    expect(auth.schemes.map((s) => s.name)).toEqual(['ApiKeyAuth']);
  });

  it('clears document security when the operation sets an empty array', () => {
    const auth = resolveOperationAuth(SPEC, 'delete', '/pets');
    expect(auth.applies).toBe(false);
    expect(auth.schemes).toEqual([]);
    expect(auth.alternatives).toEqual([]);
  });

  it('collects all schemes across OR-alternatives', () => {
    const auth = resolveOperationAuth(SPEC, 'get', '/admin');
    expect(auth.schemes.map((s) => s.name).sort()).toEqual([
      'ApiKeyAuth',
      'BasicAuth',
      'BearerAuth',
    ]);
    expect(auth.alternatives).toEqual([
      { schemes: ['BearerAuth', 'ApiKeyAuth'] },
      { schemes: ['BasicAuth'] },
    ]);
  });

  it('surfaces oauth as unsupported without inventing inputs', () => {
    const auth = resolveOperationAuth(SPEC, 'get', '/oauth');
    expect(auth.applies).toBe(false);
    expect(auth.unsupported).toEqual([
      expect.objectContaining({ name: 'OAuth', type: 'oauth2' }),
    ]);
  });

  it('treats a lone empty alternative as optional (no required schemes)', () => {
    const auth = resolveOperationAuth(SPEC, 'get', '/optional');
    expect(auth.applies).toBe(false);
    expect(auth.alternatives).toEqual([{ schemes: [] }]);
  });

  it('flags schemes named in security but missing from components', () => {
    const auth = resolveOperationAuth(
      {
        openapi: '3.0.3',
        paths: { '/x': { get: { security: [{ Missing: [] }] } } },
        components: { securitySchemes: {} },
      },
      'get',
      '/x'
    );
    expect(auth.unsupported[0]).toMatchObject({ name: 'Missing', type: 'unknown' });
  });
});

describe('applyAuthToRequest', () => {
  const bearer: SupportedAuthScheme = { name: 'BearerAuth', kind: 'bearer' };
  const basic: SupportedAuthScheme = { name: 'BasicAuth', kind: 'basic' };
  const headerKey: SupportedAuthScheme = {
    name: 'ApiKeyAuth',
    kind: 'apiKey',
    paramName: 'X-API-Key',
    location: 'header',
  };
  const queryKey: SupportedAuthScheme = {
    name: 'QueryKey',
    kind: 'apiKey',
    paramName: 'api_key',
    location: 'query',
  };
  const cookieKey: SupportedAuthScheme = {
    name: 'CookieKey',
    kind: 'apiKey',
    paramName: 'session',
    location: 'cookie',
  };

  it('sets Authorization: Bearer for bearer schemes', () => {
    const result = applyAuthToRequest(
      'https://api.example.com/pets',
      { Accept: 'application/json' },
      [bearer],
      { BearerAuth: { bearerToken: ' tok ' } }
    );
    expect(result.headers).toEqual({
      Accept: 'application/json',
      Authorization: 'Bearer tok',
    });
  });

  it('sets Authorization: Basic with base64 credentials', () => {
    const result = applyAuthToRequest(
      'https://api.example.com/pets',
      {},
      [basic],
      { BasicAuth: { username: 'alice', password: 's3cret' } }
    );
    expect(result.headers.Authorization).toBe(
      `Basic ${encodeBasicCredentials('alice', 's3cret')}`
    );
  });

  it('sets header apiKeys and overwrites same-named form headers', () => {
    const result = applyAuthToRequest(
      'https://api.example.com/pets',
      { 'X-API-Key': 'from-form' },
      [headerKey],
      { ApiKeyAuth: { apiKey: 'from-helper' } }
    );
    expect(result.headers['X-API-Key']).toBe('from-helper');
  });

  it('appends query apiKeys, replacing an existing same-named param', () => {
    const result = applyAuthToRequest(
      'https://api.example.com/pets?api_key=old&limit=5',
      {},
      [queryKey],
      { QueryKey: { apiKey: 'new-key' } }
    );
    const parsed = new URL(result.url);
    expect(parsed.searchParams.get('api_key')).toBe('new-key');
    expect(parsed.searchParams.get('limit')).toBe('5');
  });

  it('writes cookie apiKeys as a Cookie header', () => {
    const result = applyAuthToRequest(
      'https://api.example.com/pets',
      {},
      [cookieKey],
      { CookieKey: { apiKey: 'sid-value' } }
    );
    expect(result.headers.Cookie).toBe('session=sid-value');
  });

  it('skips empty credential fields', () => {
    const result = applyAuthToRequest(
      'https://api.example.com/pets',
      { Accept: 'application/json' },
      [bearer, headerKey],
      { BearerAuth: { bearerToken: '  ' }, ApiKeyAuth: { apiKey: '' } }
    );
    expect(result.headers).toEqual({ Accept: 'application/json' });
  });
});

describe('authSecretPlaceholders', () => {
  it('emits placeholders only for filled schemes', () => {
    const schemes: SupportedAuthScheme[] = [
      { name: 'BearerAuth', kind: 'bearer' },
      {
        name: 'QueryKey',
        kind: 'apiKey',
        paramName: 'api_key',
        location: 'query',
      },
    ];
    expect(
      authSecretPlaceholders(schemes, {
        BearerAuth: { bearerToken: 'tok' },
        QueryKey: { apiKey: '' },
      })
    ).toEqual({ authorization: '$AUTHORIZATION' });

    expect(
      authSecretPlaceholders(schemes, {
        QueryKey: { apiKey: 'k' },
      })
    ).toEqual({ 'query:api_key': '$API_KEY' });
  });
});

describe('hasFilledCredentials / shouldWarnProxyCredentials', () => {
  const schemes: SupportedAuthScheme[] = [{ name: 'BearerAuth', kind: 'bearer' }];

  it('detects filled bearer tokens', () => {
    expect(hasFilledCredentials(schemes, {})).toBe(false);
    expect(hasFilledCredentials(schemes, { BearerAuth: { bearerToken: 'x' } })).toBe(true);
  });

  it('warns only for custom hosts with filled credentials', () => {
    const creds: AuthCredentialsMap = { BearerAuth: { bearerToken: 'x' } };
    expect(shouldWarnProxyCredentials(true, schemes, creds)).toBe(true);
    expect(shouldWarnProxyCredentials(false, schemes, creds)).toBe(false);
    expect(shouldWarnProxyCredentials(true, schemes, {})).toBe(false);
  });
});

describe('session storage helpers', () => {
  afterEach(() => {
    // no shared state
  });

  it('saves, loads, and clears credentials via the injectable store', () => {
    const store = memoryStorage();
    saveAuthCredentials('BearerAuth', { bearerToken: 'tok' }, store);
    expect(store.data[authStorageKey('BearerAuth')]).toBe(
      JSON.stringify({ bearerToken: 'tok' })
    );

    expect(loadAuthCredentials(['BearerAuth', 'Missing'], store)).toEqual({
      BearerAuth: { bearerToken: 'tok' },
    });

    clearAuthCredentials(['BearerAuth'], store);
    expect(loadAuthCredentials(['BearerAuth'], store)).toEqual({});
  });

  it('removes the key when all fields are blank', () => {
    const store = memoryStorage({
      [authStorageKey('BearerAuth')]: JSON.stringify({ bearerToken: 'tok' }),
    });
    saveAuthCredentials('BearerAuth', { bearerToken: '  ' }, store);
    expect(store.data).not.toHaveProperty(authStorageKey('BearerAuth'));
  });

  it('ignores corrupt JSON without throwing', () => {
    const store = memoryStorage({
      [authStorageKey('BearerAuth')]: 'not-json',
    });
    expect(loadAuthCredentials(['BearerAuth'], store)).toEqual({});
  });

  it('no-ops when storage is null', () => {
    expect(() => saveAuthCredentials('X', { apiKey: 'k' }, null)).not.toThrow();
    expect(loadAuthCredentials(['X'], null)).toEqual({});
    expect(() => clearAuthCredentials(['X'], null)).not.toThrow();
  });
});
