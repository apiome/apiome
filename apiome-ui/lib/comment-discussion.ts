/**
 * The Project Discussion panel's rule set — COL-1.3 (#4515).
 *
 * The Discussion tab on the Versions dashboard lists every comment thread of a project, whatever
 * version or element it hangs on. Four questions decide what it shows, and each has one answer
 * here:
 *
 * 1. **Which threads match?** — {@link discussionListParams} spells the panel's filters in
 *    apiome-rest's own query vocabulary, and {@link sanitizeThreadListParams} is the whitelist the
 *    BFF forwards, so the browser can never widen a request.
 * 2. **How many are unresolved?** — {@link unresolvedCommentCounts} is a copy of the Studio's count
 *    rule (`private-suite/designer/src/lib/comments/comment-thread-model.ts`, COL-1.2 #4514): a
 *    thread counts while its `status` is `open`, grouped by `anchor_type` + `anchor_id`. That is
 *    exactly what `GET …/comment-threads?status=open&anchor_type=…&anchor_id=…` totals, so the
 *    panel's numbers and the canvas badges agree.
 * 3. **What is the element called?** — {@link classAnchorLabel}, {@link propertyAnchorLabel} and
 *    {@link operationAnchorLabel} spell labels the way apiome-db's V260 orphan triggers store
 *    `anchor_label`, so a live thread and an orphaned one read the same.
 * 4. **Where does clicking go?** — {@link discussionThreadSearch} builds the COL-1.2 deep link
 *    (`/workspace?projectId&versionId&lens&sel&comment=<type>:<id>&thread=<id>`), which lands in
 *    Studio with the element on the canvas and its thread popover open.
 *
 * Framework-free: no React, no Next.js, no database. The BFF routes, the DB label resolver and the
 * panel all import it.
 */

/* -------------------------------------------------------------------------- */
/* Wire vocabulary                                                            */
/* -------------------------------------------------------------------------- */

/** The kinds of element a thread can be anchored to (apiome-rest `AnchorType`). */
export const COMMENT_ANCHOR_TYPES = ['class', 'property', 'path', 'operation', 'version'] as const;

/** One element kind. */
export type CommentAnchorType = (typeof COMMENT_ANCHOR_TYPES)[number];

/** A thread's lifecycle states (apiome-rest `ThreadStatus`, V260 adds `orphaned`). */
export const COMMENT_THREAD_STATUSES = ['open', 'resolved', 'orphaned'] as const;

/** One thread status. */
export type CommentThreadStatus = (typeof COMMENT_THREAD_STATUSES)[number];

/** The largest page apiome-rest's thread list returns. */
export const REST_THREAD_PAGE_LIMIT = 200;

/** How many threads the panel asks for at a time. */
export const DISCUSSION_PAGE_SIZE = 50;

/**
 * The most open threads read to count unresolved threads per element: ten pages of 200, the same
 * ceiling the Studio's per-version store uses.
 */
export const UNRESOLVED_COUNT_THREAD_CAP = 2000;

/** One comment, as apiome-rest's `CommentRecord` returns it. */
export interface DiscussionComment {
  /** The comment id. */
  id: string;
  /** The thread it belongs to. */
  thread_id: string;
  /** Who wrote it; null once that user has been deleted. */
  author_id: string | null;
  /** The author's display name, when they have one. */
  author_name: string | null;
  /** The Markdown body. */
  body: string;
  /** User ids the body's `@handles` resolved to. */
  mentions: string[];
  /** When it was last edited; null when never edited. */
  edited_at: string | null;
  /** When it was written (ISO 8601). */
  created_at: string;
}

/**
 * What the BFF learned about an anchored element, so the panel can name it and focus it.
 *
 * Only the fields the element kind has are set: a class has `className`; a property on a class has
 * `className` + `propertyName` (a library property only `propertyName`); a path has `pathname`; an
 * operation has `pathname` + `method`.
 */
