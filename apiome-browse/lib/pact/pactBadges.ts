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

/** One pacticipant bound to the project, as the REST route lists it. */
export interface PactBadgeItem {
  slug: string;
  name: string;
  status: PactBadgeStatus;
  pacts: number;
  badge_url: string;
}

const STATUSES: readonly string[] = ['verified', 'failing', 'unknown'];

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
        badge_url: e.badge_url,
      });
    }
  }
  return items;
}
