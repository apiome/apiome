/**
 * The tenant's agentic-web site manifests — `agents.json` and `llms.txt` (MFX-32.3, #4297).
 *
 * The documents are built by the REST API (`GET /v1/browse/tenants/{slug}/agents.json` and
 * `/llms.txt`) over the tenant's published, public artifacts only. Browse serves them at
 * `/tenant/{slug}/agents.json` and `/tenant/{slug}/llms.txt`, passing its own site root as
 * `site_url` so every link in them points back at this site's version pages.
 */

/** The two manifests Browse serves for a tenant. */
export type SiteManifestKind = 'agents.json' | 'llms.txt';

/** One "For agents" link on the tenant page — the Browse entry point to a manifest (MFX-32.5, #4299). */
export interface SiteManifestLink {
  /** The manifest it opens. */
  kind: SiteManifestKind;
  /** The site-relative address of the route handler that serves it (base path included). */
  href: string;
  /** What the manifest is, shown on hover. */
  title: string;
}

/** The manifests the tenant page links to, in the order they are shown. */
const MANIFEST_TITLES: Record<SiteManifestKind, string> = {
  'agents.json': 'Site manifest listing every published API and agent endpoint',
  'llms.txt': 'Markdown index of every published API, for language models',
};

/**
 * The "For agents" links the tenant page shows: one per manifest Browse serves for the tenant.
 *
 * @param tenantSlug - The tenant's slug (encoded into the path).
 * @param basePath - The Browse base path (`NEXT_PUBLIC_BASE_PATH`), `''` when served at the root.
 * @returns `agents.json` then `llms.txt`, each with its route-handler address and hover title.
 */
export function siteManifestLinks(tenantSlug: string, basePath: string): SiteManifestLink[] {
  const root = `${basePath.replace(/\/+$/, '')}/tenant/${encodeURIComponent(tenantSlug)}`;
  return (Object.keys(MANIFEST_TITLES) as SiteManifestKind[]).map((kind) => ({
    kind,
    href: `${root}/${kind}`,
    title: MANIFEST_TITLES[kind],
  }));
}

/** The local REST API root used when `NEXT_PUBLIC_REST_API_BASE_URL` is unset. */
const DEFAULT_REST_API_BASE_URL = 'http://localhost:8000/v1';

/**
 * The tenant's public, read-only xRegistry (MFX-34.2, #4307): the root of the xRegistry core API the
 * REST service serves over the tenant's published, public artifacts. An xRegistry client is pointed
 * here directly; it follows the registry's own `*url` links from there.
 *
 * @param tenantSlug - The tenant's slug (encoded into the path).
 * @param restApiBaseUrl - The REST API root ending in `/v1` (`NEXT_PUBLIC_REST_API_BASE_URL`).
 * @returns The absolute registry URL, `…/v1/browse/tenants/{slug}/xregistry`.
 */
export function xregistryRegistryUrl(tenantSlug: string, restApiBaseUrl?: string): string {
  const root = (restApiBaseUrl || DEFAULT_REST_API_BASE_URL).replace(/\/+$/, '');
  return `${root}/browse/tenants/${encodeURIComponent(tenantSlug)}/xregistry`;
}

/** What the route handlers need to reach the REST API (injectable for tests). */
export interface SiteManifestDeps {
  /** The REST API root, ending in `/v1` (`NEXT_PUBLIC_REST_API_BASE_URL`). */
  restApiBaseUrl: string;
  /** The Browse base path (`NEXT_PUBLIC_BASE_PATH`), `''` when served at the root. */
  basePath: string;
  /** `fetch`, or a stand-in in tests. */
  fetchImpl?: typeof fetch;
}

/**
 * The REST API root this server reaches, ending in `/v1`.
 *
 * The manifests are fetched by the Browse **server**, not the browser, so a server-side address wins:
 * `APIOME_REST_INTERNAL_BASE_URL` (for example `http://rest:8000/v1` inside a container network), else
 * the browser-facing `NEXT_PUBLIC_REST_API_BASE_URL`, else the local default.
 *
 * @param env - The environment to read (`process.env` by default).
 * @returns The REST API root.
 */
export function serverRestApiBaseUrl(env: Record<string, string | undefined> = process.env): string {
  return env.APIOME_REST_INTERNAL_BASE_URL || env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
}

/** How long a client or CDN may reuse a manifest (matches the REST route and the feeds). */
export const SITE_MANIFEST_CACHE_CONTROL = 'public, max-age=300';

/**
 * The Browse site root the manifest's links use: the request's origin plus the base path.
 *
 * @param requestUrl - The incoming request's URL.
 * @param basePath - The Browse base path, `''` at the root.
 * @returns For example `https://browse.example.com/apis`, without a trailing slash.
 */
export function siteRoot(requestUrl: string, basePath: string): string {
  return `${new URL(requestUrl).origin}${basePath.replace(/\/+$/, '')}`;
}

/**
 * The REST URL that builds one manifest for a tenant.
 *
 * @param kind - `agents.json` or `llms.txt`.
 * @param tenantSlug - The tenant's slug (encoded here).
 * @param site - The Browse site root (see {@link siteRoot}).
 * @param restApiBaseUrl - The REST API root, ending in `/v1`.
 * @returns The absolute URL to fetch.
 */
export function siteManifestRestUrl(
  kind: SiteManifestKind,
  tenantSlug: string,
  site: string,
  restApiBaseUrl: string
): string {
  const root = restApiBaseUrl.replace(/\/+$/, '');
  const query = new URLSearchParams({ site_url: site });
  return `${root}/browse/tenants/${encodeURIComponent(tenantSlug)}/${kind}?${query.toString()}`;
}

/**
 * Fetch one manifest from the REST API and answer the browser with it.
 *
 * A `404` (unknown tenant) is passed on as `404`; any other failure, or an unreachable API, is a
 * `502` with a plain-text reason, so a crawler never caches an error page as a manifest.
 *
 * @param kind - `agents.json` or `llms.txt`.
 * @param tenantSlug - The tenant's slug.
 * @param requestUrl - The incoming request's URL (its origin becomes the links' site).
 * @param deps - The REST root, base path and `fetch`.
 * @returns The response to send.
 */
export async function serveSiteManifest(
  kind: SiteManifestKind,
  tenantSlug: string,
  requestUrl: string,
  deps: SiteManifestDeps
): Promise<Response> {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const url = siteManifestRestUrl(kind, tenantSlug, siteRoot(requestUrl, deps.basePath), deps.restApiBaseUrl);
  let upstream: Response;
  try {
    upstream = await fetchImpl(url, { headers: { Accept: kind === 'agents.json' ? 'application/json' : 'text/plain' } });
  } catch {
    return new Response(`The ${kind} could not be built right now.`, { status: 502 });
  }
  if (upstream.status === 404) {
    return new Response('Not found', { status: 404 });
  }
  if (!upstream.ok) {
    return new Response(`The ${kind} could not be built right now.`, { status: 502 });
  }
  const body = await upstream.text();
  return new Response(body, {
    headers: {
      'Content-Type': kind === 'agents.json' ? 'application/json; charset=utf-8' : 'text/plain; charset=utf-8',
      'Cache-Control': SITE_MANIFEST_CACHE_CONTROL,
    },
  });
}
