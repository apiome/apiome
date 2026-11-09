/**
 * Federated public MCP search: the published catalog plus an MCP registry — V2-MCP-26.4 / MCAT-12.4 (#3710).
 *
 * `/mcp/search?q=…&registry=1` searches the published public catalog as always and also asks an MCP
 * registry (`MCP_REGISTRY_SEARCH_URL`, the official registry by default) for servers whose names
 * match. This module holds the framework-free half so it is unit-testable under the browse Vitest
 * setup:
 *
 * 1. **Search the registry** — {@link fetchRegistryServers} reads one `GET /v0.1/servers?search=…`
 *    page (latest versions, a bounded timeout) and {@link parseRegistryServers} reads it, tolerating
 *    the flat and snake_case draft shapes and leaving out `deleted` and nameless entries.
 * 2. **Dedupe against published endpoints** — {@link federateRegistryEntries} drops every entry a
 *    published endpoint already is: same registry server name (case-insensitive; names are
 *    reverse-DNS), or one of the entry's remote URLs equal to the endpoint's URL ({@link urlKey}).
 *    The matching catalog endpoints are labeled with the registry name instead.
 * 3. **Label** — every result carries a provenance (`catalog` | `registry`) the page renders as a
 *    badge.
 *
 * It mirrors `apiome-rest/src/app/mcp_federated_search.py`, the tenant-scoped REST variant.
 */

/** The official MCP registry root — the default when `MCP_REGISTRY_SEARCH_URL` is unset. */
export const OFFICIAL_REGISTRY_URL = 'https://registry.modelcontextprotocol.io';

/** Most registry entries a federated search asks for. */
export const REGISTRY_SEARCH_LIMIT = 20;

/** Milliseconds the registry gets to answer before the page renders without it. */
export const REGISTRY_SEARCH_TIMEOUT_MS = 4000;

/** The `_meta` key of the official registry's status fields. */
const OFFICIAL_META_KEY = 'io.modelcontextprotocol.registry/official';

/** Registry remote types → catalog transports. */
const TRANSPORTS: Record<string, string> = { 'streamable-http': 'streamable_http', sse: 'sse' };

/** Where a search result came from. */
export type McpResultSource = 'catalog' | 'registry';

/** One MCP registry entry, as the public search page renders it. Credential-free. */
export interface McpRegistryEntry {
  source: 'registry';
  /** Reverse-DNS registry name (`io.github.acme/weather`). */
  serverName: string;
  title: string | null;
  description: string | null;
  version: string | null;
  /** `active` / `deprecated` (deleted entries never appear). */
  status: string | null;
  websiteUrl: string | null;
  /** The first concrete streamable-http / sse remote, or `null` for a package-only server. */
  remoteUrl: string | null;
  transport: string | null;
  host: string | null;
  /** {@link urlKey} of every concrete remote, for dedupe. Not rendered. */
  remoteKeys: string[];
}

/** A registry entry as handed to the browser (server-only dedupe keys removed). */
export type McpRegistryHit = Omit<McpRegistryEntry, 'remoteKeys'>;

/** A published endpoint a registry entry may duplicate (from the dedupe DB lookup). */
export interface McpPublishedEndpointRef {
  endpoint_id: string;
  registry_server_name: string | null;
  /** The stored endpoint URL. Server-only: compared, never sent to the browser. */
  endpoint_url: string;
}

/** The registry half of a federated search, deduped against the published catalog. */
export interface McpFederatedRegistryResult {
  /** Whether the registry was searched and answered. */
  included: boolean;
  /** The registry searched (root URL), or `null` when federation is off. */
  registryUrl: string | null;
  /** Entries the catalog does not already have, in the registry's order. */
  entries: McpRegistryHit[];
  /** Registry entries left out because a published endpoint already is that server. */
  duplicates: number;
  /** Endpoint id → registry server name, for the "In MCP Registry" badge on catalog hits. */
  serverNameByEndpoint: Record<string, string>;
  /** Why the registry results are missing (off, unreachable, refused), or `null`. */
  error: string | null;
}

/**
 * Turn a catalog query (websearch syntax) into the registry's plain substring `search` value.
 *
 * @param query - The sanitized search query.
 * @returns The query without quotes, parentheses, `OR` and `-excluded` words; `''` when nothing is left.
 */
