import { describe, expect, it, vi } from 'vitest';
import {
  isSameOrigin,
  sendTryIt,
  TryItSendError,
  type TryItRequest,
} from '../send';

const PAGE_ORIGIN = 'https://browse.example.com';

const request = (over: Partial<TryItRequest> = {}): TryItRequest => ({
  method: 'GET',
  url: 'https://mock.example.com/acme/petstore/1.2/pets/42',
  headers: { 'X-Trace': 'abc' },
  body: null,
  target: { kind: 'mock' },
  context: { tenantSlug: 'acme', projectSlug: 'petstore', versionSlug: '1.2' },
  ...over,
});

/** Fetch stub capturing its invocation and returning a canned response. */
function fetchStub(response: Response) {
  const calls: { input: RequestInfo | URL; init?: RequestInit }[] = [];
  const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ input, init });
    return response;
  });
  return { impl: impl as unknown as typeof fetch, calls };
}

describe('isSameOrigin', () => {
  it('matches only the exact page origin', () => {
    expect(isSameOrigin(`${PAGE_ORIGIN}/x`, PAGE_ORIGIN)).toBe(true);
    expect(isSameOrigin('https://other.example.com/x', PAGE_ORIGIN)).toBe(false);
    expect(isSameOrigin('http://browse.example.com/x', PAGE_ORIGIN)).toBe(false);
    expect(isSameOrigin('not a url', PAGE_ORIGIN)).toBe(false);
  });
});

describe('sendTryIt — direct path (same-origin)', () => {
  it('fetches the target directly and normalizes the response', async () => {
    const { impl, calls } = fetchStub(
      new Response('{"ok":true}', {
        status: 201,
        statusText: 'Created',
        headers: { 'content-type': 'application/json' },
      })
    );
    let tick = 1000;
    const result = await sendTryIt(
      request({ url: `${PAGE_ORIGIN}/local/thing`, method: 'POST', body: '{"a":1}' }),
      { pageOrigin: PAGE_ORIGIN, fetchImpl: impl, now: () => (tick += 25) }
    );
    expect(calls).toHaveLength(1);
    expect(calls[0].input).toBe(`${PAGE_ORIGIN}/local/thing`);
    expect(calls[0].init).toMatchObject({ method: 'POST', body: '{"a":1}' });
    expect(result).toMatchObject({
      status: 201,
      statusText: 'Created',
      bodyText: '{"ok":true}',
      sizeBytes: 11,
      truncated: false,
      via: 'direct',
    });
    expect(result.durationMs).toBe(25);
    expect(result.headers['content-type']).toBe('application/json');
  });

  it('wraps network failures in a TryItSendError', async () => {
    const impl = (async () => {
      throw new TypeError('Failed to fetch');
    }) as unknown as typeof fetch;
    await expect(
      sendTryIt(request({ url: `${PAGE_ORIGIN}/x` }), { pageOrigin: PAGE_ORIGIN, fetchImpl: impl })
    ).rejects.toMatchObject({ name: 'TryItSendError', kind: 'network' });
  });
});

