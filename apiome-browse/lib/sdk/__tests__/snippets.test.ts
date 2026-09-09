/**
 * Public per-operation snippet helpers — SDK-3.3 (#4493).
 *
 * Pins how an operation is addressed on the SDK-2.3 route — the part most likely to break, since
 * the route's `:path` parameter accepts an encoding that `encodeURIComponent` alone does not
 * produce — plus the tab vocabulary and the error copy.
 */

import { describe, expect, it } from 'vitest';
import {
  SNIPPET_LANGS,
  SNIPPET_LANG_LABELS,
  encodeOperationId,
  operationIdForSnippet,
  publicSnippetUrl,
  snippetCacheKey,
  snippetErrorFromResponse,
  snippetErrorMessage,
} from '../snippets';

const COORDS = { tenantSlug: 'acme', projectSlug: 'widgets', versionSlug: '1.0.0' };
const BASE = 'https://api.example.com/v1';

/** A Response double carrying a status and a body. */
function response(status: number, body = ''): Response {
  return { status, text: async () => body } as unknown as Response;
}

describe('operationIdForSnippet', () => {
  it('prefers the spec-declared operationId', () => {
    expect(
      operationIdForSnippet({ method: 'get', path: '/pets/{id}', operationId: 'getPet' })
    ).toBe('getPet');
  });

  it('falls back to the canonical key for a spec that declares none', () => {
    expect(operationIdForSnippet({ method: 'get', path: '/pets/{id}' })).toBe('GET /pets/{id}');
  });

  it('upper-cases the method in the fallback, as the canonical key does', () => {
    expect(operationIdForSnippet({ method: 'patch', path: '/pets' })).toBe('PATCH /pets');
  });

  it('treats a blank operationId as absent', () => {
    expect(operationIdForSnippet({ method: 'get', path: '/pets', operationId: '   ' })).toBe(
      'GET /pets'
    );
  });
});

describe('encodeOperationId', () => {
  it('encodes spaces and braces but leaves slashes whole', () => {
    // The exact form the route's docs give as addressable. Fully-encoded slashes (`%2F`) are
    // rejected outright by some proxies, so they are restored.
    expect(encodeOperationId('GET /pets/{id}')).toBe('GET%20/pets/%7Bid%7D');
  });

  it('leaves a plain operationId untouched', () => {
    expect(encodeOperationId('getPet')).toBe('getPet');
  });

  it('encodes a query-string character that would otherwise truncate the path', () => {
    expect(encodeOperationId('GET /a?b')).toBe('GET%20/a%3Fb');
  });
});

describe('publicSnippetUrl', () => {
  it('addresses an operation by id in one language', () => {
    expect(publicSnippetUrl(BASE, COORDS, 'getPet', 'ts')).toBe(
      'https://api.example.com/v1/browse/tenants/acme/projects/widgets/versions/1.0.0' +
        '/snippets/getPet?lang=ts'
    );
  });

  it('addresses a canonical key without breaking the path', () => {
    expect(publicSnippetUrl(BASE, COORDS, 'GET /pets/{id}', 'curl')).toBe(
      'https://api.example.com/v1/browse/tenants/acme/projects/widgets/versions/1.0.0' +
        '/snippets/GET%20/pets/%7Bid%7D?lang=curl'
    );
  });

  it('encodes each slug segment', () => {
    const url = publicSnippetUrl(
      BASE,
      { tenantSlug: 'a c', projectSlug: 'p/q', versionSlug: '1.0' },
      'getPet',
      'python'
    );
    expect(url).toContain('/tenants/a%20c/');
    expect(url).toContain('/projects/p%2Fq/');
  });
});

describe('the tab vocabulary', () => {
  it('offers the three canonical languages in documentation order', () => {
    expect(SNIPPET_LANGS).toEqual(['ts', 'python', 'curl']);
  });

  it('labels every language it offers', () => {
    for (const lang of SNIPPET_LANGS) {
      expect(SNIPPET_LANG_LABELS[lang]).toBeTruthy();
    }
  });
});

describe('snippetCacheKey', () => {
  it('is unique per operation and language', () => {
    expect(snippetCacheKey('getPet', 'ts')).not.toBe(snippetCacheKey('getPet', 'curl'));
    expect(snippetCacheKey('getPet', 'ts')).not.toBe(snippetCacheKey('listPets', 'ts'));
  });

  it('is stable for the same pair', () => {
    expect(snippetCacheKey('getPet', 'ts')).toBe(snippetCacheKey('getPet', 'ts'));
  });
});

describe('snippetErrorMessage', () => {
  it('states plainly that an operation simply has no request example', () => {
    // A 422 here is a property of the operation (no HTTP binding), not a fault to retry past.
    expect(snippetErrorMessage(422)).toBe('No request example is defined for this operation.');
  });

  it('explains a rate limit', () => {
    expect(snippetErrorMessage(429)).toContain('Too many requests');
  });

  it('explains an unavailable example', () => {
    expect(snippetErrorMessage(404)).toBe('No example is available for this operation.');
  });

  it('names the status for anything else', () => {
    expect(snippetErrorMessage(500)).toBe('Could not load the example (500).');
  });

  it("prefers the server's own sentence when it sent one", () => {
    expect(snippetErrorMessage(422, 'No HTTP binding.')).toBe('No HTTP binding.');
  });
});

describe('snippetErrorFromResponse', () => {
  it('lifts the detail out of the body', async () => {
    await expect(
      snippetErrorFromResponse(response(422, '{"detail": "no HTTP binding"}'))
    ).resolves.toBe('no HTTP binding');
  });

  it('falls back to the stable copy when the body carries none', async () => {
    await expect(snippetErrorFromResponse(response(404))).resolves.toBe(
      'No example is available for this operation.'
    );
  });
});
