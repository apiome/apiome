/**
 * The notification centre's rules, with no React and no `window` — COL-3.2 (#4522).
 *
 * COL-3.1 (#4521) writes one inbox row per recipient per event and exposes three reads;
 * this module is everything the browser has to decide *about* such a row that is not
 * drawing it: what it says, where clicking it goes, which run of the list it belongs to,
 * and what a BFF route is allowed to forward upstream.
 *
 * It is framework-free for the same reason `lib/comment-discussion.ts` and
 * `lib/review-status.ts` are: the rail dropdown, the full page and the BFF routes all need
 * these answers, and only one of the three has a DOM.
 *
 * The wire shapes mirror `apiome-rest/docs/notifications.md`. Two properties of that
 * contract are load-bearing here:
 *
 * - **A payload key that did not resolve is absent, never null.** Every reader below
 *   therefore treats "missing" as the normal case and degrades the sentence rather than
 *   printing `undefined`.
 * - **`project_id` and `version_id` are columns, not payload**, so a notification whose
 *   destination was deleted arrives with them nulled. That is exactly when
 *   {@link notificationHref} answers `null`, and the row is drawn inert instead of linking
 *   somewhere that 404s.
 */

/* -------------------------------------------------------------------------
   The vocabulary
   ------------------------------------------------------------------------- */

/**
 * The findings CDG-2.3 (#5962) routes to an entity's owner team, in the order the UI lists
 * them. Each row says what happened in its own `summary` and links with its own `link`.
 */
export const OWNER_NOTIFICATION_TYPES = [
  'owner_finding',
  'owner_breaking_change',
  'owner_verification_drift',
  'owner_gate_blocked',
  'owner_trust_drift',
  'owner_shadow_api',
  'owner_sync_failed',
] as const;

/**
 * Every event apiome-rest writes rows for, in the order the UI lists them.
 *
 * The order is deliberate — the two that ask the reader to *do* something come first, then
 * the collaboration events (COL-3.1), then the owner findings (CDG-2.3) — and it is the order
 * of the preference switches and the page's filter chips, so the reader meets the same types
 * in the same sequence everywhere.
 */
export const NOTIFICATION_TYPES = [
  'mention',
  'review_requested',
  'review_decision',
  'thread_resolved',
  'version_published',
  ...OWNER_NOTIFICATION_TYPES,
] as const;

/** One of the event types. */
export type NotificationType = (typeof NOTIFICATION_TYPES)[number];

/** One of the owner-finding types. */
export type OwnerNotificationType = (typeof OWNER_NOTIFICATION_TYPES)[number];

/**
 * Whether a type is an owner finding (CDG-2.3).
 *
 * @param type - A notification type.
 * @returns True for the `owner_*` types.
 */
export function isOwnerNotificationType(type: NotificationType): type is OwnerNotificationType {
  return (OWNER_NOTIFICATION_TYPES as readonly string[]).includes(type);
}

/** The plural noun each type is filtered and switched by. */
export const NOTIFICATION_TYPE_LABELS: Readonly<Record<NotificationType, string>> = {
  mention: 'Mentions',
  review_requested: 'Review requests',
  review_decision: 'Review decisions',
  thread_resolved: 'Resolved threads',
  version_published: 'Publishes',
  owner_finding: 'Lint findings',
  owner_breaking_change: 'Breaking changes',
  owner_verification_drift: 'Verification drift',
  owner_gate_blocked: 'Blocked deploy gates',
  owner_trust_drift: 'MCP trust drift',
  owner_shadow_api: 'Shadow APIs',
  owner_sync_failed: 'Failed connector syncs',
};

/**
 * What each switch in the preferences pane promises, in one line.
 *
 * Phrased as what the reader will *stop* seeing, because that is what flipping the switch
 * off does — see `components/ade/preferences/NotificationsTab.tsx`.
 */