export interface CommentAnchorContext {
  /** How the element reads, e.g. `Customer`, `Customer.email`, `GET /customers/{id}`. */
  label: string;
  /** The class name, for a class or a property on a class. */
  className?: string | null;
  /** The property name, for a property. */
  propertyName?: string | null;
  /** The pathname, for a path or an operation. */
  pathname?: string | null;
  /** The HTTP method as stored (`GET`), for an operation. */
  method?: string | null;
}

/** One thread, as apiome-rest's `CommentThreadSummary` returns it plus the BFF's anchor context. */
export interface DiscussionThread {
  /** The thread id. */
  id: string;
  /** The project the thread belongs to. */
  project_id: string;
  /** The version (revision) id whose element is discussed. */
  version_id: string;
  /** The kind of element the thread is anchored to. */
  anchor_type: CommentAnchorType;
  /** The anchored element's id. */
  anchor_id: string;
  /** `open`, `resolved` or `orphaned`. */
  status: CommentThreadStatus;
  /** The deleted element's label — set only while the thread is orphaned. */
  anchor_label?: string | null;
  /** When the element was deleted — set only while the thread is orphaned. */
  orphaned_at?: string | null;
  /** Who opened the thread. */
  created_by: string | null;
  /** Their display name. */
  created_by_name: string | null;
  /** Who resolved it, when resolved. */
  resolved_by: string | null;
  /** When it was resolved. */
  resolved_at: string | null;
  /** When it was opened. */
  created_at: string;
  /** The latest reply or status change; the list sorts by it. */
  last_activity_at: string;
  /** How many comments the thread holds, the opening one included. */
  comment_count: number;
  /** The opening comment. */
  root_comment?: DiscussionComment | null;
  /** The element's name and focus details; null when the BFF could not resolve them. */
  anchor_context?: CommentAnchorContext | null;
}

/** A page of the thread list. */
export interface DiscussionThreadPage {
  /** The threads on this page, most recently active first. */
  threads: DiscussionThread[];
  /** How many threads this page holds. */
  count: number;
  /** How many threads match the filters in all. */
  total: number;
  /** The page size asked for. */
  limit: number;
  /** How many threads were skipped. */
  offset: number;
}

/** The counts the panel draws beside its filters and on each row. */
export interface DiscussionSummary {
  /** Threads per status under the current mentions / element-type filters. */
  statusTotals: Record<CommentThreadStatus, number>;
  /** Every open thread of the project, unfiltered — the tab's count. */
  unresolvedTotal: number;
  /** Open threads per {@link commentAnchorKey}, unfiltered — the canvas badge numbers. */
  unresolvedByAnchor: Record<string, number>;
  /** True when the project has more open threads than {@link UNRESOLVED_COUNT_THREAD_CAP}. */
  truncated: boolean;
}

/**
 * Whether a value names an element kind.
 *
 * @param value - Anything.
 * @returns True for one of {@link COMMENT_ANCHOR_TYPES}.
 */
export function isCommentAnchorType(value: unknown): value is CommentAnchorType {
  return typeof value === 'string' && (COMMENT_ANCHOR_TYPES as readonly string[]).includes(value);
}

/**
 * Whether a value names a thread status.
 *
 * @param value - Anything.
 * @returns True for one of {@link COMMENT_THREAD_STATUSES}.
 */
export function isCommentThreadStatus(value: unknown): value is CommentThreadStatus {
  return typeof value === 'string' && (COMMENT_THREAD_STATUSES as readonly string[]).includes(value);
}

/** The canonical 8-4-4-4-12 hex UUID shape. */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Whether a value is a UUID. Anchor ids are row ids, and a SQL `uuid[]` cast rejects anything
 * else, so the label resolver drops the rest before querying.
 *
 * @param value - Anything.
 * @returns True for a hex UUID string.
 */
export function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value);
}

/* -------------------------------------------------------------------------- */
/* Filters                                                                    */
/* -------------------------------------------------------------------------- */

/** The status facet: one status, or every thread. */
export type DiscussionStatusFilter = CommentThreadStatus | 'all';

