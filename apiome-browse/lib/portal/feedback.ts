/**
 * Portal consumer feedback — COL-4.4 (#4528).
 *
 * A signed-in reader can send the owning team feedback on a published version: on the whole API or
 * on one operation. The team answers in its Discussion panel (where the thread is tagged
 * `consumer`), and the reader reads the replies on the version page's **Feedback** tab.
 *
 * The browser never holds the reader session (it is an `HttpOnly` cookie), so the tab talks to
 * Browse's own route handlers under `/api/portal/feedback/…`, which forward to apiome-rest's
 * `/v1/portal/{tenant}/feedback/{project}/{version}/threads` with `Authorization: Reader <token>`.
 *
 * Framework-free (Vitest, node environment). Wire types mirror
 * `apiome-rest/src/app/consumer_feedback.py`, snake_case as they arrive.
 */

/** What a reader can give feedback on. */
export type FeedbackTarget = 'version' | 'operation';

/** An operation, named the way the spec names it. */
export interface FeedbackOperation {
  method: string;
  path: string;
}

/** One message in a thread. */
export interface FeedbackComment {
  id: string;
  body: string;
  /** True for the owning team's replies; false for the reader's own messages. */
  from_team: boolean;
  author_name?: string | null;
  created_at: string;
  edited_at?: string | null;
}

/** A reader's feedback thread. */
export interface FeedbackThread {
  id: string;
  target: FeedbackTarget;
  operation?: FeedbackOperation | null;
  status: 'open' | 'resolved';
  resolved_at?: string | null;
  created_at: string;
  last_activity_at: string;
  comments: FeedbackComment[];
}

/** `GET …/threads`. */
export interface FeedbackThreadList {
  threads: FeedbackThread[];
}

/** The body of `POST …/threads`. */
export interface FeedbackCreateBody {
  target: FeedbackTarget;
  method?: string;
  path?: string;
  body: string;
}

/** What a thread action does: reply, resolve, or reopen. */
export type FeedbackAction = 'comments' | 'resolve' | 'reopen';

/** The thread actions the route handler accepts. */
export const FEEDBACK_ACTIONS: readonly FeedbackAction[] = ['comments', 'resolve', 'reopen'];

/** HTTP methods an OpenAPI path item can hold operations under. */
const HTTP_METHODS = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'] as const;

/** The value of the target picker for the whole API. */
export const WHOLE_API = 'version';

/** A version label or slug as Browse routes carry it. */
const SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._~+-]{0,127}$/;

/** A thread id (a UUID). */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Whether a path segment is a plausible project slug or version label. Guards the route handler, so
 * a crafted segment can never change the upstream path.
 *
 * @param value - The segment.
 * @returns True for a short run of URL-safe characters.
 */
export function isFeedbackSegment(value: string | null | undefined): value is string {
  return typeof value === 'string' && SEGMENT.test(value);
}

/**
 * Whether a value is a thread id.
 *
 * @param value - The candidate.
 * @returns True for a UUID.
 */
export function isThreadId(value: string | null | undefined): value is string {
  return typeof value === 'string' && UUID.test(value);
}

/**
 * Whether a value is a thread action.
 *
 * @param value - The candidate.
 * @returns True for `comments`, `resolve` or `reopen`.
 */
export function isFeedbackAction(value: string | null | undefined): value is FeedbackAction {
  return typeof value === 'string' && (FEEDBACK_ACTIONS as readonly string[]).includes(value);
}

/**
 * The apiome-rest URL for a version's feedback threads, or one thread action.
 *
 * @param restBase - The REST root ending in `/v1`.
 * @param tenant - The tenant slug.
 * @param project - The project slug.
 * @param version - The version label.
 * @param threadId - A thread, for an action.
 * @param action - The action on that thread.
 * @returns The URL.
 */
