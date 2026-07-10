/**
 * Tests for the Try It CORS-safe relay logic — SIM-3.2 (#4448).
 */

import { describe, expect, it, vi } from 'vitest';
import {
  checkTargetAllowed,
  deriveAllowedSpecOrigins,
  executeRelay,
  isBlockedIp,
  MAX_REQUEST_BODY_BYTES,
  parseRelayEnvelope,
  sanitizeRequestHeaders,
  sanitizeResponseHeaders,
  serverUrlWithDefaults,
  SSRF_BLOCKED_CODE,
  statusTextFor,
  stripSensitiveHeaders,
  type RelayHttpRequest,
  type RelayHttpResponse,
  type RelayPolicy,
  type RelayRequest,
} from '../relay';

/** A valid relay envelope, overridable per test. */
const envelope = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  url: 'https://api.example.com/pets/42',
  method: 'GET',
  headers: { 'X-Trace': 'abc' },
  body: null,
  target: { kind: 'custom', customHostConfirmed: true },
  context: { tenantSlug: 'acme', projectSlug: 'petstore', versionSlug: '1.2' },
  ...over,
});

/** A validated relay request, overridable per test. */
const relayRequest = (over: Partial<RelayRequest> = {}): RelayRequest => ({
  url: 'https://api.example.com/pets/42',
  method: 'GET',
  headers: {},
  body: null,
  target: { kind: 'custom', customHostConfirmed: true },
  context: { tenantSlug: 'acme', projectSlug: 'petstore', versionSlug: '1.2' },
  ...over,
});

const openPolicy: RelayPolicy = { mockOrigin: null, specOrigins: [] };

/** Wrap body text as the async-iterable stream shape the relay reads. */
function bodyStream(
  chunks: (string | Uint8Array)[],
  destroy = vi.fn()
): RelayHttpResponse['body'] {
  const encoder = new TextEncoder();
  const data = chunks.map((c) => (typeof c === 'string' ? encoder.encode(c) : c));
  const iterable = {
    async *[Symbol.asyncIterator]() {
      yield* data;
    },
    destroy,
  };
  return iterable;
}

/** A stubbed upstream response. */
function httpResponse(over: Partial<RelayHttpResponse> = {}): RelayHttpResponse {
  return {
    statusCode: 200,
    headers: { 'content-type': 'application/json' },
    body: bodyStream(['{"ok":true}']),
    ...over,
  };
}

/** Deps with a public-resolving DNS stub and a single canned response. */
function fakeDeps(
  httpRequest: RelayHttpRequest,
  over: Partial<Parameters<typeof executeRelay>[2]> = {}
) {
  return {
    httpRequest,
    resolve: vi.fn(async () => ['93.184.216.34']),
    ...over,
  };
}