describe('sendTryIt — proxy path (cross-origin)', () => {
  it('POSTs the SIM-3.2 envelope to /api/try-it and unwraps the reply', async () => {
    const { impl, calls } = fetchStub(
      new Response(
        JSON.stringify({
          status: 200,
          statusText: 'OK',
          headers: { 'content-type': 'application/json' },
          body: '{"name":"Rex"}',
          durationMs: 12,
          sizeBytes: 14,
          truncated: false,
        }),
        { status: 200 }
      )
    );
    const req = request({ method: 'POST', body: '{"name":"Rex"}' });
    const result = await sendTryIt(req, { pageOrigin: PAGE_ORIGIN, fetchImpl: impl });

    expect(calls[0].input).toBe('/api/try-it');
    const sent = JSON.parse(String(calls[0].init?.body));
    expect(sent).toEqual({
      url: req.url,
      method: 'POST',
      headers: { 'X-Trace': 'abc' },
      body: '{"name":"Rex"}',
      target: { kind: 'mock' },
      context: { tenantSlug: 'acme', projectSlug: 'petstore', versionSlug: '1.2' },
    });
    expect(result).toMatchObject({
      status: 200,
      bodyText: '{"name":"Rex"}',
      durationMs: 12,
      sizeBytes: 14,
      via: 'proxy',
    });
  });

  it('forwards custom-host confirmation in the envelope', async () => {
    const { impl, calls } = fetchStub(
      new Response(JSON.stringify({ status: 204, body: '' }), { status: 200 })
    );
    await sendTryIt(
      request({ target: { kind: 'custom', customHostConfirmed: true } }),
      { pageOrigin: PAGE_ORIGIN, fetchImpl: impl }
    );
    expect(JSON.parse(String(calls[0].init?.body)).target).toEqual({
      kind: 'custom',
      customHostConfirmed: true,
    });
  });

  it('maps a missing relay route (404/405) to proxy-unavailable', async () => {
    for (const status of [404, 405]) {
      const { impl } = fetchStub(new Response('nope', { status }));
      await expect(
        sendTryIt(request(), { pageOrigin: PAGE_ORIGIN, fetchImpl: impl })
      ).rejects.toMatchObject({ kind: 'proxy-unavailable' });
    }
  });

  it('surfaces relay refusals (403) with the problem detail', async () => {
    const { impl } = fetchStub(
      new Response(JSON.stringify({ detail: 'Target host not allowed.' }), { status: 403 })
    );
    await expect(
      sendTryIt(request(), { pageOrigin: PAGE_ORIGIN, fetchImpl: impl })
    ).rejects.toMatchObject({ kind: 'refused', message: 'Target host not allowed.' });
  });

  it('falls back to a generic refusal message when the 403 body is not JSON', async () => {
    const { impl } = fetchStub(new Response('forbidden', { status: 403 }));
    await expect(
      sendTryIt(request(), { pageOrigin: PAGE_ORIGIN, fetchImpl: impl })
    ).rejects.toMatchObject({ kind: 'refused', message: 'The Try It relay refused this target.' });
  });

  it('rejects malformed relay replies and other relay errors as bad-envelope', async () => {
    const { impl: notJson } = fetchStub(new Response('<html>', { status: 200 }));
    await expect(
      sendTryIt(request(), { pageOrigin: PAGE_ORIGIN, fetchImpl: notJson })
    ).rejects.toMatchObject({ kind: 'bad-envelope' });

    const { impl: noStatus } = fetchStub(
      new Response(JSON.stringify({ body: 'x' }), { status: 200 })
    );
    await expect(
      sendTryIt(request(), { pageOrigin: PAGE_ORIGIN, fetchImpl: noStatus })
    ).rejects.toMatchObject({ kind: 'bad-envelope' });

    const { impl: serverError } = fetchStub(new Response('boom', { status: 500 }));
    await expect(
      sendTryIt(request(), { pageOrigin: PAGE_ORIGIN, fetchImpl: serverError })
    ).rejects.toMatchObject({ kind: 'bad-envelope' });
  });

  it('fills envelope defaults for missing optional fields', async () => {
    const { impl } = fetchStub(
      new Response(JSON.stringify({ status: 200, body: 'abcé' }), { status: 200 })
    );
    let tick = 0;
    const result = await sendTryIt(request(), {
      pageOrigin: PAGE_ORIGIN,
      fetchImpl: impl,
      now: () => (tick += 5),
    });
    expect(result.statusText).toBe('');
    expect(result.headers).toEqual({});
    // 'abcé' is 5 bytes in UTF-8.
    expect(result.sizeBytes).toBe(5);
    expect(result.durationMs).toBeGreaterThanOrEqual(0);
    expect(result.truncated).toBe(false);
  });

  it('wraps relay connection failures as network errors', async () => {
    const impl = (async () => {
      throw new TypeError('Failed to fetch');
    }) as unknown as typeof fetch;
    await expect(
      sendTryIt(request(), { pageOrigin: PAGE_ORIGIN, fetchImpl: impl })
    ).rejects.toMatchObject({ kind: 'network' });
  });
});

describe('sendTryIt — validation', () => {
  it('rejects unparseable URLs before dispatch', async () => {
    const { impl, calls } = fetchStub(new Response('x'));
    await expect(
      sendTryIt(request({ url: 'not a url' }), { pageOrigin: PAGE_ORIGIN, fetchImpl: impl })
    ).rejects.toSatisfy(
      (e: unknown) => e instanceof TryItSendError && e.kind === 'invalid-url'
    );
    expect(calls).toHaveLength(0);
  });
});
