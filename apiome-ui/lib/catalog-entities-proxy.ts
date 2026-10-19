/**
 * Shared pieces of the `/api/catalog/entities*` proxy routes — CDG-5.1 (#5979).
 *
 * Auth, forwarding and the error contract are the connectors proxy's; this adds the URL builder for
 * paths below `/v1/catalog/{slug}`.
 */

import { REST_API_BASE_URL } from '@lib/rest-auth';

export { forwardConnectorRequest as forwardCatalogRequest, resolveConnectorTenant as resolveCatalogTenant } from '@lib/connectors-proxy';

/** What the browser is told when apiome-rest cannot be reached. */
export const CATALOG_UNAVAILABLE = 'The catalog is unavailable (apiome-rest not reachable). Try again shortly.';

/**
 * The REST URL of a path below `/v1/catalog/{slug}`.
 *
 * @param slug - Tenant slug.
 * @param path - Path below the tenant, e.g. `entities` or `entities/summary`.
 */
export function catalogUrl(slug: string, path: string): string {
  return `${REST_API_BASE_URL}/catalog/${encodeURIComponent(slug)}/${path}`;
}
