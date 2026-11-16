/**
 * Upstream URL for the Browse `changelog.md` route (PCX-2.1, #5896): the REST
 * `GET /v1/browse/tenants/{t}/projects/{p}/changelog.md` endpoint with the page's filters.
 * Framework-free so the forwarding rule is unit-tested.
 */

import { changelogFilterQuery, parseChangelogFilters } from './projectChangelog';

/**
 * Build the REST URL for a project's Markdown changelog, forwarding only the recognised filters
 * (`severity`, `pathGroup`, `since`) — any other query parameter is dropped.
 *
 * @param restBase - REST root ending in `/v1` (a trailing slash is tolerated).
 * @param tenantSlug - Tenant slug.
 * @param projectSlug - Project slug.
 * @param search - The incoming request's query parameters.
 * @returns The absolute upstream URL.
 */
export function changelogMarkdownUpstreamUrl(
  restBase: string,
  tenantSlug: string,
  projectSlug: string,
  search: URLSearchParams
): string {
  const filters = parseChangelogFilters({
    severity: search.get('severity') ?? undefined,
    pathGroup: search.get('pathGroup') ?? undefined,
    since: search.get('since') ?? undefined,
  });
  const root = restBase.replace(/\/+$/, '');
  return (
    `${root}/browse/tenants/${encodeURIComponent(tenantSlug)}/projects/${encodeURIComponent(projectSlug)}/changelog.md` +
    changelogFilterQuery(filters)
  );
}
