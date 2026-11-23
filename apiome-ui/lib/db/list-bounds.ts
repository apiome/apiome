/**
 * Bounds and keyset cursors for the UI's direct-SQL lists (DBP-1.13, #7196).
 *
 * No list that grows with tenant data is read unbounded:
 *
 * - A list a screen pages through takes `limit` (at most {@link MAX_LIST_ROWS}) and an opaque
 *   `cursor`, reads `limit + 1` rows, and answers `{ items, hasMore, nextCursor }`. The cursor
 *   names the last row the reader saw, so page 1,000 costs what page 1 costs.
 * - A list no screen pages (a picker, a compatibility read) carries a hard `LIMIT` of
 *   {@link MAX_UNPAGED_ROWS} as a safety bound.
 *
 * The cursor format is the one apiome-rest issues (`apiome-rest/src/app/keyset_pagination.py`):
 * unpadded urlsafe base64 over a small JSON object — `{"t": <ISO timestamp>, "i": <id>}` for a
 * `(timestamp, id)` ordering, `{"k": [...]}` for any other sort key.
 *
 * This module is pure (no pool, no `'use server'`), so client components may import its
 * constants and types.
 */

/** The hard maximum page size of every paged list. */
export const MAX_LIST_ROWS = 200;
/** The page size used when the caller names none. */
export const DEFAULT_LIST_ROWS = 50;
/** The hard cap of a list that is read whole, without paging. */
export const MAX_UNPAGED_ROWS = 1000;

const MAX_CURSOR_LENGTH = 2048;

/** The cursor is not one this service issued for this list. */
export class InvalidCursorError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'InvalidCursorError';
  }
}

/** Paging options every paged list accepts. */
export interface ListPageOptions {
  /** Page size; clamped to `[1, MAX_LIST_ROWS]`, {@link DEFAULT_LIST_ROWS} when omitted. */
  limit?: number;
  /** The previous page's `nextCursor`; omitted or `null` for the first page. */
  cursor?: string | null;
}

/** One page of a keyset-paginated list. */
export interface ListPage<T> {
  /** The rows of this page, at most the requested limit. */
  items: T[];
  /** Whether a further page exists. */
  hasMore: boolean;
  /** The cursor of the next page; `null` on the last page. */
  nextCursor: string | null;
}

/**
 * Resolve a requested page size against the bounds.
 *
 * @param limit The requested size; omitted (or not a finite number) for the default.
 * @param max The largest size allowed.
 * @returns A whole number in `[1, max]`.
 */
export function clampListLimit(limit?: number, max: number = MAX_LIST_ROWS): number {
  const requested =
    typeof limit === 'number' && Number.isFinite(limit) ? Math.trunc(limit) : DEFAULT_LIST_ROWS;
  return Math.max(1, Math.min(requested, Math.trunc(max)));
}

/**
 * Serialise a cursor payload.
 *
 * @param payload The JSON object to carry.
 * @returns Unpadded urlsafe base64.
 */
function encode(payload: Record<string, unknown>): string {
  return Buffer.from(JSON.stringify(payload), 'utf8').toString('base64url');
}

/**
 * Read a cursor payload back.
 *
 * @param token The cursor as the caller sent it.
 * @returns The JSON object it carries.
 * @throws InvalidCursorError The token is empty, too long, not base64url, or not a JSON object.
 */
function decode(token: unknown): Record<string, unknown> {
  const text = typeof token === 'string' ? token.trim() : '';
  if (!text) throw new InvalidCursorError('empty cursor');
  if (text.length > MAX_CURSOR_LENGTH) throw new InvalidCursorError('cursor too long');
  if (!/^[A-Za-z0-9_-]+={0,2}$/.test(text)) throw new InvalidCursorError('invalid base64');
  let payload: unknown;
  try {
    payload = JSON.parse(Buffer.from(text, 'base64url').toString('utf8'));
  } catch {
    throw new InvalidCursorError('invalid json');
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new InvalidCursorError('cursor must be a JSON object');
  }
  return payload as Record<string, unknown>;
}

/**
 * The cursor after a row of a `(timestamp, id)`-ordered list.
 *
 * @param timestamp The row's sort timestamp: ISO text (see {@link cursorTimestampSql}, which
 *   keeps PostgreSQL's microseconds) or a `Date`.
 * @param id The row's id, the tie-breaker.
 * @returns The opaque cursor.
 */
