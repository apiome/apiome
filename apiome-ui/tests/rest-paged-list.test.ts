/**
 * @jest-environment node
 */
import {
  HAS_MORE_HEADER,
  MAX_FOLLOWED_PAGES,
  NEXT_CURSOR_HEADER,
  fetchAllPages,
  nextCursorOf,
  pageUrl,
} from '../lib/rest-paged-list';

const INIT: RequestInit = { method: 'GET', headers: { Authorization: 'Bearer t' } };

function page(rows: unknown, cursor?: string, status = 200): Response {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (cursor) {
    headers[HAS_MORE_HEADER] = 'true';
    headers[NEXT_CURSOR_HEADER] = cursor;
  } else {
    headers[HAS_MORE_HEADER] = 'false';
  }
  return new Response(JSON.stringify(rows), { status, headers });
}

function fetcherOf(pages: Record<string, Response>) {
  const calls: string[] = [];
  const fetcher = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const found = pages[url];
    if (!found) throw new Error(`unexpected request: ${url}`);
    return found;
  }) as unknown as typeof fetch;
  return { fetcher, calls };
}

describe('nextCursorOf', () => {
  it('reads the cursor only when the list says it continues', () => {
    expect(nextCursorOf(page([], 'abc'))).toBe('abc');
    expect(nextCursorOf(page([]))).toBeNull();
    expect(
      nextCursorOf(new Response('[]', { headers: { [NEXT_CURSOR_HEADER]: 'abc' } }))
    ).toBeNull();
    expect(nextCursorOf(new Response('[]', { headers: { [HAS_MORE_HEADER]: 'true' } }))).toBeNull();
  });
});

describe('pageUrl', () => {
  it('adds the cursor and keeps the filters', () => {
    expect(pageUrl('http://rest/v1/projects/acme', 'c 1')).toBe(
      'http://rest/v1/projects/acme?cursor=c+1'
    );
    expect(pageUrl('http://rest/v1/projects/acme?team=pay&cursor=old', 'new')).toBe(
      'http://rest/v1/projects/acme?team=pay&cursor=new'
    );
  });
});

describe('fetchAllPages', () => {
  it('returns a single page untouched', async () => {
    const only = page([{ id: 1 }]);
    const { fetcher, calls } = fetcherOf({ 'http://rest/list': only });
    const response = await fetchAllPages('http://rest/list', INIT, fetcher);
    expect(response).toBe(only);
    expect(calls).toEqual(['http://rest/list']);
  });

  it('follows the cursor to the end and returns the whole list', async () => {
    const { fetcher, calls } = fetcherOf({
      'http://rest/list?team=pay': page([{ id: 1 }, { id: 2 }], 'c1'),
      'http://rest/list?team=pay&cursor=c1': page([{ id: 3 }], 'c2'),
      'http://rest/list?team=pay&cursor=c2': page([{ id: 4 }]),
    });
    const response = await fetchAllPages('http://rest/list?team=pay', INIT, fetcher);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }]);
    expect(calls).toHaveLength(3);
    expect((fetcher as unknown as jest.Mock).mock.calls.every(([, init]) => init === INIT)).toBe(
      true
    );
  });

  it('returns an error response as it is, without following anything', async () => {
    const denied = page({ detail: 'nope' }, 'c1', 403);
    const { fetcher, calls } = fetcherOf({ 'http://rest/list': denied });
    expect(await fetchAllPages('http://rest/list', INIT, fetcher)).toBe(denied);
    expect(calls).toHaveLength(1);
  });

  it('returns a failing later page instead of a partial list', async () => {
    const broken = page({ detail: 'boom' }, undefined, 500);
    const { fetcher } = fetcherOf({
      'http://rest/list': page([{ id: 1 }], 'c1'),
      'http://rest/list?cursor=c1': broken,
    });
    expect(await fetchAllPages('http://rest/list', INIT, fetcher)).toBe(broken);
  });

  it('leaves a body that is not an array alone', async () => {
    const envelope = page({ items: [] }, 'c1');
    const { fetcher, calls } = fetcherOf({ 'http://rest/list': envelope });
    expect(await fetchAllPages('http://rest/list', INIT, fetcher)).toBe(envelope);
    expect(calls).toHaveLength(1);
  });

  it('stops when a cursor leads to an empty page', async () => {
    const { fetcher } = fetcherOf({
      'http://rest/list': page([{ id: 1 }], 'c1'),
      'http://rest/list?cursor=c1': page([], 'c1'),
    });
    const response = await fetchAllPages('http://rest/list', INIT, fetcher);
    expect(await response.json()).toEqual([{ id: 1 }]);
  });

  it('never follows more than the page ceiling', async () => {
    const fetcher = jest.fn(async () => page([{ id: 1 }], 'again')) as unknown as typeof fetch;
    const response = await fetchAllPages('http://rest/list', INIT, fetcher);
    expect((fetcher as unknown as jest.Mock).mock.calls).toHaveLength(MAX_FOLLOWED_PAGES);
    expect(await response.json()).toHaveLength(MAX_FOLLOWED_PAGES);
  });
});
