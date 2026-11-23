/**
 * Read a whole bare-array REST list that the REST API serves one page at a time (#7196).
 *
 * `GET /v1/projects/{tenant}`, `/v1/versions/{tenant}/{project}`, `/v1/catalog/{tenant}` and
 * `/v1/paths/{tenant}/{version}` answer with a JSON array of at most one page and say in the
 * `X-Has-More` / `X-Next-Cursor` response headers whether and where the list continues. The
 * app's own API routes hand whole lists to pickers and tables, so they read through this helper,
 * which follows the cursor until the list ends.
 */

/** Response header that is `true` when another page exists. */
export const HAS_MORE_HEADER = 'X-Has-More';

/** Response header that carries the cursor of the next page. */
export const NEXT_CURSOR_HEADER = 'X-Next-Cursor';

/** The most pages one read follows, so a list that never ends cannot hang a request. */
export const MAX_FOLLOWED_PAGES = 250;

/**
 * The cursor of the page after `response`, or null on the last page.
 *
 * @param response - One page's response.
 * @returns The next page's cursor, or null when the list ends here.
 */
export function nextCursorOf(response: Response): string | null {
  if ((response.headers.get(HAS_MORE_HEADER) ?? '').toLowerCase() !== 'true') {
    return null;
  }
  const cursor = response.headers.get(NEXT_CURSOR_HEADER);
  return cursor && cursor.length > 0 ? cursor : null;
}

/**
 * The URL of a later page: the first page's URL with its `cursor` set.
 *
 * @param url - The first page's URL, with its filters.
 * @param cursor - The cursor to continue from.
 * @returns The URL of the page that starts after `cursor`.
 */
export function pageUrl(url: string, cursor: string): string {
  const [base, query = ''] = url.split('?');
  const params = new URLSearchParams(query);
  params.set('cursor', cursor);
  return `${base}?${params.toString()}`;
}

/**
 * GET a paged bare-array list and return it whole, as one response.
 *
 * The first page's response is returned untouched when it is an error, is not a JSON array, or is
 * the only page, so callers handle status codes and error bodies exactly as they did before. A
 * later page that fails is returned as it is: a partial list is never passed off as the whole one.
 *
 * @param url - The list URL, with its filters.
 * @param init - Request options (method and auth headers); used for every page.
 * @param fetcher - The fetch implementation (replaceable in tests).
 * @returns A response whose JSON body is the whole list.
 */
export async function fetchAllPages(
  url: string,
  init: RequestInit,
  fetcher: typeof fetch = fetch
): Promise<Response> {
  const first = await fetcher(url, init);
  let cursor = first.ok ? nextCursorOf(first) : null;
  if (!cursor) {
    return first;
  }
  const firstBody: unknown = await first.clone().json();
  if (!Array.isArray(firstBody)) {
    return first;
  }
  const rows: unknown[] = [...firstBody];
  for (let page = 1; cursor && page < MAX_FOLLOWED_PAGES; page += 1) {
    const response = await fetcher(pageUrl(url, cursor), init);
    if (!response.ok) {
      return response;
    }
    const body: unknown = await response.clone().json();
    if (!Array.isArray(body) || body.length === 0) {
      break;
    }
    rows.push(...body);
    cursor = nextCursorOf(response);
  }
  return new Response(JSON.stringify(rows), {
    status: first.status,
    headers: { 'Content-Type': 'application/json' },
  });
}