export function feedbackRestUrl(
  restBase: string,
  tenant: string,
  project: string,
  version: string,
  threadId?: string,
  action?: FeedbackAction,
): string {
  const base = `${restBase.replace(/\/+$/, '')}/portal/${encodeURIComponent(tenant)}/feedback/${encodeURIComponent(
    project,
  )}/${encodeURIComponent(version)}/threads`;
  return threadId && action ? `${base}/${encodeURIComponent(threadId)}/${action}` : base;
}

/**
 * Browse's own route for the same call, as the browser fetches it.
 *
 * @param basePath - `NEXT_PUBLIC_BASE_PATH` (`''` at the root).
 * @param tenant - The tenant slug.
 * @param project - The project slug.
 * @param version - The version label.
 * @param threadId - A thread, for an action.
 * @param action - The action on that thread.
 * @returns The path.
 */
export function feedbackBffUrl(
  basePath: string,
  tenant: string,
  project: string,
  version: string,
  threadId?: string,
  action?: FeedbackAction,
): string {
  const base = `${basePath.replace(/\/+$/, '')}/api/portal/feedback/${encodeURIComponent(tenant)}/${encodeURIComponent(
    project,
  )}/${encodeURIComponent(version)}/threads`;
  return threadId && action ? `${base}/${encodeURIComponent(threadId)}/${action}` : base;
}

/**
 * Every operation of a parsed OpenAPI document, in document order, for the target picker.
 *
 * @param spec - The parsed spec (anything; a non-OpenAPI document yields no operations).
 * @returns Method (upper case) and path pairs.
 */
export function specOperations(spec: unknown): FeedbackOperation[] {
  const paths = (spec as { paths?: unknown } | null)?.paths;
  if (!paths || typeof paths !== 'object') return [];
  const operations: FeedbackOperation[] = [];
  for (const [path, item] of Object.entries(paths as Record<string, unknown>)) {
    if (!item || typeof item !== 'object') continue;
    for (const method of HTTP_METHODS) {
      if ((item as Record<string, unknown>)[method]) operations.push({ method: method.toUpperCase(), path });
    }
  }
  return operations;
}

/**
 * The picker value for an operation (and the whole API).
 *
 * @param operation - The operation, or null for the whole API.
 * @returns `version`, or `GET /pets/{petId}`.
 */
export function targetValue(operation: FeedbackOperation | null): string {
  return operation ? `${operation.method} ${operation.path}` : WHOLE_API;
}

/**
 * Turn the picker value and message into the request body.
 *
 * @param value - The picker value from {@link targetValue}.
 * @param body - The message.
 * @returns The `POST …/threads` body.
 */
export function createBody(value: string, body: string): FeedbackCreateBody {
  if (value === WHOLE_API) return { target: 'version', body };
  const space = value.indexOf(' ');
  return { target: 'operation', method: value.slice(0, space), path: value.slice(space + 1), body };
}

/**
 * How a thread's subject reads.
 *
 * @param thread - The thread.
 * @returns `Whole API`, `GET /pets/{petId}`, or `An operation that was removed`.
 */
export function threadSubject(thread: Pick<FeedbackThread, 'target' | 'operation'>): string {
  if (thread.target === 'version') return 'Whole API';
  return thread.operation ? `${thread.operation.method} ${thread.operation.path}` : 'An operation that was removed';
}

/**
 * What the tab says for a refusal the route handler passes on.
 *
 * @param status - The HTTP status.
 * @param code - The `detail.code`, if any.
 * @returns A sentence for the reader.
 */
export function feedbackErrorCopy(status: number, code: string | null | undefined): string {
  if (status === 401) return 'Your sign-in has ended. Sign in again to send feedback.';
  if (status === 429) return 'You have sent a lot of feedback in a short time. Wait a minute and try again.';
  if (code === 'feedback-operation-not-found') return 'That operation is not part of this version any more.';
  if (code === 'feedback-version-not-found') return 'This version no longer takes feedback.';
  if (code === 'feedback-thread-not-found') return 'That thread is no longer available.';
  if (code === 'comment-empty-body') return 'Write a message first.';
  return 'Feedback could not be sent right now. Try again in a moment.';
}