export function registryQuery(query: string): string {
  return query
    .replace(/["()]/g, ' ')
    .split(/\s+/)
    .filter((w) => w && w !== 'OR' && !w.startsWith('-'))
    .join(' ');
}

/**
 * Reduce a registry root as configured to the root the client appends `/v0.1/servers` to.
 *
 * @param url - A registry URL (may end in `/`, `/v0.1` or `/v0.1/servers`).
 * @returns The root, or `''` when blank.
 */
export function normalizeRegistryBase(url: string): string {
  let base = (url || '').trim().replace(/\/+$/, '');
  for (const suffix of ['/v0.1/servers', '/v0.1']) {
    if (base.endsWith(suffix)) base = base.slice(0, -suffix.length).replace(/\/+$/, '');
  }
  return base;
}

/**
 * A comparable form of an MCP server URL, for deduping a registry remote against an endpoint.
 *
 * @param url - A registry remote URL or a stored endpoint URL (may carry userinfo).
 * @returns `scheme://host[:port]/path` with the scheme and host in lower case and no userinfo,
 *   query, fragment or trailing `/`; `null` for a non-`http(s)` or unparsable URL.
 */
export function urlKey(url: string | null | undefined): string | null {
  if (!url) return null;
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return null;
  }
  if ((parsed.protocol !== 'http:' && parsed.protocol !== 'https:') || !parsed.hostname) return null;
  const path = parsed.pathname.replace(/\/+$/, '');
  return `${parsed.protocol}//${parsed.host}${path}`;
}

/** A credential-free display URL (no userinfo, query or fragment), or `null`. */
function cleanUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url.trim());
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
    return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
  } catch {
    return null;
  }
}

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

/**
 * Read one `servers[]` element of a registry `ServerList`.
 *
 * @param element - The element: the v0.1 shape (`{server, _meta}`) or the older flat shape, in the
 *   camelCase draft or an earlier snake_case one.
 * @returns The entry, or `null` when it has no name or the registry marks it `deleted`.
 */
export function parseRegistryEntry(element: unknown): McpRegistryEntry | null {
  if (!isObject(element)) return null;
  const server = isObject(element.server) ? element.server : element;
  const meta = isObject(element._meta) ? element._meta : isObject(server._meta) ? server._meta : {};
  const official = isObject(meta[OFFICIAL_META_KEY]) ? (meta[OFFICIAL_META_KEY] as Json) : {};
  const serverName = text(server.name);
  if (!serverName) return null;
  const status = text(official.status)?.toLowerCase() ?? null;
  if (status === 'deleted') return null;

  const remotes = Array.isArray(server.remotes) ? server.remotes.filter(isObject) : [];
  const remoteKeys: string[] = [];
  let remoteUrl: string | null = null;
  let transport: string | null = null;
  for (const remote of remotes) {
    const raw = text(remote.url);
    if (!raw || raw.includes('{') || raw.includes('}')) continue;
    const key = urlKey(raw);
    if (key && !remoteKeys.includes(key)) remoteKeys.push(key);
    const type = (text(remote.type) ?? text(remote.transport_type) ?? text(remote.transportType) ?? '').toLowerCase();
    if (!remoteUrl && TRANSPORTS[type] && key) {
      remoteUrl = cleanUrl(raw);
      transport = TRANSPORTS[type];
    }
  }
  let host: string | null = null;
  if (remoteUrl) {
    try {
      host = new URL(remoteUrl).hostname;
    } catch {
      host = null;
    }
  }
  return {
    source: 'registry',
    serverName,
    title: text(server.title),
    description: text(server.description),
    version: text(server.version),
    status,
    websiteUrl: cleanUrl(text(server.websiteUrl) ?? text(server.website_url)),
    remoteUrl,
    transport,
    host,
    remoteKeys,
  };
}

/**
 * Read a registry `GET /v0.1/servers` body.
 *
 * @param body - The parsed JSON body.
 * @returns The readable entries, in listed order (unreadable, nameless and deleted ones left out).
 * @throws Error when the body has no `servers` list (not the v0.1 shape).
 */
export function parseRegistryServers(body: unknown): McpRegistryEntry[] {
  if (!isObject(body) || !Array.isArray(body.servers)) {
    throw new Error('The MCP registry answered with an unexpected body (no servers list).');
  }
  return body.servers.map(parseRegistryEntry).filter((e): e is McpRegistryEntry => e !== null);
}

