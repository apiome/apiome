/**
 * The browser's reader of a revision's OpenAPI document (COA-5.13, #7089).
 *
 * Pinned: the read goes through the `/document` proxy, the text is re-printed with two-space
 * indentation, the digest is remembered per revision and sent back as `If-None-Match`, a `304`
 * returns the cached text without a download, the cache is bounded, and a refusal becomes a
 * `RevisionDocumentError` carrying REST's message and code.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

import {
  DOCUMENT_CACHE_MAX_CHARS,
  DOCUMENT_CACHE_MAX_ENTRIES,
  RevisionDocumentError,
  clearRevisionDocumentCache,
  loadRevisionDocument,
  revisionDocumentHref,
  sameRevisionDocument,
} from '@/app/utils/revision-document';

const PROJECT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const V1 = '11111111-1111-4111-8111-111111111111';
const V2 = '22222222-2222-4222-8222-222222222222';

type Call = { url: string; ifNoneMatch: string | null };
type Reply = { status: number; body?: string; sha256?: string | null };

let calls: Call[] = [];
/** What REST holds per revision id: the compact document and its digest. */
let stored: Record<string, { body: string; sha256: string }> = {};
let override: ((call: Call) => Reply | undefined) | null = null;

function response(reply: Reply) {
  const headers: Record<string, string> = { 'content-type': 'application/json' };
  if (reply.sha256) headers['x-apiome-content-sha256'] = reply.sha256;
  return {
    ok: reply.status >= 200 && reply.status < 300,
    status: reply.status,
    headers: { get: (name: string) => headers[name.toLowerCase()] ?? null },
    text: async () => reply.body ?? '',
    json: async () => JSON.parse(reply.body ?? 'null'),
    body: { cancel: async () => undefined },
  };
}

beforeEach(() => {
  clearRevisionDocumentCache();
  calls = [];
  override = null;
  stored = {
    [V1]: { body: '{"openapi":"3.2.0","info":{"title":"One"}}', sha256: 'sha-one' },
    [V2]: { body: '{"openapi":"3.2.0","info":{"title":"Two"}}', sha256: 'sha-two' },
  };
  global.fetch = jest.fn(async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    const ifNoneMatch =
      (init?.headers as Record<string, string> | undefined)?.['If-None-Match'] ?? null;
    const call = { url, ifNoneMatch };
    calls.push(call);
    const forced = override?.(call);
    if (forced) return response(forced);
    const versionId = /\/api\/versions\/([^/]+)\/document/.exec(url)?.[1] ?? '';
    const held = stored[versionId];
    if (!held)
      return response({ status: 404, body: '{"success":false,"error":"Version not found"}' });
    if (ifNoneMatch === `"${held.sha256}"`) return response({ status: 304, sha256: held.sha256 });
    return response({ status: 200, body: held.body, sha256: held.sha256 });
  }) as unknown as typeof fetch;
});