/** The element-type facet: one kind, or every kind. */
export type DiscussionElementFilter = CommentAnchorType | 'all';

/** Everything the panel filters on. */
export interface DiscussionFilters {
  /** Which status to list. */
  status: DiscussionStatusFilter;
  /** Only threads where a comment mentions the viewer. */
  mentionsMe: boolean;
  /** Which kind of element to list. */
  elementType: DiscussionElementFilter;
}

/** Where the panel starts: the open threads, on every element, whoever they mention. */
export const DEFAULT_DISCUSSION_FILTERS: Readonly<DiscussionFilters> = Object.freeze({
  status: 'open',
  mentionsMe: false,
  elementType: 'all',
});

/** The status chips, in the order they are drawn. */
export const DISCUSSION_STATUS_FILTERS: readonly DiscussionStatusFilter[] = [
  'open',
  'resolved',
  'orphaned',
  'all',
];

/** Each status chip's label. */
export const DISCUSSION_STATUS_LABELS: Readonly<Record<DiscussionStatusFilter, string>> = {
  open: 'Open',
  resolved: 'Resolved',
  orphaned: 'Orphaned',
  all: 'All',
};

/** The element-type chips, in the order they are drawn. */
export const DISCUSSION_ELEMENT_FILTERS: readonly DiscussionElementFilter[] = [
  'all',
  'class',
  'property',
  'path',
  'operation',
  'version',
];

/** Each element-type chip's label. */
export const DISCUSSION_ELEMENT_LABELS: Readonly<Record<DiscussionElementFilter, string>> = {
  all: 'All elements',
  class: 'Classes',
  property: 'Properties',
  path: 'Paths',
  operation: 'Operations',
  version: 'Versions',
};

/** One element kind, singular, for a row's type badge. */
export const ANCHOR_TYPE_LABELS: Readonly<Record<CommentAnchorType, string>> = {
  class: 'Class',
  property: 'Property',
  path: 'Path',
  operation: 'Operation',
  version: 'Version',
};

/**
 * The query string the panel sends to its BFF list route.
 *
 * The names are apiome-rest's own (`status`, `mentions_me`, `anchor_type`, `limit`, `offset`), so
 * the BFF forwards them after {@link sanitizeThreadListParams} rather than translating.
 *
 * @param filters - The panel's filters.
 * @param paging - The page to read.
 * @param versionId - Narrow to one version's threads, by revision id (the review page, COL-2.2);
 *   every version of the project when omitted.
 * @returns The query string, including its leading `?`.
 */
export function discussionListParams(
  filters: Readonly<DiscussionFilters>,
  paging: { limit?: number; offset?: number } = {},
  versionId?: string | null
): string {
  const params = new URLSearchParams();
  if (filters.status !== 'all') params.set('status', filters.status);
  if (filters.mentionsMe) params.set('mentions_me', 'true');
  if (filters.elementType !== 'all') params.set('anchor_type', filters.elementType);
  if (versionId) params.set('version', versionId);
  params.set('limit', String(paging.limit ?? DISCUSSION_PAGE_SIZE));
  params.set('offset', String(paging.offset ?? 0));
  return `?${params.toString()}`;
}

/**
 * The query string the panel sends to its BFF summary route: the filters that shape the status
 * counts. Status itself is not sent — the summary counts every status.
 *
 * @param filters - The panel's filters.
 * @param versionId - Narrow the counts to one version's threads, by revision id (COL-2.2).
 * @returns The query string, including its leading `?`, or `''` when nothing narrows.
 */
export function discussionSummaryParams(
  filters: Readonly<DiscussionFilters>,
  versionId?: string | null
): string {
  const params = new URLSearchParams();
  if (filters.mentionsMe) params.set('mentions_me', 'true');
  if (filters.elementType !== 'all') params.set('anchor_type', filters.elementType);
  if (versionId) params.set('version', versionId);
  const query = params.toString();
  return query ? `?${query}` : '';
}

/** Anything with URLSearchParams' `get`. */
export interface ParamReader {
  get(name: string): string | null;
}