/**
 * Ask an MCP registry for the latest versions of the servers whose names match `query`.
 *
 * @param query - The registry search term ({@link registryQuery}); blank returns `[]` without a call.
 * @param options.baseUrl - The registry root.
 * @param options.limit - Entries to ask for.
 * @param options.timeoutMs - Milliseconds before the request is aborted.
 * @param options.fetchImpl - The fetch to use (tests inject a fake registry).
 * @returns The entries, in the registry's order.
 * @throws Error when the registry times out, answers non-2xx, or answers with an unexpected body.
 */
export async function fetchRegistryServers(
  query: string,
  {
    baseUrl,
    limit = REGISTRY_SEARCH_LIMIT,
    timeoutMs = REGISTRY_SEARCH_TIMEOUT_MS,
    fetchImpl = fetch,
  }: { baseUrl: string; limit?: number; timeoutMs?: number; fetchImpl?: typeof fetch }
): Promise<McpRegistryEntry[]> {
  const term = query.trim();
  if (!term) return [];
  const params = new URLSearchParams({ search: term, limit: String(limit), version: 'latest' });
  const response = await fetchImpl(`${normalizeRegistryBase(baseUrl)}/v0.1/servers?${params.toString()}`, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(timeoutMs),
    cache: 'no-store',
  });
  if (!response.ok) {
    throw new Error(`The MCP registry answered HTTP ${response.status}.`);
  }
  return parseRegistryServers(await response.json());
}

/**
 * Dedupe registry entries against the published catalog and label both sides.
 *
 * @param entries - The registry entries the search found.
 * @param published - Published endpoints that may match (by registry name or URL host).
 * @returns The entries the catalog does not have, how many were duplicates, and endpoint id →
 *   registry name for every published endpoint known to a registry (its recorded name, or the
 *   entry it matched).
 */
export function federateRegistryEntries(
  entries: McpRegistryEntry[],
  published: McpPublishedEndpointRef[]
): { entries: McpRegistryEntry[]; duplicates: number; serverNameByEndpoint: Record<string, string> } {
  const byName = new Map<string, string>();
  const byUrl = new Map<string, string>();
  const serverNameByEndpoint: Record<string, string> = {};
  for (const row of published) {
    const name = row.registry_server_name?.trim();
    if (name) {
      if (!byName.has(name.toLowerCase())) byName.set(name.toLowerCase(), row.endpoint_id);
      serverNameByEndpoint[row.endpoint_id] = name;
    }
    const key = urlKey(row.endpoint_url);
    if (key && !byUrl.has(key)) byUrl.set(key, row.endpoint_id);
  }
  const kept: McpRegistryEntry[] = [];
  let duplicates = 0;
  for (const entry of entries) {
    const endpointId =
      byName.get(entry.serverName.toLowerCase()) ??
      entry.remoteKeys.map((k) => byUrl.get(k)).find((id): id is string => id !== undefined);
    if (endpointId !== undefined) {
      duplicates += 1;
      if (!serverNameByEndpoint[endpointId]) serverNameByEndpoint[endpointId] = entry.serverName;
      continue;
    }
    kept.push(entry);
  }
  return { entries: kept, duplicates, serverNameByEndpoint };
}

/**
 * The lower-case hosts of the entries' remotes, for the dedupe DB lookup.
 *
 * @param entries - Registry entries.
 * @returns Distinct hosts, sorted.
 */
export function registryRemoteHosts(entries: McpRegistryEntry[]): string[] {
  const hosts = new Set<string>();
  for (const entry of entries) {
    for (const key of entry.remoteKeys) {
      try {
        hosts.add(new URL(key).hostname.toLowerCase());
      } catch {
        // urlKey only yields parsable URLs; nothing to add otherwise.
      }
    }
  }
  return [...hosts].sort();
}

/**
 * Strip server-only fields before an entry is handed to a client component.
 *
 * @param entry - A registry entry.
 * @returns The entry without `remoteKeys`.
 */
export function toClientEntry(entry: McpRegistryEntry): McpRegistryHit {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { remoteKeys, ...rest } = entry;
  return rest;
}

/**
 * The `/mcp/search` URL for a query, an optional pinned sort mode and the registry toggle.
 *
 * @param query - The search query (trimmed here).
 * @param sort - A pinned sort mode, or `null` for the query default.
 * @param includeRegistry - Whether to also search the MCP registry (`registry=1`).
 * @returns The page path with its query string.
 */
export function mcpSearchHref(query: string, sort: string | null, includeRegistry: boolean): string {
  const params = new URLSearchParams({ q: query.trim() });
  if (sort) params.set('sort', sort);
  if (includeRegistry) params.set('registry', '1');
  return `/mcp/search?${params.toString()}`;
}