describe('parseRelayEnvelope', () => {
  it('accepts a valid envelope and upper-cases the method', () => {
    const parsed = parseRelayEnvelope(envelope({ method: 'post', body: '{"a":1}' }));
    expect(parsed).toMatchObject({
      ok: true,
      request: { method: 'POST', body: '{"a":1}', url: 'https://api.example.com/pets/42' },
    });
  });

  it('rejects non-object payloads', () => {
    expect(parseRelayEnvelope(null)).toMatchObject({ ok: false });
    expect(parseRelayEnvelope('hi')).toMatchObject({ ok: false });
    expect(parseRelayEnvelope([1])).toMatchObject({ ok: false });
  });

  it('rejects missing or relative URLs', () => {
    expect(parseRelayEnvelope(envelope({ url: undefined }))).toMatchObject({ ok: false });
    expect(parseRelayEnvelope(envelope({ url: '/pets' }))).toMatchObject({ ok: false });
  });

  it('rejects non-http(s) schemes', () => {
    for (const url of ['ftp://example.com/x', 'file:///etc/passwd', 'gopher://example.com']) {
      expect(parseRelayEnvelope(envelope({ url }))).toMatchObject({ ok: false });
    }
  });

  it('rejects tunneling and diagnostic methods', () => {
    for (const method of ['CONNECT', 'TRACE', 'TRACK', 'trace']) {
      expect(parseRelayEnvelope(envelope({ method }))).toMatchObject({ ok: false });
    }
  });

  it('rejects malformed methods', () => {
    for (const method of ['GE T', 'GET\r\nHost: evil', '', 'X'.repeat(21), 7]) {
      expect(parseRelayEnvelope(envelope({ method }))).toMatchObject({ ok: false });
    }
  });

  it('rejects header injection attempts', () => {
    expect(
      parseRelayEnvelope(envelope({ headers: { 'X-Bad\r\nHost': 'x' } }))
    ).toMatchObject({ ok: false });
    expect(
      parseRelayEnvelope(envelope({ headers: { 'X-Bad': 'a\r\nHost: evil' } }))
    ).toMatchObject({ ok: false });
    expect(parseRelayEnvelope(envelope({ headers: { 'X-Bad': 42 } }))).toMatchObject({
      ok: false,
    });
  });

  it('rejects request bodies over the cap', () => {
    const body = 'x'.repeat(MAX_REQUEST_BODY_BYTES + 1);
    expect(parseRelayEnvelope(envelope({ body }))).toMatchObject({ ok: false });
  });

  it('rejects bad target kinds and non-boolean confirmations', () => {
    expect(parseRelayEnvelope(envelope({ target: { kind: 'other' } }))).toMatchObject({
      ok: false,
    });
    expect(
      parseRelayEnvelope(envelope({ target: { kind: 'custom', customHostConfirmed: 'yes' } }))
    ).toMatchObject({ ok: false });
  });

  it('rejects missing context slugs', () => {
    expect(parseRelayEnvelope(envelope({ context: {} }))).toMatchObject({ ok: false });
    expect(
      parseRelayEnvelope(envelope({ context: { tenantSlug: 'a', projectSlug: 'b' } }))
    ).toMatchObject({ ok: false });
  });
});

describe('isBlockedIp', () => {
  it.each([
    '127.0.0.1',
    '127.255.255.254',
    '10.0.0.1',
    '10.255.255.255',
    '172.16.0.1',
    '172.31.255.255',
    '192.168.0.1',
    '192.168.255.255',
    '169.254.169.254', // cloud metadata
    '169.254.0.1',
    '100.100.100.200', // Alibaba metadata (CGNAT range)
    '100.64.0.1',
    '0.0.0.0',
    '192.0.0.8',
    '198.18.0.1',
    '224.0.0.1',
    '255.255.255.255',
  ])('blocks IPv4 %s', (ip) => {
    expect(isBlockedIp(ip)).toBe(true);
  });

  it.each(['8.8.8.8', '1.1.1.1', '93.184.216.34', '172.32.0.1', '100.128.0.1', '169.253.1.1'])(
    'allows public IPv4 %s',
    (ip) => {
      expect(isBlockedIp(ip)).toBe(false);
    }
  );

  it.each([
    '::1',
    '::',
    'fe80::1',
    'fe80::1%eth0',
    'fc00::1',
    'fd12:3456::1',
    'fec0::1',
    'ff02::1',
    '::ffff:10.0.0.1', // mapped RFC1918
    '::ffff:169.254.169.254', // mapped metadata
    '64:ff9b::a00:1', // NAT64-embedded 10.0.0.1
    '2002:a00:1::', // 6to4-embedded 10.0.0.1
    '[::1]', // bracketed, as URL hostnames arrive
  ])('blocks IPv6 %s', (ip) => {
    expect(isBlockedIp(ip)).toBe(true);
  });

  it.each(['2606:4700::1111', '::ffff:8.8.8.8', '2400:cb00::1'])(
    'allows public IPv6 %s',
    (ip) => {
      expect(isBlockedIp(ip)).toBe(false);
    }
  );

  it('blocks unparseable input (fail closed)', () => {
    expect(isBlockedIp('not-an-ip')).toBe(true);
    expect(isBlockedIp('1.2.3.4.5')).toBe(true);
    expect(isBlockedIp('::gggg')).toBe(true);
    expect(isBlockedIp('1::2::3')).toBe(true);
  });
});