/**
 * Parse a non-negative integer query value.
 *
 * @param raw - The raw value.
 * @returns The integer, or null when absent or not a plain non-negative integer.
 */
function parseCount(raw: string | null): number | null {
  if (raw === null || !/^\d+$/.test(raw.trim())) return null;
  const value = Number(raw.trim());
  return Number.isSafeInteger(value) ? value : null;
}

/**
 * The whitelist the BFF list route forwards to apiome-rest.
 *
 * Only the panel's filters survive: an unknown key is dropped, an unknown `status` or
 * `anchor_type` is dropped (so the list widens to every status rather than failing), `mentions_me`
 * is forwarded only as `true`, and `limit` is clamped to 1–{@link REST_THREAD_PAGE_LIMIT}.
 * `version` is forwarded only as a revision id (a UUID) — the review page's Discussion tab narrows to
 * the version under review (COL-2.2); a version label or anything else is dropped, so the list stays
 * project-wide. `anchor_id` is deliberately not forwarded.
 *
 * @param input - The browser's query.
 * @returns The query to send upstream.
 */
export function sanitizeThreadListParams(input: ParamReader): URLSearchParams {
  const out = new URLSearchParams();
  const status = input.get('status');
  if (isCommentThreadStatus(status)) out.set('status', status);
  const anchorType = input.get('anchor_type');
  if (isCommentAnchorType(anchorType)) out.set('anchor_type', anchorType);
  if (input.get('mentions_me') === 'true') out.set('mentions_me', 'true');
  const version = input.get('version');
  if (isUuid(version)) out.set('version', version);
  const limit = parseCount(input.get('limit'));
  out.set(
    'limit',
    String(Math.min(REST_THREAD_PAGE_LIMIT, Math.max(1, limit ?? DISCUSSION_PAGE_SIZE)))
  );
  const offset = parseCount(input.get('offset'));
  out.set('offset', String(offset ?? 0));
  return out;
}

/* -------------------------------------------------------------------------- */
/* Counts                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * The key one element's threads are grouped under — the Studio's own spelling.
 *
 * @param anchorType - The element kind.
 * @param anchorId - The element's id.
 * @returns `class:<id>`, `property:<id>` and so on.
 */
export function commentAnchorKey(anchorType: CommentAnchorType, anchorId: string): string {
  return `${anchorType}:${anchorId}`;
}

/**
 * Count the unresolved threads per element — the COL-1.2 badge rule.
 *
 * @param threads - Threads of any versions; only their status and anchor are read.
 * @returns A map from {@link commentAnchorKey} to its number of `open` threads. An element with none
 *   is absent rather than present with zero.
 */
export function unresolvedCommentCounts(
  threads: ReadonlyArray<Pick<DiscussionThread, 'status' | 'anchor_type' | 'anchor_id'>>
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const thread of threads) {
    if (thread.status !== 'open') continue;
    const key = commentAnchorKey(thread.anchor_type, thread.anchor_id);
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}

/**
 * How many threads a status chip stands for.
 *
 * @param totals - Threads per status.
 * @param filter - The chip.
 * @returns That status's total, or the sum for `all`.
 */
export function statusFilterCount(
  totals: Readonly<Record<CommentThreadStatus, number>>,
  filter: DiscussionStatusFilter
): number {
  if (filter !== 'all') return totals[filter] ?? 0;
  return COMMENT_THREAD_STATUSES.reduce((sum, status) => sum + (totals[status] ?? 0), 0);
}

/**
 * The words beside a row saying how many unresolved threads its element has.
 *
 * @param count - Open threads on the element.
 * @returns `1 unresolved on this element`, `3 unresolved on this element`, or `''` for none.
 */
export function unresolvedOnElementText(count: number): string {
  if (!Number.isFinite(count) || count <= 0) return '';
  return `${Math.floor(count)} unresolved on this element`;
}

/* -------------------------------------------------------------------------- */
/* Labels                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * A class's label.
 *
 * @param className - The class name.
 * @returns The name itself (V260: `classes.name`).
 */