export function encodeTimeIdCursor(timestamp: string | Date, id: string): string {
  const stamp = timestamp instanceof Date ? timestamp.toISOString() : String(timestamp);
  return encode({ t: stamp, i: String(id) });
}

/**
 * Read a `(timestamp, id)` cursor.
 *
 * @param token The cursor as the caller sent it.
 * @returns The timestamp (ISO text with a timezone) and the id.
 * @throws InvalidCursorError The token is malformed, or its timestamp has no timezone.
 */
export function decodeTimeIdCursor(token: unknown): { t: string; i: string } {
  const payload = decode(token);
  const { t, i } = payload;
  if (typeof t !== 'string' || typeof i !== 'string' || !i) {
    throw new InvalidCursorError('cursor missing t or i');
  }
  if (
    !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?/.test(t) ||
    Number.isNaN(Date.parse(t))
  ) {
    throw new InvalidCursorError('bad timestamp');
  }
  if (!/(Z|[+-]\d{2}(:?\d{2})?)$/.test(t)) {
    throw new InvalidCursorError('cursor timestamp missing timezone info');
  }
  return { t, i };
}

/**
 * The cursor after a row of a list ordered by any other key.
 *
 * @param values The row's sort-key values, in `ORDER BY` order.
 * @returns The opaque cursor.
 */
export function encodeKeyCursor(values: readonly unknown[]): string {
  return encode({
    k: values.map((value) => {
      if (value === null || value === undefined) return null;
      if (value instanceof Date) return value.toISOString();
      if (typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string') {
        return value;
      }
      return String(value);
    }),
  });
}

/**
 * Read a sort-key cursor.
 *
 * @param token The cursor as the caller sent it.
 * @param size How many key values the list's ordering has.
 * @returns The key values, in `ORDER BY` order.
 * @throws InvalidCursorError The token is malformed or carries a different number of values.
 */
export function decodeKeyCursor(token: unknown, size: number): unknown[] {
  const values = decode(token).k;
  if (!Array.isArray(values) || values.length !== size) {
    throw new InvalidCursorError('cursor does not match this list');
  }
  if (values.some((value) => value !== null && typeof value === 'object')) {
    throw new InvalidCursorError('cursor does not match this list');
  }
  return values;
}

/**
 * Cut a `limit + 1` read down to a page.
 *
 * @param rows The rows read with `LIMIT limit + 1`.
 * @param limit The page size the caller asked for.
 * @param cursorOf Builds the cursor that follows a row.
 * @returns The page; `nextCursor` is set only when a further row was read.
 */
export function pageOf<T>(
  rows: readonly T[],
  limit: number,
  cursorOf: (row: T) => string,
): ListPage<T> {
  const items = rows.slice(0, limit);
  const hasMore = rows.length > limit;
  const nextCursor = hasMore && items.length > 0 ? cursorOf(items[items.length - 1]) : null;
  return { items, hasMore, nextCursor };
}

/**
 * SQL that renders a `timestamptz` expression as ISO-8601 UTC text with microseconds.
 *
 * node-postgres hands a timestamp back as a `Date`, which is millisecond-precise; a cursor built
 * from it would skip or repeat rows written within the same millisecond. Select this beside the
 * row and build the cursor from the text.
 *
 * @param expression The timestamp expression as the query names it. Trusted SQL, never caller
 *   input.
 * @returns A SQL expression yielding e.g. `2026-01-02T03:04:05.678901Z`.
 */
export function cursorTimestampSql(expression: string): string {
  return `to_char((${expression}) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')`;
}

/**
 * Turn a reader's search text into an `ILIKE` pattern that matches it anywhere, literally.
 *
 * @param search The text as typed; `%`, `_` and `\` in it match themselves.
 * @returns `%text%`, or `null` when there is nothing to search for.
 */
export function searchPattern(search: string | null | undefined): string | null {
  const text = typeof search === 'string' ? search.trim().slice(0, 200) : '';
  if (!text) return null;
  return `%${text.replace(/[\\%_]/g, '\\$&')}%`;
}

/**
 * Drop the cursor-only columns a paged query selected beside each row.
 *
 * @param row A row as read.
 * @param keys The cursor-only column names.
 * @returns The row without them.
 */
export function withoutCursorColumns<T extends Record<string, unknown>>(
  row: T,
  keys: readonly string[],
): T {
  const copy: Record<string, unknown> = { ...row };
  for (const key of keys) delete copy[key];
  return copy as T;
}