describe('serverUrlWithDefaults / deriveAllowedSpecOrigins', () => {
  it('substitutes variable defaults and first enum values', () => {
    expect(
      serverUrlWithDefaults('https://{env}.example.com/{base}', {
        env: { default: 'api' },
        base: { enum: ['v1', 'v2'] },
      })
    ).toBe('https://api.example.com/v1');
  });

  it('leaves unresolvable variables in place', () => {
    expect(serverUrlWithDefaults('https://{env}.example.com', {})).toBe(
      'https://{env}.example.com'
    );
    expect(serverUrlWithDefaults('https://{env}.example.com', null)).toBe(
      'https://{env}.example.com'
    );
  });

  it('derives unique origins and skips unusable rows', () => {
    expect(
      deriveAllowedSpecOrigins([
        { url: 'https://api.example.com/v1' },
        { url: 'https://api.example.com/v2' }, // same origin
        { url: 'https://{env}.example.com', variables: { env: { default: 'staging' } } },
        { url: 'https://{env}.example.com', variables: null }, // unresolved template
        { url: '/relative' },
        { url: 'ftp://files.example.com' },
        { url: '' },
      ])
    ).toEqual(['https://api.example.com', 'https://staging.example.com']);
  });
});

describe('checkTargetAllowed', () => {
  const policy: RelayPolicy = {
    mockOrigin: 'http://mock.example.com',
    specOrigins: ['https://api.example.com'],
  };

  it('allows mock targets matching the mock origin', () => {
    expect(
      checkTargetAllowed('http://mock.example.com/acme/petstore/1.2/pets', { kind: 'mock' }, policy)
    ).toEqual({ allowed: true });
  });

  it('refuses mock targets when the mock is disabled or the origin differs', () => {
    expect(
      checkTargetAllowed('http://mock.example.com/x', { kind: 'mock' }, openPolicy)
    ).toMatchObject({ allowed: false });
    expect(
      checkTargetAllowed('http://other.example.com/x', { kind: 'mock' }, policy)
    ).toMatchObject({ allowed: false });
  });

  it('allows spec targets only for declared origins', () => {
    expect(checkTargetAllowed('https://api.example.com/pets', { kind: 'spec' }, policy)).toEqual({
      allowed: true,
    });
    expect(
      checkTargetAllowed('https://evil.example.com/pets', { kind: 'spec' }, policy)
    ).toMatchObject({ allowed: false });
    // Same host, different port/scheme is a different origin.
    expect(
      checkTargetAllowed('http://api.example.com/pets', { kind: 'spec' }, policy)
    ).toMatchObject({ allowed: false });
  });

  it('allows custom targets only with explicit confirmation', () => {
    expect(
      checkTargetAllowed(
        'https://anything.example.com/x',
        { kind: 'custom', customHostConfirmed: true },
        policy
      )
    ).toEqual({ allowed: true });
    expect(
      checkTargetAllowed('https://anything.example.com/x', { kind: 'custom' }, policy)
    ).toMatchObject({ allowed: false });
  });
});

describe('header hygiene', () => {
  it('strips cookies and transport headers from requests and pins identity encoding', () => {
    const clean = sanitizeRequestHeaders({
      Cookie: 'session=secret',
      Host: 'evil.example.com',
      'Content-Length': '999',
      'Transfer-Encoding': 'chunked',
      'Accept-Encoding': 'gzip',
      'Proxy-Authorization': 'Basic xxx',
      'Content-Type': 'application/json',
      Authorization: 'Bearer token',
      'X-Trace': 'abc',
    });
    expect(clean).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer token',
      'X-Trace': 'abc',
      'accept-encoding': 'identity',
    });
  });

  it('strips credential headers for cross-origin redirects', () => {
    expect(
      stripSensitiveHeaders({
        Authorization: 'Bearer token',
        'X-API-Key': 'k',
        'x-auth-token': 't',
        'X-Trace': 'abc',
      })
    ).toEqual({ 'X-Trace': 'abc' });
  });

  it('strips Set-Cookie from responses and joins multi-valued headers', () => {
    expect(
      sanitizeResponseHeaders({
        'set-cookie': ['a=1', 'b=2'],
        'Set-Cookie2': 'c=3',
        vary: ['Accept', 'Origin'],
        'content-type': 'application/json',
        empty: undefined,
      })
    ).toEqual({ vary: 'Accept, Origin', 'content-type': 'application/json' });
  });
});

