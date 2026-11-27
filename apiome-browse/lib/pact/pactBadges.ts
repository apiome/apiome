/**
 * Pact badges on the project page — PFX-1.10 (#6923).
 *
 * Framework-free helpers for the "Pact verification" strip: the wire type of
 * `GET /v1/browse/tenants/{t}/projects/{p}/pact-badges` (see
 * `apiome-rest/src/app/pact_badge_routes.py`), its URL, and a tolerant parser. The strip is
 * optional, so a bad or missing answer parses to an empty list and nothing is drawn.
 */

/** What a badge says. */
export type PactBadgeStatus = 'verified' | 'failing' | 'unknown';

/** One consumer of a pacticipant, with the status of its latest pact (PFX-7.5, #6965). */
export interface PactConsumer {
  slug: string;
  name: string;
  status: PactBadgeStatus;
}

/** One pacticipant bound to the project, as the REST route lists it. */
export interface PactBadgeItem {
  slug: string;
  name: string;
  status: PactBadgeStatus;
  pacts: number;
  /** How many consumers have a pact with it (may exceed `consumers.length`, which is capped). */
  consumer_count: number;
  consumers: PactConsumer[];
  badge_url: string;
}

const STATUSES: readonly string[] = ['verified', 'failing', 'unknown'];

/**
 * Read the consumers out of one item, dropping anything malformed.
 *
 * @param value - The item's `consumers` (anything).
 * @returns The well-formed consumers; `[]` when absent (an older REST API).
 */
function parseConsumers(value: unknown): PactConsumer[] {
  if (!Array.isArray(value)) return [];
  const out: PactConsumer[] = [];
  for (const entry of value) {
    const c = entry as Partial<PactConsumer> | null;
    if (
      c &&
      typeof c.slug === 'string' &&
      typeof c.name === 'string' &&
      typeof c.status === 'string' &&
      STATUSES.includes(c.status)
    ) {
      out.push({ slug: c.slug, name: c.name, status: c.status as PactBadgeStatus });
    }
  }
  return out;
}

/**
 * The one-line summary of an item's consumers, e.g. `3 consumers · 2 verified · 1 failing`.
 *
 * @param item - The pacticipant.
 * @returns The summary, or `null` when it has no consumers.
 */
export function consumersSummary(item: Pick<PactBadgeItem, 'consumer_count' | 'consumers'>): string | null {
  if (item.consumer_count <= 0) return null;
  const count = (status: PactBadgeStatus) => item.consumers.filter((c) => c.status === status).length;
  const parts = [`${item.consumer_count} ${item.consumer_count === 1 ? 'consumer' : 'consumers'}`];
  if (count('verified')) parts.push(`${count('verified')} verified`);
  if (count('failing')) parts.push(`${count('failing')} failing`);
  return parts.join(' · ');
}

/**
 * The URL of a project's pact status list.
 *
 * @param restApiBaseUrl - The browser-reachable REST base URL, ending in `/v1`.
 * @param tenantSlug - The workspace slug.
 * @param projectSlug - The project slug.
 * @returns The absolute `GET …/pact-badges` URL.
 */
export function pactBadgesUrl(restApiBaseUrl: string, tenantSlug: string, projectSlug: string): string {
  const tenant = encodeURIComponent(tenantSlug);
  const project = encodeURIComponent(projectSlug);
  return `${restApiBaseUrl}/browse/tenants/${tenant}/projects/${project}/pact-badges`;
}

/**
 * Read the pacticipants out of a `pact-badges` response, dropping anything malformed.
 *
 * @param body - The parsed JSON body (anything).
 * @returns The well-formed items, in the order sent; `[]` for anything else. A `badge_url` that is
 *   not an `http(s)` URL drops its item, so a page can never be made to embed another scheme.
 */
export function parsePactBadges(body: unknown): PactBadgeItem[] {
  const list = (body as { pacticipants?: unknown } | null)?.pacticipants;
  if (!Array.isArray(list)) return [];
  const items: PactBadgeItem[] = [];
  for (const entry of list) {
    const e = entry as Partial<PactBadgeItem> | null;
    if (
      e &&
      typeof e.slug === 'string' &&
      typeof e.name === 'string' &&
      typeof e.status === 'string' &&
      STATUSES.includes(e.status) &&
      typeof e.badge_url === 'string' &&
      /^https?:\/\//i.test(e.badge_url)
    ) {
      items.push({
        slug: e.slug,
        name: e.name,
        status: e.status as PactBadgeStatus,
        pacts: typeof e.pacts === 'number' ? e.pacts : 0,
        consumers: parseConsumers(e.consumers),
        consumer_count:
          typeof e.consumer_count === 'number' && e.consumer_count >= 0
            ? e.consumer_count
            : parseConsumers(e.consumers).length,
        badge_url: e.badge_url,
      });
    }
  }
  return items;
}