describe('loadRevisionDocument', () => {
  test('reads through the proxy and re-prints the document with two-space indentation', async () => {
    const document = await loadRevisionDocument(PROJECT, V1);

    expect(calls).toEqual([{ url: revisionDocumentHref(PROJECT, V1), ifNoneMatch: null }]);
    expect(calls[0].url).toBe(`/api/versions/${V1}/document?projectId=${PROJECT}`);
    expect(document).toEqual({
      text: JSON.stringify({ openapi: '3.2.0', info: { title: 'One' } }, null, 2),
      sha256: 'sha-one',
      notModified: false,
    });
  });

  test('revalidates with the remembered digest and serves a 304 from the cache', async () => {
    const first = await loadRevisionDocument(PROJECT, V1);
    const second = await loadRevisionDocument(PROJECT, V1);

    expect(calls[1].ifNoneMatch).toBe('"sha-one"');
    expect(second).toEqual({ text: first.text, sha256: 'sha-one', notModified: true });
  });

  test('downloads again when the revision changed', async () => {
    await loadRevisionDocument(PROJECT, V1);
    stored[V1] = {
      body: '{"openapi":"3.2.0","info":{"title":"One, edited"}}',
      sha256: 'sha-one-b',
    };

    const edited = await loadRevisionDocument(PROJECT, V1);

    expect(calls[1].ifNoneMatch).toBe('"sha-one"');
    expect(edited.notModified).toBe(false);
    expect(edited.sha256).toBe('sha-one-b');
    expect(edited.text).toContain('One, edited');
    // And the new digest is the one sent next time.
    await loadRevisionDocument(PROJECT, V1);
    expect(calls[2].ifNoneMatch).toBe('"sha-one-b"');
  });

  test('two revisions with the same document share one cached text', async () => {
    stored[V2] = { ...stored[V1] };
    const parse = jest.spyOn(JSON, 'parse');
    const one = await loadRevisionDocument(PROJECT, V1);
    const parsedAfterFirst = parse.mock.calls.length;
    const two = await loadRevisionDocument(PROJECT, V2);

    expect(two.text).toBe(one.text);
    expect(sameRevisionDocument(one, two)).toBe(true);
    // The second revision's body is not parsed again: the text is keyed by digest.
    expect(parse.mock.calls.length).toBe(parsedAfterFirst);
    parse.mockRestore();
  });

  test('keeps at most DOCUMENT_CACHE_MAX_ENTRIES documents, least recently used out first', async () => {
    const ids = Array.from({ length: DOCUMENT_CACHE_MAX_ENTRIES + 1 }, (_, i) => `v-${i}`);
    for (const id of ids) stored[id] = { body: `{"n":"${id}"}`, sha256: `sha-${id}` };
    for (const id of ids) await loadRevisionDocument(PROJECT, id);
    calls = [];

    // The first one was evicted: its digest is known but its text is gone, so no validator is sent.
    await loadRevisionDocument(PROJECT, ids[0]);
    expect(calls[0].ifNoneMatch).toBeNull();
    // The newest is still held.
    expect((await loadRevisionDocument(PROJECT, ids[ids.length - 1])).notModified).toBe(true);
  });

  test('does not keep a document larger than the cache', async () => {
    const big = JSON.stringify({ text: 'x'.repeat(DOCUMENT_CACHE_MAX_CHARS) });
    stored[V1] = { body: big, sha256: 'sha-big' };

    const first = await loadRevisionDocument(PROJECT, V1);
    await loadRevisionDocument(PROJECT, V1);

    expect(first.text.length).toBeGreaterThan(DOCUMENT_CACHE_MAX_CHARS);
    expect(calls.map((call) => call.ifNoneMatch)).toEqual([null, null]);
  });

  test('asks again without the validator when the text was evicted before a 304 arrived', async () => {
    await loadRevisionDocument(PROJECT, V1);
    override = (call) => {
      if (call.ifNoneMatch !== '"sha-one"') return undefined;
      clearRevisionDocumentCache();
      return { status: 304, sha256: 'sha-one' };
    };

    const document = await loadRevisionDocument(PROJECT, V1);

    expect(calls.map((call) => call.ifNoneMatch)).toEqual([null, '"sha-one"', null]);
    expect(document.notModified).toBe(false);
    expect(document.text).toContain('"title": "One"');
  });

  test('works without a digest, and then never sends a validator', async () => {
    override = () => ({ status: 200, body: '{"a":1}', sha256: null });

    const first = await loadRevisionDocument(PROJECT, V1);
    await loadRevisionDocument(PROJECT, V1);

    expect(first).toEqual({ text: '{\n  "a": 1\n}', sha256: null, notModified: false });
    expect(calls.map((call) => call.ifNoneMatch)).toEqual([null, null]);
  });
});

describe('a read that fails', () => {
  test("carries REST's message, status and code", async () => {
    override = () => ({
      status: 502,
      body: '{"success":false,"error":"The document store did not return the document.","code":"document-unreadable"}',
    });

    const error = await loadRevisionDocument(PROJECT, V1).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(RevisionDocumentError);
    expect(error).toMatchObject({
      message: 'The document store did not return the document.',
      status: 502,
      code: 'document-unreadable',
    });
  });

  test('names the status when REST sent no message', async () => {
    override = () => ({ status: 500, body: 'null' });
    await expect(loadRevisionDocument(PROJECT, V1)).rejects.toThrow(
      'The document could not be read (HTTP 500).',
    );
  });

  test('says so when the request never completed', async () => {
    global.fetch = jest.fn(async () => {
      throw new TypeError('Failed to fetch');
    }) as unknown as typeof fetch;
    await expect(loadRevisionDocument(PROJECT, V1)).rejects.toMatchObject({
      name: 'RevisionDocumentError',
      status: 0,
      message: 'The document could not be read.',
    });
  });

  test('rethrows an abort as it is, so the caller can ignore it', async () => {
    const abort = Object.assign(new Error('aborted'), { name: 'AbortError' });
    global.fetch = jest.fn(async () => {
      throw abort;
    }) as unknown as typeof fetch;
    await expect(loadRevisionDocument(PROJECT, V1)).rejects.toBe(abort);
  });

  test('refuses a body that is not JSON, and caches nothing', async () => {
    override = () => ({ status: 200, body: '<html>', sha256: 'sha-html' });
    await expect(loadRevisionDocument(PROJECT, V1)).rejects.toThrow(
      'apiome-rest returned a document that is not JSON.',
    );
    override = null;
    await loadRevisionDocument(PROJECT, V1);
    expect(calls[1].ifNoneMatch).toBeNull();
  });
});

describe('sameRevisionDocument', () => {
  test('is true only for two equal digests', () => {
    expect(sameRevisionDocument({ sha256: 'ABC' }, { sha256: 'abc' })).toBe(true);
    expect(sameRevisionDocument({ sha256: 'abc' }, { sha256: 'abd' })).toBe(false);
    // Without a digest the texts must be compared: never "the same".
    expect(sameRevisionDocument({ sha256: null }, { sha256: null })).toBe(false);
    expect(sameRevisionDocument({ sha256: 'abc' }, { sha256: null })).toBe(false);
  });
});