export const NOTIFICATION_TYPE_DESCRIPTIONS: Readonly<Record<NotificationType, string>> = {
  mention: 'When somebody names you in a comment.',
  review_requested: 'When you are asked to review a version.',
  review_decision: 'When a reviewer answers a review you requested.',
  thread_resolved: 'When a thread you took part in is resolved.',
  version_published: 'When a version you collaborated on is published.',
  owner_finding: 'When something your team owns gets a new error-level lint finding.',
  owner_breaking_change: 'When a refresh brings a breaking change to something your team owns.',
  owner_verification_drift: 'When verification finds drift on something your team owns.',
  owner_gate_blocked: 'When the deploy gate fails for a project your team owns.',
  owner_trust_drift: 'When an MCP endpoint your team owns drifts from its trust baseline.',
  owner_shadow_api: 'When a connector your team owns finds APIs the catalog does not describe.',
  owner_sync_failed: 'When a connector your team owns fails to sync.',
};

/**
 * Whether a value is one of the five types.
 *
 * @param value - Anything; a query parameter, a stored preference, a wire field.
 * @returns True when it is a {@link NotificationType}.
 */
export function isNotificationType(value: unknown): value is NotificationType {
  return (
    typeof value === 'string' && (NOTIFICATION_TYPES as readonly string[]).includes(value)
  );
}

/* -------------------------------------------------------------------------
   The wire
   ------------------------------------------------------------------------- */

/**
 * The `payload` object of a notification.
 *
 * Every key is optional: apiome-rest omits what it could not resolve, and the set of keys
 * present depends on the type (`apiome-rest/docs/notifications.md` § Payload).
 */
export interface NotificationPayload {
  /** The project's slug, for the sentence. */
  project_slug?: string;
  /** The project's display name. */
  project_name?: string;
  /** The version, e.g. `1.2.0`. */
  version_label?: string;
  /** The thread to open — `mention` and `thread_resolved`. */
  thread_id?: string;
  /** The comment that named the recipient — `mention`. */
  comment_id?: string;
  /** What the thread is anchored to. */
  anchor_type?: string;
  /** The id of that element. */
  anchor_id?: string;
  /** Up to 280 characters of the comment — `mention`. */
  excerpt?: string;
  /** The review — `review_requested` and `review_decision`. */
  review_id?: string;
  /** Which round of it. */
  round?: number;
  /** `approve` or `request_changes` — `review_decision`. */
  decision?: string;
  /** The kind of entity an owner finding is about (`project`, `catalog_item`, …) — `owner_*`. */
  entity_kind?: string;
  /** That entity's id — `owner_*`. */
  entity_id?: string;
  /** That entity's display name, when the producer had it — `owner_*`. */
  entity_name?: string;
  /** What happened, in one sentence — `owner_*`. */
  summary?: string;
  /** Relative app path to the finding — `owner_*`. */
  link?: string;
  /** The producer's id for the finding (a report, a run) — `owner_*`. */
  finding_id?: string;
  /** The owner team the finding was routed to — `owner_*`. */
  team?: { id?: string; slug?: string; name?: string };
}

/** One row of the caller's inbox, as `GET …/notifications` returns it. */
export interface NotificationRow {
  /** The row's id — what `POST …/notifications/read` marks. */
  id: string;
  /** The tenant the event happened in. */
  tenant_id: string;
  /** The recipient: always the caller. */
  user_id: string;
  /** Which of the five events this is. */
  type: NotificationType;
  /** The ids and labels the sentence and the link need. */
  payload: NotificationPayload;
  /** Who did it; null once that person has left. */
  actor_id: string | null;
  /** Their display name, read fresh at list time so a rename is never stale. */
  actor_name: string | null;
  /** The project the row points at; null once it is deleted. */
  project_id: string | null;
  /** The version the row points at; null once it is deleted. */
  version_id: string | null;
  /** When it was read, or null while it is unread. */
  read_at: string | null;
  /** When the event happened. */
  created_at: string;
}

/** A page of the inbox. */
export interface NotificationPage {
  /** The rows, newest first. */
  notifications: NotificationRow[];
  /** How many are in this page. */
  count: number;
  /** How many match the query in all. */
  total: number;
  /** The page size that was applied. */
  limit: number;
  /** Where this page starts. */
  offset: number;
}

/**
 * The unread tallies, as `GET …/notifications/unread-count` returns them.
 *
 * `by_type` reports **every** type, zeroes included, which is what lets the badge be
 * recomputed for any subset of types without a second request.
 */
export interface NotificationUnreadCounts {
  /** Unread rows of every type. */
  total: number;
  /** Unread rows per type. */
  by_type: Record<NotificationType, number>;
}

