/**
 * Where the `/api/usage` proxy forwards a request — RDG-5.4 (#5789).
 *
 * Pure, so the mapping is tested without Next.js: the route (`src/app/api/usage/[[...path]]`)
 * passes the REST base URL and the session's tenant slug.
 *
 * Tenant-wide resources are addressed with a **colon-prefixed marker** segment (a colon cannot
 * appear in a project slug), so a project can be called `retention` and still be reachable:
 *
 *   :retention                    -> {base}/tenants/{t}/usage/retention
 *   :toolsets/<id>/body-samples   -> {base}/tenants/{t}/agent-toolsets/<id>/body-samples
 *   <project>/sources[/<id>]      -> {base}/tenants/{t}/projects/<project>/usage/sources[/<id>]
 *   <project>/export              -> {base}/tenants/{t}/projects/<project>/usage/export
 */

/** The marker segment for the workspace's retention. */
export const USAGE_RETENTION_MARKER = ':retention';

/** The marker segment for an agent toolset's body-sample window. */
export const USAGE_TOOLSETS_MARKER = ':toolsets';

/** The project sub-resources the proxy forwards. Anything else is refused. */
const PROJECT_RESOURCES = new Set(['sources', 'export']);

/**
 * Build the upstream URL for a request.
 *
 * @param baseUrl The REST base URL (ending in `/v1`).
 * @param tenantSlug The session's tenant slug.
 * @param segments The path segments after `/api/usage`.
 * @returns The absolute REST URL, or `null` for a path the proxy does not serve.
 */
export function usageUpstreamPath(baseUrl: string, tenantSlug: string, segments: string[]): string | null {
  const tenant = `${baseUrl}/tenants/${encodeURIComponent(tenantSlug)}`;
  const [first, ...rest] = segments;
  if (!first) return null;
  if (first === USAGE_RETENTION_MARKER) return rest.length === 0 ? `${tenant}/usage/retention` : null;
  if (first === USAGE_TOOLSETS_MARKER) {
    const [toolsetId, leaf] = rest;
    if (!toolsetId || leaf !== 'body-samples' || rest.length !== 2) return null;
    return `${tenant}/agent-toolsets/${encodeURIComponent(toolsetId)}/body-samples`;
  }
  const [resource, ...tail] = rest;
  if (!resource || !PROJECT_RESOURCES.has(resource) || tail.length > 1) return null;
  if (resource === 'export' && tail.length) return null;
  const suffix = tail.map(encodeURIComponent).join('/');
  return `${tenant}/projects/${encodeURIComponent(first)}/usage/${resource}${suffix ? `/${suffix}` : ''}`;
}

/**
 * Whether the segments address the export (streamed as a file, not wrapped as JSON).
 *
 * @param segments The path segments after `/api/usage`.
 * @returns `true` for `<project>/export`.
 */
export function isUsageExport(segments: string[]): boolean {
  return segments.length === 2 && segments[1] === 'export' && !segments[0].startsWith(':');
}