export function classAnchorLabel(className: string): string {
  return className;
}

/**
 * A property's label.
 *
 * @param className - The owning class's name, or null for a library property.
 * @param propertyName - The property name.
 * @returns `Class.property` on a class, or the bare name in the library (V260's spelling).
 */
export function propertyAnchorLabel(className: string | null | undefined, propertyName: string): string {
  return className ? `${className}.${propertyName}` : propertyName;
}

/**
 * An operation's label.
 *
 * @param method - The HTTP method as stored.
 * @param pathname - The path it lives under.
 * @returns `GET /customers/{id}` (V260's spelling: upper-case method, a space, the pathname).
 */
export function operationAnchorLabel(method: string, pathname: string): string {
  return `${method.toUpperCase()} ${pathname}`;
}

/**
 * What a row calls its element.
 *
 * @param thread - The thread.
 * @returns The stored label for an orphaned thread, `Whole version` for a version anchor, the
 *   resolved label otherwise, and `<Kind> <first 8 of id>` when nothing could be resolved.
 */
export function threadElementLabel(thread: Readonly<DiscussionThread>): string {
  if (thread.status === 'orphaned') {
    return thread.anchor_label || thread.anchor_context?.label || 'Deleted element';
  }
  if (thread.anchor_type === 'version') return 'Whole version';
  if (thread.anchor_context?.label) return thread.anchor_context.label;
  return `${ANCHOR_TYPE_LABELS[thread.anchor_type]} ${thread.anchor_id.slice(0, 8)}`;
}

/**
 * A single-line preview of a comment body.
 *
 * @param body - The Markdown body.
 * @param max - The most characters to keep before the ellipsis.
 * @returns The body with whitespace runs collapsed, cut at `max` with `…`.
 */