/** What `POST …/notifications/read` answers with. */
export interface NotificationReadResult {
  /** How many rows this call changed; already-read rows are not counted again. */
  marked: number;
  /** The unread tallies that follow, so the badge needs no second call. */
  unread: NotificationUnreadCounts;
}

/** The unread counts with nothing unread — the SSR value, and the value after a failure. */
export const EMPTY_UNREAD_COUNTS: Readonly<NotificationUnreadCounts> = Object.freeze({
  total: 0,
  by_type: Object.freeze(
    Object.fromEntries(NOTIFICATION_TYPES.map((type) => [type, 0]))
  ) as Record<NotificationType, number>,
});

/**
 * Read an unread-count reply defensively.
 *
 * The badge must never be `NaN` and must never be missing a type, so a reply that is short
 * of one is completed with zeroes rather than rejected — the same forgiveness the endpoint
 * itself shows by reporting zeroes.
 *
 * @param value - The parsed reply, or anything at all.
 * @returns Counts with all five types present.
 */
export function parseUnreadCounts(value: unknown): NotificationUnreadCounts {
  const source = (value ?? {}) as Partial<NotificationUnreadCounts>;
  const byType = (source.by_type ?? {}) as Partial<Record<NotificationType, unknown>>;
  const resolved = Object.fromEntries(
    NOTIFICATION_TYPES.map((type) => {
      const count = byType[type];
      return [type, typeof count === 'number' && Number.isFinite(count) ? count : 0];
    })
  ) as Record<NotificationType, number>;
  const total =
    typeof source.total === 'number' && Number.isFinite(source.total)
      ? source.total
      : NOTIFICATION_TYPES.reduce((sum, type) => sum + resolved[type], 0);
  return { total, by_type: resolved };
}

/* -------------------------------------------------------------------------
   Paging
   ------------------------------------------------------------------------- */

/** apiome-rest's own ceiling on a page of the inbox. */
export const NOTIFICATION_MAX_LIMIT = 200;

/** How many rows the full page asks for at a time. */
export const NOTIFICATION_PAGE_SIZE = 50;

/**
 * How many rows the rail dropdown asks for.
 *
 * A dropdown is a glance, not an archive: more than this and the popup is taller than the
 * rail it hangs off, which is what the full page is for. Read as `NOTIFICATION_PAGE_SIZE`
 * would be, so muting a type still leaves the menu with something to show.
 */
export const NOTIFICATION_MENU_LIMIT = 20;

/* -------------------------------------------------------------------------
   Sentences
   ------------------------------------------------------------------------- */

/** What an actor is called once they have left the tenant (`actor_id` is nulled). */
const UNKNOWN_ACTOR = 'Someone';

/**
 * The person a notification is about, fit to start a sentence.
 *
 * @param row - The notification.
 * @returns Their display name, or `Someone`.
 */
export function notificationActor(row: Readonly<NotificationRow>): string {
  return row.actor_name?.trim() || UNKNOWN_ACTOR;
}

/**
 * What the notification says, in one sentence.
 *
 * The sentence names the actor and the event and nothing else; the project and the version
 * are a separate, quieter line, because they are the same two facts on every row and
 * repeating them inside the sentence makes a list of five read as five paragraphs.
 *
 * @param row - The notification.
 * @returns The sentence, with no trailing punctuation.
 */
export function notificationSentence(row: Readonly<NotificationRow>): string {
  if (isOwnerNotificationType(row.type)) {
    // An owner finding carries its own sentence; the actor is usually a sweep, not a person.
    return row.payload.summary?.trim() || OWNER_FALLBACK_SENTENCES[row.type];
  }
  const actor = notificationActor(row);
  switch (row.type) {
    case 'mention':
      return `${actor} mentioned you in a comment`;
    case 'review_requested':
      return `${actor} requested your review`;
    case 'review_decision':
      // The decision vocabulary is apiome-rest's (`approve` / `request_changes`); an
      // unrecognised value degrades to the neutral phrase rather than printing the token.
      if (row.payload.decision === 'approve') return `${actor} approved your review`;
      if (row.payload.decision === 'request_changes') {
        return `${actor} requested changes on your review`;
      }
      return `${actor} answered your review`;
    case 'thread_resolved':
      return `${actor} resolved a thread you took part in`;
    case 'version_published': {
      const label = row.payload.version_label?.trim();
      return label ? `${actor} published ${label}` : `${actor} published a version`;
    }
    default:
      // Unreachable while `type` is the union, but a future sixth type written by a newer
      // apiome-rest must not render as a blank row.
      return `${actor} did something you follow`;
  }
}

