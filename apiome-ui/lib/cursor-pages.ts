/**
 * Reading one page of a keyset-paged REST list (DBP-1.13, #7196).
 *
 * apiome-rest's list endpoints page by an opaque `cursor`: a page says whether another follows
 * (`has_more`) and where it starts (`next_cursor`), and counts the matches only when the request
 * sets `include_total` — and then only up to {@link TOTAL_CAP}. Envelopes come in two casings
 * (`has_more` / `hasMore`), and a few endpoints still page by `offset` and always report a `total`.
 * This module is the one place the app reads either, so a screen never decides "is there more?"
 * from a count it may not have been given.
 *
 * Pure and dependency-free: the BFF routes use it to forward the paging parameters, and the
 * screens (through `useCursorPages`) use it to read the answer.
 */

/** `include_total` stops counting here; a total equal to the cap means "at least this many". */
export const TOTAL_CAP = 10_000;

/** The longest cursor apiome-rest issues or accepts. */
export const MAX_CURSOR_LENGTH = 2048;

/** The paging fields of a snake_case list envelope. */
export interface SnakeCasePageEnvelope {
  /** Whether a further page exists. */
  has_more?: boolean | null;
  /** The cursor of the next page; null on the last page. */
  next_cursor?: string | null;
  /** The matches, when the request asked for them; otherwise null. */
  total?: number | null;
}

/** The paging fields of a camelCase list envelope. */
export interface CamelCasePageEnvelope {
  /** Whether a further page exists. */
  hasMore?: boolean | null;
  /** The cursor of the next page; null on the last page. */
  nextCursor?: string | null;
  /** The matches, when the request asked for them; otherwise null. */
  total?: number | null;
}

/** Either casing of a list envelope's paging fields. */
export type PageEnvelope = SnakeCasePageEnvelope & CamelCasePageEnvelope;

/** What one page says about the list around it. */
export interface PageInfo {
  /** Whether the server said a further page exists. False when it said nothing. */
  hasMore: boolean;
  /** The cursor of the next page, or null. */
  nextCursor: string | null;
  /** The matches, or null when the server did not count them. */
  total: number | null;
  /**
   * Whether the server reported `has_more` at all. An endpoint that has not moved to cursors
   * reports only a `total`; see {@link hasMoreAfter}.
   */
  reported: boolean;
}

/** A page that says nothing: no more, no cursor, no count. */
export const EMPTY_PAGE_INFO: PageInfo = {
  hasMore: false,
  nextCursor: null,
  total: null,
  reported: false,
};

/**
 * Read the paging fields of a list response, in either casing.
 *
 * @param body - The parsed response body (or anything else; a non-object reads as an empty page).
 * @returns What the page says about the rest of the list.
 */
export function readPage(body: unknown): PageInfo {
  if (!body || typeof body !== 'object') return EMPTY_PAGE_INFO;
  const source = body as PageEnvelope;
  const rawMore = typeof source.has_more === 'boolean' ? source.has_more : source.hasMore;
  const rawCursor = typeof source.next_cursor === 'string' ? source.next_cursor : source.nextCursor;
  const total =
    typeof source.total === 'number' && Number.isFinite(source.total) && source.total >= 0
      ? source.total
      : null;
  return {
    hasMore: rawMore === true,
    nextCursor: typeof rawCursor === 'string' && rawCursor.length > 0 ? rawCursor : null,
    total,
    reported: typeof rawMore === 'boolean',
  };
}

/**
 * Whether rows remain after the ones already read.
 *
 * The server's own `has_more` whenever it gave one. Only an endpoint that still pages by offset
 * (no `has_more` in its answer) falls back to comparing its `total` with what has been read.
 *
 * @param page - The latest page's paging fields.
 * @param loaded - How many rows have been read up to and including that page.
 * @returns True when another page can be asked for.
 */
export function hasMoreAfter(page: PageInfo, loaded: number): boolean {
  if (page.reported) return page.hasMore;
  return page.total !== null && loaded < page.total;
}

/** Where a request starts and whether it asks for the count. */
export interface PageRequest {
  /** The previous page's `next_cursor`; null or absent for the first page. */
  cursor?: string | null;
  /** Rows already read — sent as `offset` only when there is no cursor to continue from. */
  offset?: number;
  /** Ask the server to count the matches (up to {@link TOTAL_CAP}). */
  includeTotal?: boolean;
}

/**
 * Add the paging parameters of one request to its query.
 *
 * A cursor wins: `offset` is the deprecated fallback for an endpoint that issued no cursor, and it
 * is never sent beside one.
 *
 * @param params - The query being built; changed in place.
 * @param request - Where the page starts and whether to count.
 * @returns The same `params`, for chaining.
 */
export function setPageParams(params: URLSearchParams, request: PageRequest): URLSearchParams {
  params.delete('cursor');
  params.delete('offset');
  if (request.cursor) {
    params.set('cursor', request.cursor);
  } else if (request.offset && request.offset > 0) {
    params.set('offset', String(Math.trunc(request.offset)));
  }
  if (request.includeTotal) params.set('include_total', 'true');
  else params.delete('include_total');
  return params;
}

/**
 * Forward a browser request's `cursor` and `include_total` to apiome-rest.
 *
 * For the BFF routes that allow-list their query: a cursor is opaque, so it is passed through
 * untouched (bounded in length — the server refuses longer ones), and `include_total` is forwarded
 * only as the literal `true`.
 *
 * @param input - The incoming query.
 * @param out - The upstream query being built; changed in place.
 * @returns The same `out`, for chaining.
 */
export function forwardPageParams(
  input: Pick<URLSearchParams, 'get'>,
  out: URLSearchParams,
): URLSearchParams {
  const cursor = input.get('cursor');
  if (cursor && cursor.length <= MAX_CURSOR_LENGTH) out.set('cursor', cursor);
  if (input.get('include_total') === 'true') out.set('include_total', 'true');
  return out;
}

/**
 * A count, as a screen shows it.
 *
 * @param total - The count, or null/undefined when the server did not give one.
 * @returns `1,234`; `10,000+` at the counting cap; null when unknown, so the caller shows nothing
 *   rather than a zero it was never told.
 */
export function formatTotal(total: number | null | undefined): string | null {
  if (typeof total !== 'number' || !Number.isFinite(total) || total < 0) return null;
  if (total >= TOTAL_CAP) return `${TOTAL_CAP.toLocaleString('en-US')}+`;
  return total.toLocaleString('en-US');
}

/**
 * The `Showing 26–50 of 240 runs` sentence of a list paged by cursor.
 *
 * The same phrasing as `dataTableRangeLabel`, for a list whose count may be unknown (`Showing
 * 26–50`) or capped (`of 10,000+ runs`).
 *
 * @param first - Zero-based index of the first row shown.
 * @param shown - How many rows are shown.
 * @param total - The matches, or null when not counted.
 * @param noun - What one row is, singular.
 * @returns The sentence, or `No <noun>s` when nothing is shown.
 */
export function cursorRangeLabel(
  first: number,
  shown: number,
  total: number | null | undefined,
  noun = 'row',
): string {
  if (shown <= 0) return `No ${noun}s`;
  const from = (first + 1).toLocaleString('en-US');
  const to = (first + shown).toLocaleString('en-US');
  const count = formatTotal(total);
  if (count === null) return `Showing ${from}–${to}`;
  return `Showing ${from}–${to} of ${count} ${total === 1 ? noun : `${noun}s`}`;
}