export function commentExcerpt(body: string | null | undefined, max = 160): string {
  const text = (body ?? '').replace(/\s+/g, ' ').trim();
  if (text.length <= max) return text;
  return `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

/**
 * How many replies a thread has, in words.
 *
 * @param commentCount - Comments in the thread, the opening one included.
 * @returns `No replies`, `1 reply` or `N replies`.
 */
export function replyCountText(commentCount: number): string {
  const replies = Math.max(0, Math.floor(commentCount) - 1);
  if (replies === 0) return 'No replies';
  return replies === 1 ? '1 reply' : `${replies} replies`;
}

/* -------------------------------------------------------------------------- */
/* Deep link (COL-1.2's format)                                               */
/* -------------------------------------------------------------------------- */

/** The workspace's project parameter. */
export const WORKSPACE_PROJECT_PARAM = 'projectId';
/** The workspace's version parameter. */
export const WORKSPACE_VERSION_PARAM = 'versionId';
/** The workspace's lens parameter. */
export const WORKSPACE_LENS_PARAM = 'lens';
/** The workspace's selection-address parameter. */
export const WORKSPACE_SELECTION_PARAM = 'sel';
/** The parameter naming the element whose comment popover opens. */
export const COMMENT_ANCHOR_PARAM = 'comment';
/** The parameter naming the thread expanded inside that popover. */
export const COMMENT_THREAD_PARAM = 'thread';

/** A contract selection address, as the Studio's `selection-address.ts` defines it. */
export interface SelectionAddress {
  /** The version whose document the pointer addresses. */
  versionId: string;
  /** RFC 6901 JSON Pointer into the OpenAPI document. */
  pointer: string;
  /** The element's database id. */
  entityId?: string;
}

/**
 * The lens that draws an anchor kind.
 *
 * @param anchorType - The element kind.
 * @returns `schemas` for classes and properties, `paths` for paths and operations, null for a
 *   version, which no lens draws.
 */
export function commentDeepLinkLens(anchorType: CommentAnchorType): 'schemas' | 'paths' | null {
  if (anchorType === 'class' || anchorType === 'property') return 'schemas';
  if (anchorType === 'path' || anchorType === 'operation') return 'paths';
  return null;
}

/**
 * Build an RFC 6901 JSON Pointer (`~` → `~0`, `/` → `~1` in each token).
 *
 * @param tokens - Unescaped object keys.
 * @returns The pointer, `''` for no tokens.
 */
export function buildPointer(tokens: readonly string[]): string {
  if (tokens.length === 0) return '';
  return `/${tokens.map((token) => token.replace(/~/g, '~0').replace(/\//g, '~1')).join('/')}`;
}

/**
 * Serialize a selection address for the `sel` parameter, exactly as the Studio does.
 *
 * @param address - The address.
 * @returns `versionId|pointer|entityId`, each part URI-encoded.
 */
export function serializeSelectionAddress(address: Readonly<SelectionAddress>): string {
  return [address.versionId, address.pointer, address.entityId ?? '']
    .map(encodeURIComponent)
    .join('|');
}

/**
 * The address that puts a thread's element on the canvas.
 *
 * Spelled as the Studio's publishers spell it — `classSelectionAddress`,
 * `propertySelectionAddress`, the paths adapter — so the workspace classifies it the same way.
 *
 * @param thread - The thread, with its anchor context.
 * @returns The address, or null when the element has no canvas address (a version, a library
 *   property) or its names could not be resolved.
 */
export function anchorSelectionAddress(thread: Readonly<DiscussionThread>): SelectionAddress | null {
  const context = thread.anchor_context;
  const base = { versionId: thread.version_id, entityId: thread.anchor_id };
  switch (thread.anchor_type) {
    case 'class':
      return context?.className
        ? { ...base, pointer: buildPointer(['components', 'schemas', context.className]) }
        : null;
    case 'property':
      return context?.className && context.propertyName
        ? {
            ...base,
            pointer: buildPointer([
              'components',
              'schemas',
              context.className,
              'properties',
              context.propertyName,
            ]),
          }
        : null;
    case 'path':
      return context?.pathname ? { ...base, pointer: buildPointer(['paths', context.pathname]) } : null;
    case 'operation':
      return context?.pathname && context.method
        ? {
            ...base,
            pointer: buildPointer(['paths', context.pathname, context.method.toLowerCase()]),
          }
        : null;
    default:
      return null;
  }
}

/**
 * The query string of a thread's Studio deep link.
 *
 * A live thread gets the full COL-1.2 link — scope, lens, selection, `comment` and `thread` — in
 * the Studio's own parameter order. An orphaned thread's element is gone, so it gets the version's
 * scope only: the Studio lists orphaned threads there for relinking (COL-1.4).
 *
 * @param thread - The thread.
 * @returns The query string, including its leading `?`.
 */
export function discussionThreadSearch(thread: Readonly<DiscussionThread>): string {
  const params = new URLSearchParams();
  params.set(WORKSPACE_PROJECT_PARAM, thread.project_id);
  params.set(WORKSPACE_VERSION_PARAM, thread.version_id);
  if (thread.status !== 'orphaned') {
    const lens = commentDeepLinkLens(thread.anchor_type);
    if (lens) params.set(WORKSPACE_LENS_PARAM, lens);
    const selection = anchorSelectionAddress(thread);
    if (selection) params.set(WORKSPACE_SELECTION_PARAM, serializeSelectionAddress(selection));
    params.set(COMMENT_ANCHOR_PARAM, commentAnchorKey(thread.anchor_type, thread.anchor_id));
    params.set(COMMENT_THREAD_PARAM, thread.id);
  }
  return `?${params.toString()}`;
}

/**
 * A thread's Studio deep link.
 *
 * @param workspaceRoute - The Studio workspace route on this deployment (absolute or relative), or
 *   null when the Studio is not available.
 * @param thread - The thread.
 * @returns The href, or null without a workspace route.
 */
export function discussionThreadHref(
  workspaceRoute: string | null | undefined,
  thread: Readonly<DiscussionThread>
): string | null {
  if (!workspaceRoute) return null;
  return `${workspaceRoute}${discussionThreadSearch(thread)}`;
}