describe('executeRelay', () => {
  it('relays an allowed request and returns the envelope with timing and size', async () => {
    let time = 1000;
    const httpRequest = vi.fn(async () => {
      time += 120;
      return httpResponse();
    });
    const outcome = await executeRelay(
      relayRequest({ headers: { Cookie: 'secret', 'X-Trace': 'abc' } }),
      openPolicy,
      fakeDeps(httpRequest, { now: () => time })
    );
    expect(outcome).toEqual({
      kind: 'response',
      envelope: {
        status: 200,
        statusText: 'OK',
        headers: { 'content-type': 'application/json' },
        body: '{"ok":true}',
        durationMs: 120,
        sizeBytes: 11,
        truncated: false,
      },
    });
    // Cookie never reaches the target; the trace header does.
    const sentHeaders = httpRequest.mock.calls[0][1].headers;
    expect(sentHeaders).not.toHaveProperty('Cookie');
    expect(sentHeaders).toMatchObject({ 'X-Trace': 'abc' });
  });

  it('refuses targets failing the allow-policy without touching the network', async () => {
    const httpRequest = vi.fn();
    const outcome = await executeRelay(
      relayRequest({ target: { kind: 'custom' } }), // unconfirmed
      openPolicy,
      fakeDeps(httpRequest)
    );
    expect(outcome).toMatchObject({ kind: 'refused' });
    expect(httpRequest).not.toHaveBeenCalled();
  });

  it('refuses literal metadata, RFC1918, and loopback IP targets', async () => {
    const httpRequest = vi.fn();
    for (const host of ['169.254.169.254', '10.0.0.5', '127.0.0.1', '[::1]', '192.168.1.10']) {
      const outcome = await executeRelay(
        relayRequest({ url: `http://${host}/latest/meta-data/` }),
        openPolicy,
        fakeDeps(httpRequest)
      );
      expect(outcome).toMatchObject({ kind: 'refused', detail: expect.stringContaining('SSRF') });
    }
    expect(httpRequest).not.toHaveBeenCalled();
  });

  it('refuses hostnames whose resolved addresses include a blocked IP', async () => {
    const httpRequest = vi.fn();
    const outcome = await executeRelay(
      relayRequest({ url: 'https://rebind.example.com/x' }),
      openPolicy,
      fakeDeps(httpRequest, {
        resolve: vi.fn(async () => ['93.184.216.34', '169.254.169.254']),
      })
    );
    expect(outcome).toMatchObject({ kind: 'refused', detail: expect.stringContaining('SSRF') });
    expect(httpRequest).not.toHaveBeenCalled();
  });

  it('returns a 502 gateway envelope when the host does not resolve', async () => {
    const outcome = await executeRelay(
      relayRequest({ url: 'https://nxdomain.example.com/x' }),
      openPolicy,
      fakeDeps(vi.fn(), { resolve: vi.fn(async () => Promise.reject(new Error('ENOTFOUND'))) })
    );
    expect(outcome).toMatchObject({
      kind: 'response',
      envelope: { status: 502, body: expect.stringContaining('Could not resolve') },
    });
  });

  it('treats a connect-time SSRF block (DNS rebinding defense) as a refusal', async () => {
    const blocked = Object.assign(new Error('blocked'), { code: SSRF_BLOCKED_CODE });
    const outcome = await executeRelay(
      relayRequest(),
      openPolicy,
      fakeDeps(vi.fn(async () => Promise.reject(blocked)))
    );
    expect(outcome).toMatchObject({ kind: 'refused', detail: expect.stringContaining('SSRF') });
  });

  it('returns a 502 gateway envelope for connection failures', async () => {
    const outcome = await executeRelay(
      relayRequest(),
      openPolicy,
      fakeDeps(vi.fn(async () => Promise.reject(new Error('connect ECONNREFUSED'))))
    );
    expect(outcome).toMatchObject({
      kind: 'response',
      envelope: { status: 502, statusText: 'Bad Gateway', truncated: false },
    });
  });

  it('truncates bodies at the cap with a truncated flag', async () => {
    const big = 'x'.repeat(700);
    const outcome = await executeRelay(
      relayRequest(),
      openPolicy,
      fakeDeps(
        vi.fn(async () => httpResponse({ body: bodyStream([big, big]) })),
        { maxBodyBytes: 1000 }
      )
    );
    expect(outcome).toMatchObject({
      kind: 'response',
      envelope: { status: 200, sizeBytes: 1000, truncated: true },
    });
    if (outcome.kind === 'response') {
      expect(outcome.envelope.body).toHaveLength(1000);
    }
  });

  it('does not flag bodies that end exactly at the cap', async () => {
    const outcome = await executeRelay(
      relayRequest(),
      openPolicy,
      fakeDeps(
        vi.fn(async () => httpResponse({ body: bodyStream(['x'.repeat(1000)]) })),
        { maxBodyBytes: 1000 }
      )
    );
    expect(outcome).toMatchObject({
      kind: 'response',
      envelope: { sizeBytes: 1000, truncated: false },
    });
  });

  it('aborts at the time budget and returns a 504 gateway envelope', async () => {
    const httpRequest: RelayHttpRequest = (_url, init) =>
      new Promise((_resolvePromise, rejectPromise) => {
        init.signal.addEventListener('abort', () => rejectPromise(new Error('aborted')));
      });
    const outcome = await executeRelay(
      relayRequest(),
      openPolicy,
      fakeDeps(httpRequest, { timeoutMs: 25 })
    );
    expect(outcome).toMatchObject({
      kind: 'response',
      envelope: { status: 504, statusText: 'Gateway Timeout' },
    });
  });

  it('flags the body as truncated when the stream aborts mid-read', async () => {
    const body: RelayHttpResponse['body'] = {
      async *[Symbol.asyncIterator]() {
        yield new TextEncoder().encode('partial');
        throw new Error('aborted');
      },
    };
    const outcome = await executeRelay(
      relayRequest(),
      openPolicy,
      fakeDeps(vi.fn(async () => httpResponse({ body })))
    );
    expect(outcome).toMatchObject({
      kind: 'response',
      envelope: { body: 'partial', truncated: true },
    });
  });

  it('follows redirects and re-checks the SSRF guard on every hop', async () => {
    const destroy = vi.fn();
    const httpRequest = vi.fn(async () =>
      httpResponse({
        statusCode: 302,
        headers: { location: 'http://internal.example.com/admin' },
        body: bodyStream([], destroy),
      })
    );
    const resolve = vi.fn(async (hostname: string) =>
      hostname === 'internal.example.com' ? ['10.0.0.7'] : ['93.184.216.34']
    );
    const outcome = await executeRelay(
      relayRequest(),
      openPolicy,
      fakeDeps(httpRequest, { resolve })
    );
    expect(outcome).toMatchObject({ kind: 'refused', detail: expect.stringContaining('SSRF') });
    expect(httpRequest).toHaveBeenCalledTimes(1);
    expect(destroy).toHaveBeenCalled();
  });

  it('rewrites 303 redirects to GET, drops the body, and strips credentials cross-origin', async () => {
    const calls: { url: string; method: string; headers: Record<string, string>; body: string | null }[] = [];
    const httpRequest: RelayHttpRequest = async (url, init) => {
      calls.push({ url, method: init.method, headers: init.headers, body: init.body });
      if (calls.length === 1) {
        return httpResponse({
          statusCode: 303,
          headers: { location: 'https://other.example.com/created' },
          body: bodyStream([]),
        });
      }
      return httpResponse({ body: bodyStream(['done']) });
    };
    const outcome = await executeRelay(
      relayRequest({
        method: 'POST',
        body: '{"a":1}',
        headers: { Authorization: 'Bearer t', 'Content-Type': 'application/json', 'X-Trace': 'z' },
      }),
      openPolicy,
      fakeDeps(httpRequest)
    );
    expect(outcome).toMatchObject({ kind: 'response', envelope: { status: 200, body: 'done' } });
    expect(calls).toHaveLength(2);
    expect(calls[1]).toMatchObject({
      url: 'https://other.example.com/created',
      method: 'GET',
      body: null,
    });
    expect(calls[1].headers).not.toHaveProperty('Authorization');
    expect(calls[1].headers).not.toHaveProperty('Content-Type');
    expect(calls[1].headers).toMatchObject({ 'X-Trace': 'z' });
  });

  it('keeps method and body on 307 redirects within the same origin', async () => {
    const calls: { method: string; body: string | null; headers: Record<string, string> }[] = [];
    const httpRequest: RelayHttpRequest = async (_url, init) => {
      calls.push({ method: init.method, body: init.body, headers: init.headers });
      if (calls.length === 1) {
        return httpResponse({
          statusCode: 307,
          headers: { location: '/v2/pets' },
          body: bodyStream([]),
        });
      }
      return httpResponse();
    };
    await executeRelay(
      relayRequest({ method: 'POST', body: '{"a":1}', headers: { Authorization: 'Bearer t' } }),
      openPolicy,
      fakeDeps(httpRequest)
    );
    expect(calls[1]).toMatchObject({ method: 'POST', body: '{"a":1}' });
    expect(calls[1].headers).toMatchObject({ Authorization: 'Bearer t' });
  });

  it('refuses redirects to non-http(s) schemes', async () => {
    const httpRequest = vi.fn(async () =>
      httpResponse({
        statusCode: 302,
        headers: { location: 'file:///etc/passwd' },
        body: bodyStream([]),
      })
    );
    const outcome = await executeRelay(relayRequest(), openPolicy, fakeDeps(httpRequest));
    expect(outcome).toMatchObject({ kind: 'refused' });
  });

  it('relays the final 3xx once the redirect cap is reached', async () => {
    const httpRequest = vi.fn(async () =>
      httpResponse({
        statusCode: 302,
        headers: { location: 'https://api.example.com/loop' },
        body: bodyStream(['moved']),
      })
    );
    const outcome = await executeRelay(
      relayRequest(),
      openPolicy,
      fakeDeps(httpRequest, { maxRedirects: 2 })
    );
    expect(outcome).toMatchObject({ kind: 'response', envelope: { status: 302, body: 'moved' } });
    expect(httpRequest).toHaveBeenCalledTimes(3);
  });

  it('exempts the operator-configured mock origin from the IP guard', async () => {
    const httpRequest = vi.fn(async () => httpResponse({ body: bodyStream(['mocked']) }));
    const resolve = vi.fn(async () => ['127.0.0.1']);
    const policy: RelayPolicy = { mockOrigin: 'http://localhost:8775', specOrigins: [] };
    const outcome = await executeRelay(
      relayRequest({
        url: 'http://localhost:8775/acme/petstore/1.2/pets',
        target: { kind: 'mock' },
      }),
      policy,
      fakeDeps(httpRequest, { resolve })
    );
    expect(outcome).toMatchObject({ kind: 'response', envelope: { status: 200, body: 'mocked' } });
    // No DNS pre-check ran and the unguarded connection path was requested.
    expect(resolve).not.toHaveBeenCalled();
    expect(httpRequest.mock.calls[0][1].ipGuard).toBe(false);
  });

  it('re-applies the IP guard when the mock redirects away from its origin', async () => {
    const httpRequest = vi.fn(async () =>
      httpResponse({
        statusCode: 302,
        headers: { location: 'http://169.254.169.254/latest/meta-data/' },
        body: bodyStream([]),
      })
    );
    const policy: RelayPolicy = { mockOrigin: 'http://localhost:8775', specOrigins: [] };
    const outcome = await executeRelay(
      relayRequest({ url: 'http://localhost:8775/acme/petstore/1.2/pets', target: { kind: 'mock' } }),
      policy,
      fakeDeps(httpRequest)
    );
    expect(outcome).toMatchObject({ kind: 'refused', detail: expect.stringContaining('SSRF') });
  });

  it('never leaks Set-Cookie back to the browser', async () => {
    const outcome = await executeRelay(
      relayRequest(),
      openPolicy,
      fakeDeps(
        vi.fn(async () =>
          httpResponse({
            headers: { 'set-cookie': ['sid=secret'], 'content-type': 'text/plain' },
            body: bodyStream(['ok']),
          })
        )
      )
    );
    expect(outcome).toMatchObject({
      kind: 'response',
      envelope: { headers: { 'content-type': 'text/plain' } },
    });
    if (outcome.kind === 'response') {
      expect(outcome.envelope.headers).not.toHaveProperty('set-cookie');
    }
  });
});

describe('statusTextFor', () => {
  it('maps common codes and falls back to an empty string', () => {
    expect(statusTextFor(200)).toBe('OK');
    expect(statusTextFor(504)).toBe('Gateway Timeout');
    expect(statusTextFor(299)).toBe('');
  });
});