/** What an owner finding says when its payload carries no `summary`. */
const OWNER_FALLBACK_SENTENCES: Readonly<Record<OwnerNotificationType, string>> = {
  owner_finding: 'New error-level lint findings',
  owner_breaking_change: 'A refresh introduced a breaking change',
  owner_verification_drift: 'Verification found drift',
  owner_gate_blocked: 'The deploy gate failed',
  owner_trust_drift: 'An MCP endpoint drifted from its trust baseline',
  owner_shadow_api: 'A connector found shadow APIs',
  owner_sync_failed: 'A connector sync failed',
};

/** How an owner finding names the kind of entity when it carries no name. */
const ENTITY_KIND_LABELS: Readonly<Record<string, string>> = {
  project: 'Project',
  catalog_item: 'Catalog item',
  mcp_endpoint: 'MCP endpoint',
  consumer: 'Consumer',
  connector: 'Connector',
};

/**
 * The quiet second line: the project, and the version when the row names one.
 *
 * For an owner finding it is the team it was routed to and the entity: `Payments · Orders API`.
 *
 * @param row - The notification.
 * @returns `Payments · 1.2.0`, `Payments`, or an empty string when neither resolved.
 */
export function notificationContext(row: Readonly<NotificationRow>): string {
  if (isOwnerNotificationType(row.type)) {
    const team = row.payload.team?.name?.trim() || row.payload.team?.slug?.trim() || '';
    const entity =
      row.payload.entity_name?.trim() ||
      row.payload.project_name?.trim() ||
      ENTITY_KIND_LABELS[row.payload.entity_kind ?? ''] ||
      '';
    return [team, entity].filter(Boolean).join(' · ');
  }
  const project = row.payload.project_name?.trim() || row.payload.project_slug?.trim() || '';
  const version = row.payload.version_label?.trim() || '';
  // A publish already says the version in its sentence; repeating it here is noise.
  if (row.type === 'version_published') return project;
  if (project && version) return `${project} · ${version}`;
  return project || version;
}

/**
 * The comment excerpt a mention carries, if any.
 *
 * @param row - The notification.
 * @returns The excerpt, or null for every other type and for a mention without one.
 */
export function notificationExcerpt(row: Readonly<NotificationRow>): string | null {
  if (row.type !== 'mention') return null;
  const excerpt = row.payload.excerpt?.trim();
  return excerpt ? excerpt : null;
}

/* -------------------------------------------------------------------------
   Deep links
   ------------------------------------------------------------------------- */

/** The project dashboard a thread or a version is reached through. */
const VERSIONS_ROUTE = '/ade/dashboard/versions';

/** COL-2.2's review page. */
const REVIEWS_ROUTE = '/ade/reviews';

/** The full notification centre. */
export const NOTIFICATIONS_ROUTE = '/ade/dashboard/notifications';

/**
 * The Versions screen's main-tab parameter, read by
 * `src/app/ade/dashboard/versions/page.tsx`.
 */
export const VERSIONS_TAB_PARAM = 'tab';

/** The thread that screen's Discussion tab should highlight. */
export const VERSIONS_THREAD_PARAM = 'thread';

/**
 * Where clicking a notification goes.
 *
 * Every destination is an apiome-ui route rather than a Studio one. The payload carries a
 * thread's id but not the *names* its Studio address is built from (`anchor_context` is a
 * COL-1.3 read, not a stored field), so a Studio link would degrade to version scope —
 * and it would dead-end entirely where the Studio is not licensed. COL-1.3's Discussion
 * tab is the destination that always exists and always knows the thread.
 *
 * | Type | Destination |
 * | --- | --- |
 * | `mention`, `thread_resolved` | the project's Discussion tab, that thread highlighted |
 * | `review_requested`, `review_decision` | `/ade/reviews/{id}` |
 * | `version_published` | the project's version timeline |
 * | `owner_*` | the finding's own `link` — an `/ade/` path only |
 *
 * @param row - The notification.
 * @returns The href, or `null` when the row has lost the id its destination needs — a
 *   deleted project, or a review the payload never carried.
 */
