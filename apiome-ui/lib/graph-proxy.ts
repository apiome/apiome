/**
 * Shared forwarding for the `/api/graph/*` proxy routes (CDG-3.4, #5969).
 *
 * The graph reads live under `/v1/graph/{tenant}/…` rather than `/v1/tenants/{tenant}/…`, so the
 * URL builder is its own; auth, forwarding and the error contract are the connectors proxy's.
 * Permissions (`projects:view`) are REST's.
 */

import { REST_API_BASE_URL } from '@lib/rest-auth';
import { GRAPH_EDGE_KINDS, GRAPH_NODE_KINDS, GRAPH_PROVENANCES } from '@lib/graph';

export { forwardConnectorRequest as forwardGraphRequest, resolveConnectorTenant as resolveGraphTenant } from '@lib/connectors-proxy';

/**
 * The REST URL of one path below `/v1/graph/{slug}`.
 *
 * @param slug - Tenant slug.
 * @param path - Path below the tenant, e.g. `entities` or `blast-radius`.
 */
export function graphUrl(slug: string, path: string): string {
  return `${REST_API_BASE_URL}/graph/${encodeURIComponent(slug)}/${path}`;
}

/** Copy only the allowed, well-formed query parameters onto a REST query string. */
export function forwardedQuery(
  params: URLSearchParams,
  allowed: Readonly<Record<string, 'repeat' | 'single'>>
): string {
  const out = new URLSearchParams();
  for (const [key, mode] of Object.entries(allowed)) {
    const values = mode === 'repeat' ? params.getAll(key) : [params.get(key)].filter((v): v is string => v !== null);
    for (const value of values) {
      if (!value || value.length > 200) continue;
      if (key === 'kind' && mode === 'repeat' && !isAllowedKind(value)) continue;
      if (key === 'provenance' && !(GRAPH_PROVENANCES as readonly string[]).includes(value)) continue;
      out.append(key, value);
    }
  }
  const query = out.toString();
  return query ? `?${query}` : '';
}

function isAllowedKind(value: string): boolean {
  return (GRAPH_NODE_KINDS as readonly string[]).includes(value) || (GRAPH_EDGE_KINDS as readonly string[]).includes(value);
}