export function notificationHref(row: Readonly<NotificationRow>): string | null {
  switch (row.type) {
    case 'mention':
    case 'thread_resolved': {
      if (!row.project_id) return null;
      const params = new URLSearchParams({ projectId: row.project_id });
      params.set(VERSIONS_TAB_PARAM, 'discussion');
      const thread = row.payload.thread_id?.trim();
      if (thread) params.set(VERSIONS_THREAD_PARAM, thread);
      return `${VERSIONS_ROUTE}?${params.toString()}`;
    }
    case 'review_requested':
    case 'review_decision': {
      const review = row.payload.review_id?.trim();
      return review ? `${REVIEWS_ROUTE}/${encodeURIComponent(review)}` : null;
    }
    case 'version_published': {
      if (!row.project_id) return null;
      return `${VERSIONS_ROUTE}?${new URLSearchParams({ projectId: row.project_id }).toString()}`;
    }
    default:
      if (isOwnerNotificationType(row.type)) return ownerFindingHref(row.payload.link);
      return null;
  }
}

/**
 * The deep link an owner finding carries, when it is safe to follow.
 *
 * Only a same-origin app path is accepted: a payload is data, and a link that left the app
 * (`https://…`, `//host`, `javascript:`) would make the notification centre an open redirect.
 *
 * @param link - The payload's `link`.
 * @returns The path, or `null`.
 */
export function ownerFindingHref(link: string | undefined): string | null {
  const path = link?.trim();
  if (!path || !path.startsWith('/ade/') || path.includes('\\')) return null;
  return path;
}

/* -------------------------------------------------------------------------
   Grouping
   ------------------------------------------------------------------------- */

/** The four runs a list of notifications is drawn in. */
export type NotificationBucket = 'today' | 'yesterday' | 'earlier-week' | 'older';

/** The heading above each run. */
export const NOTIFICATION_BUCKET_LABELS: Readonly<Record<NotificationBucket, string>> = {
  today: 'Today',
  yesterday: 'Yesterday',
  'earlier-week': 'Earlier this week',
  older: 'Older',
};

/** A run of notifications under one heading. */
export interface NotificationGroup {
  /** Which run this is. */
  bucket: NotificationBucket;
  /** Its heading. */
  label: string;
  /** The rows in it, in the order they were given. */
  rows: NotificationRow[];
}

/** Milliseconds in a day, for the "earlier this week" window. */
const DAY_MS = 86_400_000;

/**
 * Midnight of a timestamp's own calendar day, in the reader's timezone.
 *
 * Calendar days rather than rolling 24-hour windows: "yesterday" means the day before the
 * one the reader is having, and a notification from 23:50 last night is not "today"
 * because it is eleven hours old.
 *
 * @param at - Epoch milliseconds.
 * @returns Epoch milliseconds of that day's 00:00 local.
 */
function startOfLocalDay(at: number): number {
  const date = new Date(at);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

/**
 * Which run a timestamp belongs to.
 *
 * @param createdAt - The row's ISO-8601 `created_at`.
 * @param now - Reference epoch milliseconds; a parameter so tests need no fake clock.
 * @returns The bucket. An unparseable or future timestamp is `today` — clock skew between
 *   the server and the reader must not file a brand-new notification under "Older".
 */
export function notificationBucket(createdAt: string, now: number): NotificationBucket {
  const at = new Date(createdAt).getTime();
  if (!Number.isFinite(at)) return 'today';
  const today = startOfLocalDay(now);
  if (at >= today) return 'today';
  if (at >= today - DAY_MS) return 'yesterday';
  if (at >= today - 6 * DAY_MS) return 'earlier-week';
  return 'older';
}

/**
 * Split rows into the four runs, dropping the runs that are empty.
 *
 * The rows arrive newest first and keep that order inside each run, so the grouping only
 * ever inserts headings — it never re-sorts, which is what keeps the dropdown and the page
 * showing the same sequence as the endpoint.
 *
 * @param rows - The notifications, newest first.
 * @param now - Reference epoch milliseconds.
 * @returns One group per non-empty run, in bucket order.
 */
export function groupNotificationsByTime(
  rows: readonly NotificationRow[],
  now: number
): NotificationGroup[] {
  const order: readonly NotificationBucket[] = ['today', 'yesterday', 'earlier-week', 'older'];
  const buckets = new Map<NotificationBucket, NotificationRow[]>();
  for (const row of rows) {
    const bucket = notificationBucket(row.created_at, now);
    const existing = buckets.get(bucket);
    if (existing) existing.push(row);
    else buckets.set(bucket, [row]);
  }
  return order
    .filter((bucket) => (buckets.get(bucket)?.length ?? 0) > 0)
    .map((bucket) => ({
      bucket,
      label: NOTIFICATION_BUCKET_LABELS[bucket],
      rows: buckets.get(bucket) as NotificationRow[],
    }));
}

/* -------------------------------------------------------------------------
   What the BFF forwards
   ------------------------------------------------------------------------- */

/** The shape of a query reader — `URLSearchParams` and Next's own both satisfy it. */
export interface NotificationParamReader {
  /** Read one parameter. */
  get(name: string): string | null;
}

/**
 * Clamp a caller's `limit` into what apiome-rest accepts.
 *
 * @param raw - The raw parameter, or null.
 * @returns A limit between 1 and {@link NOTIFICATION_MAX_LIMIT}.
 */
function sanitizeLimit(raw: string | null): number {
  const parsed = Number.parseInt(raw ?? '', 10);
  if (!Number.isFinite(parsed) || parsed < 1) return NOTIFICATION_PAGE_SIZE;
  return Math.min(parsed, NOTIFICATION_MAX_LIMIT);
}

/**
 * The query the inbox BFF route is allowed to forward.
 *
 * A whitelist, not a pass-through — the same rule `sanitizeThreadListParams` follows. The
 * caller cannot reach apiome-rest with a parameter this module has not heard of, so a
 * future upstream filter cannot be driven from the browser before the BFF has decided it
 * should be.
 *
 * @param input - The incoming query.
 * @returns The parameters to send upstream: `unread`, `type`, `limit`, `offset`.
 */
export function sanitizeNotificationListParams(
  input: NotificationParamReader
): URLSearchParams {
  const params = new URLSearchParams();

  // `unread` is a flag: present and truthy means "only what has not been read".
  const unread = input.get('unread');
  if (unread === 'true' || unread === '1') params.set('unread', 'true');

  const type = input.get('type');
  if (isNotificationType(type)) params.set('type', type);

  params.set('limit', String(sanitizeLimit(input.get('limit'))));

  const offset = Number.parseInt(input.get('offset') ?? '', 10);
  params.set('offset', String(Number.isFinite(offset) && offset > 0 ? offset : 0));

  return params;
}

/** A mark-read request, after the BFF has decided it is one. */
export type NotificationReadRequest = { all: true } | { ids: string[] };

/** The `8-4-4-4-12` hex form; anything else never reaches a `::uuid` cast upstream. */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * How many ids one mark-read call may name.
 *
 * The dropdown marks one row at a time and the page marks a screenful, so the bound is
 * generous; it exists so a hand-made request cannot turn one POST into an unbounded
 * statement.
 */
export const NOTIFICATION_MARK_READ_MAX_IDS = NOTIFICATION_MAX_LIMIT;

/**
 * Read a mark-read body, or refuse it.
 *
 * `{all: true}` wins when both are given: it is the wider of the two, and a request that
 * asks for both has already said it wants everything marked.
 *
 * @param body - The parsed request body.
 * @returns The request to forward, or `null` when the body names nothing markable.
 */
export function sanitizeMarkReadBody(body: unknown): NotificationReadRequest | null {
  if (!body || typeof body !== 'object') return null;
  const source = body as { all?: unknown; ids?: unknown };
  if (source.all === true) return { all: true };
  if (!Array.isArray(source.ids)) return null;
  const ids = source.ids
    .filter((id): id is string => typeof id === 'string' && UUID_PATTERN.test(id))
    .slice(0, NOTIFICATION_MARK_READ_MAX_IDS);
  return ids.length > 0 ? { ids } : null;
}
