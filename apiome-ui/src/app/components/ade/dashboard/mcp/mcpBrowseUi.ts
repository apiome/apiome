/**
 * Private MCP browse view — shared types & pure presentation helpers (V2-MCP-23.1 / MCAT-9.1).
 *
 * The browse list page and the endpoint detail page both consume the apiome-rest MCP
 * catalog API through the Next.js proxy routes under `/api/mcp/*`. This module holds the wire
 * types and the *pure* adapter/format helpers that turn those payloads into what the views
 * render — kept free of React so they can be unit-tested directly.
 */

/** Badge variants available from the shared UI Badge component. */
export type McpBadgeVariant = 'default' | 'secondary' | 'success' | 'warning' | 'error' | 'outline';

/**
 * Validated branding a server advertised in its `initialize` `serverInfo` (V2-MCP-34.2, #4656).
 *
 * Every field is an already-guarded (https-only, SSRF-safe, length-bounded) *reference* the card
 * renders directly — the icon as an `<img>`, the website as a link. The whole object is `null` on a
 * snapshot when the server advertised no usable branding, and the card falls back to its text form.
 * Defined here (the lowest-level MCP UI module) so both the browse and version views can share it.
 */
export interface McpServerBranding {
  /** The server's advertised website URL, or `null`. */
  website_url: string | null;
  /** A URL for the server's display icon/logo, or `null`. */
  icon_url: string | null;
  /** The declared MIME type of {@link icon_url} (e.g. `image/png`), or `null`; descriptive only. */
  icon_mime_type: string | null;
}

/** One endpoint as returned by `GET /v1/mcp/{slug}/browse`. */
export interface McpBrowseEndpoint {
  id: string;
  name: string;
  slug: string;
  host: string;
  endpoint_url: string;
  transport: string;
  description: string | null;
  category: string | null;
  visibility: string;
  /**
   * The endpoint's auth scheme (e.g. `bearer` / `oauth` / `none`) when the catalog surfaces it.
   * The browse payload does not always include it (auth lives on the credential record), so it is
   * parsed defensively and the catalog's auth facet/badge only appear when a value is present.
   */
  auth_scheme: string | null;
  published: boolean;
  enabled: boolean;
  quarantined: boolean;
  last_discovered_at: string | null;
  last_discovery_status: string | null;
  current_version_id: string | null;
  score: number | null;
  grade: string | null;
  /** The current snapshot's advertised branding (logo/site), or `null` when none was advertised. */
  server_branding: McpServerBranding | null;
  tool_count: number;
  resource_count: number;
  resource_template_count: number;
  prompt_count: number;
  capability_count: number;
  /** The current snapshot's reported MCP protocol version, or `null` when unreported (35.1). */
  protocol_version: string | null;
  /** Server-derived discovery health: `healthy` / `failing` / `undiscovered` / `disabled` / `quarantined`. */
  health: string;
  /** True when the current surface has a tool asserting `destructiveHint: true` (35.1). */
  has_destructive: boolean;
  /** True when the current surface has tools and every one asserts `readOnlyHint: true` (35.1). */
  read_only_only: boolean;
  /** Server-derived complexity band: `simple` / `moderate` / `complex` / `unknown` (35.1). */
  complexity_band: string;
  /** Catalog freshness: `fresh` / `stale` / `failing` / `backoff` / `quarantined` (36.2). */
  freshness: string;
  /** Last successful discovery snapshot time, when known (36.2). */
  last_known_good_at: string | null;
}

/** A host bucket: every cataloged endpoint that shares one host. */
export interface McpBrowseHostGroup {
  host: string;
  endpoint_count: number;
  capability_count: number;
  endpoints: McpBrowseEndpoint[];
}

/** One lifecycle signal the server's own text or annotations carry for a capability (34.4). */
export interface McpLifecycleSignal {
  id: string;
  /** The stage this signal asserts: `deprecated` / `experimental` / `beta` / `stable`. */
  stage: string;
  /** What matched: `annotation_flag` / `annotation_status` / `name_token` / `description_phrase`. */
  kind: string;
  /** Where it matched: `annotations` / `name` / `title` / `description`. */
  source: string;
  /** The verbatim matched annotation (`key=value`), token, or phrase. */
  matched: string;
  /** Bounded context excerpt around the match (may be empty for annotation matches). */
  excerpt: string;
}

/**
 * A capability's lifecycle assessment, computed server-side by the pure detector (34.4).
 *
 * `stage` is the roll-up a badge renders: `deprecated` / `experimental` / `beta` /
 * `stable` (explicitly declared by an annotation only) / `unspecified`. `unspecified`
 * means the server said nothing — deliberately never rendered as "stable".
 */
export interface McpCapabilityLifecycle {
  stage: string;
  signals: McpLifecycleSignal[];
  signals_truncated: number;
}

/** One normalized capability item (tool / resource / resource_template / prompt). */
export interface McpCapabilityItem {
  item_type: string;
  name: string;
  title: string | null;
  description: string | null;
  uri: string | null;
  uri_template: string | null;
  /** Tool argument schema (JSON Schema), when the item declares one. */
  input_schema: Record<string, unknown> | null;
  /** Tool structured-result schema (JSON Schema), when declared. */
  output_schema: Record<string, unknown> | null;
  /** Behavioural annotations / hints the server published for the item. */
  annotations: Record<string, unknown> | null;
  /** Stable position within its kind, as returned by the catalog. */
  ordinal: number;
  /** Server-computed lifecycle assessment, or `null` when the API predates it. */
  lifecycle: McpCapabilityLifecycle | null;
}

/** A version snapshot's full surface as returned by the version-detail read. */
export interface McpVersionDetail {
  id: string;
  version_seq: number;
  version_tag: string | null;
  server_name: string | null;
  server_version: string | null;
  server_title: string | null;
  protocol_version: string | null;
  instructions: string | null;
  score: number | null;
  grade: string | null;
  is_current: boolean;
  discovered_at: string | null;
  items: McpCapabilityItem[];
}

/** An endpoint's catalog record as returned by the endpoint-detail read. */
export interface McpEndpointDetail {
  id: string;
  name: string;
  slug: string;
  endpoint_url: string;
  transport: string;
  description: string | null;
  category: string | null;
  visibility: string;
  published: boolean;
  enabled: boolean;
  /** Periodic re-discovery cadence in seconds, or `null` when the endpoint uses the default. */
  discovery_cadence_seconds: number | null;
  current_version_id: string | null;
  last_discovered_at: string | null;
  /** Outcome of the most recent discovery run (e.g. `changed` / `unchanged` / `failed`), or `null`
   *  before the first discovery — drives the profile card's health pill. */
  last_discovery_status: string | null;
  /** How the endpoint entered the catalog (`manual` / `registry` / `import`, V2-MCP-34.5). */
  added_via: string;
}

/** The display label and grouping order for each capability kind. */
export const MCP_CAPABILITY_KINDS: ReadonlyArray<{ key: string; label: string }> = [
  { key: 'tool', label: 'Tools' },
  { key: 'resource', label: 'Resources' },
  { key: 'resource_template', label: 'Resource templates' },
  { key: 'prompt', label: 'Prompts' },
];

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asInt(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : 0;
}

function asScore(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : null;
}

/** Coerce a value to a plain JSON object, or NULL for anything that is not one (arrays included). */
function asObject(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Parse one browse-endpoint object defensively (missing/invalid fields fall back to safe defaults). */
/**
 * Parse a `server_branding` block defensively into {@link McpServerBranding}, or `null`.
 *
 * A non-object payload, or one whose fields are all absent/blank, yields `null` so the card falls
 * back to its text form. The REST side has already validated each URL (https-only, SSRF-safe), so
 * this is a shape guard, not a security boundary — but it stays strict (only non-empty strings) so a
 * malformed payload never produces a broken `<img>`/link.
 */
export function mcpServerBrandingFromPayload(raw: unknown): McpServerBranding | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const website_url = asString(r.website_url);
  const icon_url = asString(r.icon_url);
  const icon_mime_type = asString(r.icon_mime_type);
  if (website_url === null && icon_url === null && icon_mime_type === null) return null;
  return { website_url, icon_url, icon_mime_type };
}

export function mcpBrowseEndpointFromPayload(raw: unknown): McpBrowseEndpoint {
  const r = (raw ?? {}) as Record<string, unknown>;
  return {
    id: String(r.id ?? ''),
    name: String(r.name ?? ''),
    slug: String(r.slug ?? ''),
    host: String(r.host ?? '(local)'),
    endpoint_url: String(r.endpoint_url ?? ''),
    transport: String(r.transport ?? ''),
    description: asString(r.description),
    category: asString(r.category),
    visibility: String(r.visibility ?? 'private'),
    auth_scheme: asString(r.auth_scheme) ?? asString(r.auth_type) ?? asString(r.auth),
    published: r.published === true,
    enabled: r.enabled !== false,
    quarantined: r.quarantined === true,
    last_discovered_at: asString(r.last_discovered_at),
    last_discovery_status: asString(r.last_discovery_status),
    current_version_id: asString(r.current_version_id),
    score: asScore(r.score),
    grade: asString(r.grade),
    server_branding: mcpServerBrandingFromPayload(r.server_branding),
    tool_count: asInt(r.tool_count),
    resource_count: asInt(r.resource_count),
    resource_template_count: asInt(r.resource_template_count),
    prompt_count: asInt(r.prompt_count),
    capability_count: asInt(r.capability_count),
    protocol_version: asString(r.protocol_version),
    health: asString(r.health) ?? 'undiscovered',
    has_destructive: r.has_destructive === true,
    read_only_only: r.read_only_only === true,
    complexity_band: asString(r.complexity_band) ?? 'unknown',
    freshness: r.quarantined === true ? 'quarantined' : asString(r.freshness) ?? 'fresh',
    last_known_good_at: asString(r.last_known_good_at),
  };
}

/** Parse the `groups` array from a `GET /v1/mcp/{slug}/browse` payload into host groups. */
export function mcpBrowseGroupsFromPayload(data: unknown): McpBrowseHostGroup[] {
  const payload = (data ?? {}) as Record<string, unknown>;
  const groups = Array.isArray(payload.groups) ? payload.groups : [];
  return groups.map((g) => {
    const group = (g ?? {}) as Record<string, unknown>;
    const endpoints = (Array.isArray(group.endpoints) ? group.endpoints : []).map(
      mcpBrowseEndpointFromPayload,
    );
    return {
      host: String(group.host ?? '(local)'),
      endpoint_count:
        typeof group.endpoint_count === 'number' ? asInt(group.endpoint_count) : endpoints.length,
      capability_count:
        typeof group.capability_count === 'number'
          ? asInt(group.capability_count)
          : endpoints.reduce((sum, e) => sum + e.capability_count, 0),
      endpoints,
    };
  });
}

/**
 * Parse a capability's `lifecycle` block defensively into {@link McpCapabilityLifecycle}.
 *
 * A non-object payload (older API) yields `null` — the card simply renders no lifecycle
 * badge. A malformed signal entry is dropped rather than producing a broken badge tooltip.
 */
export function mcpCapabilityLifecycleFromPayload(raw: unknown): McpCapabilityLifecycle | null {
  const r = asObject(raw);
  if (r === null) return null;
  const stage = asString(r.stage);
  if (stage === null) return null;
  const signals = (Array.isArray(r.signals) ? r.signals : [])
    .map((s) => asObject(s))
    .filter((s): s is Record<string, unknown> => s !== null)
    .map((s) => ({
      id: String(s.id ?? ''),
      stage: String(s.stage ?? ''),
      kind: String(s.kind ?? ''),
      source: String(s.source ?? ''),
      matched: String(s.matched ?? ''),
      excerpt: typeof s.excerpt === 'string' ? s.excerpt : '',
    }));
  return {
    stage,
    signals,
    signals_truncated: asInt(r.signals_truncated),
  };
}

/** Parse one capability item defensively. */
export function mcpCapabilityItemFromPayload(raw: unknown): McpCapabilityItem {
  const r = (raw ?? {}) as Record<string, unknown>;
  return {
    item_type: String(r.item_type ?? ''),
    name: String(r.name ?? ''),
    title: asString(r.title),
    description: asString(r.description),
    uri: asString(r.uri),
    uri_template: asString(r.uri_template),
    input_schema: asObject(r.input_schema),
    output_schema: asObject(r.output_schema),
    annotations: asObject(r.annotations),
    ordinal: asInt(r.ordinal),
    lifecycle: mcpCapabilityLifecycleFromPayload(r.lifecycle),
  };
}

/** Parse a `{ version: {...} }` version-detail payload into a {@link McpVersionDetail}. */
export function mcpVersionDetailFromPayload(data: unknown): McpVersionDetail | null {
  const payload = (data ?? {}) as Record<string, unknown>;
  const v = payload.version as Record<string, unknown> | undefined;
  if (!v || typeof v !== 'object') return null;
  const items = (Array.isArray(v.items) ? v.items : []).map(mcpCapabilityItemFromPayload);
  return {
    id: String(v.id ?? ''),
    version_seq: asInt(v.version_seq),
    version_tag: asString(v.version_tag),
    server_name: asString(v.server_name),
    server_title: asString(v.server_title),
    server_version: asString(v.server_version),
    protocol_version: asString(v.protocol_version),
    instructions: asString(v.instructions),
    score: asScore(v.score),
    grade: asString(v.grade),
    is_current: v.is_current === true,
    discovered_at: asString(v.discovered_at),
    items,
  };
}

/**
 * Build the PATCH body for the endpoint-detail Publish/Unpublish toggle.
 *
 * Publishing an MCP server means making it publicly discoverable — and the public catalog view
 * (`mcp_v_public_endpoints`, backing the apiome-browse MCP pages) lists only endpoints that
 * are `enabled` AND `published` AND `visibility = 'public'`. Toggling `published` alone leaves a
 * server at the default `visibility = 'private'`, so it would never appear in the browser. We
 * therefore set `published` and `visibility` together: publish → public, unpublish → private (so
 * the published/visibility badges stay coherent). Granular visibility control still lives in the
 * Settings tab for the rare "published but tenant-private" case.
 */
export function mcpPublishTogglePatch(
  currentlyPublished: boolean,
): { published: boolean; visibility: 'public' | 'private' } {
  return currentlyPublished
    ? { published: false, visibility: 'private' }
    : { published: true, visibility: 'public' };
}

/** Parse an `{ endpoint: {...} }` endpoint-detail payload into a {@link McpEndpointDetail}. */
export function mcpEndpointDetailFromPayload(data: unknown): McpEndpointDetail | null {
  const payload = (data ?? {}) as Record<string, unknown>;
  const e = payload.endpoint as Record<string, unknown> | undefined;
  if (!e || typeof e !== 'object') return null;
  return {
    id: String(e.id ?? ''),
    name: String(e.name ?? ''),
    slug: String(e.slug ?? ''),
    endpoint_url: String(e.endpoint_url ?? ''),
    transport: String(e.transport ?? ''),
    description: asString(e.description),
    category: asString(e.category),
    visibility: String(e.visibility ?? 'private'),
    published: e.published === true,
    enabled: e.enabled !== false,
    discovery_cadence_seconds: asScore(e.discovery_cadence_seconds),
    current_version_id: asString(e.current_version_id),
    last_discovered_at: asString(e.last_discovered_at),
    last_discovery_status: asString(e.last_discovery_status),
    added_via: asString(e.added_via) ?? 'manual',
  };
}

/** A collapsible JSON block to render under one capability item (a schema or its annotations). */
export interface McpItemDetailSection {
  key: 'input_schema' | 'output_schema' | 'annotations';
  label: string;
  /** Pretty-printed JSON ready to drop into a <pre>. */
  json: string;
}

/** Display order + human labels for an item's JSON detail sections. */
const MCP_ITEM_DETAIL_LABELS: ReadonlyArray<{ key: McpItemDetailSection['key']; label: string }> = [
  { key: 'input_schema', label: 'Input schema' },
  { key: 'output_schema', label: 'Output schema' },
  { key: 'annotations', label: 'Annotations' },
];

/** Pretty-print a JSON value for display; returns an empty string if it cannot be serialized. */
export function mcpFormatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return '';
  }
}

/** True when an object is absent or has no own keys (so there is nothing worth rendering). */
function isEmptyObject(obj: Record<string, unknown> | null): boolean {
  return !obj || Object.keys(obj).length === 0;
}

/**
 * Build the JSON detail sections to render for a capability item — its input schema, output
 * schema, and annotations — skipping any that are absent or empty. The order is stable
 * (input → output → annotations) so the UI renders predictably.
 */
export function mcpItemDetailSections(item: McpCapabilityItem): McpItemDetailSection[] {
  const byKey: Record<McpItemDetailSection['key'], Record<string, unknown> | null> = {
    input_schema: item.input_schema,
    output_schema: item.output_schema,
    annotations: item.annotations,
  };
  const sections: McpItemDetailSection[] = [];
  for (const { key, label } of MCP_ITEM_DETAIL_LABELS) {
    const value = byKey[key];
    if (!isEmptyObject(value)) {
      sections.push({ key, label, json: mcpFormatJson(value) });
    }
  }
  return sections;
}

/** One behavioural hint extracted from an item's `annotations` (a boolean tool hint). */
export interface McpAnnotationHint {
  key: string;
  label: string;
  value: boolean;
}

/** The MCP tool-annotation behavioural hints, in display order, with human labels. */
const MCP_ANNOTATION_HINTS: ReadonlyArray<{ key: string; label: string }> = [
  { key: 'readOnlyHint', label: 'Read-only' },
  { key: 'destructiveHint', label: 'Destructive' },
  { key: 'idempotentHint', label: 'Idempotent' },
  { key: 'openWorldHint', label: 'Open-world' },
];

/**
 * Extract the known boolean behavioural hints from a capability item's `annotations`, in spec
 * order. Absent or non-boolean hints are skipped, so the result holds only hints the server
 * actually declared — ready to render as chips/badges.
 */
export function mcpAnnotationHints(item: McpCapabilityItem): McpAnnotationHint[] {
  const annotations = item.annotations;
  if (!annotations) return [];
  const hints: McpAnnotationHint[] = [];
  for (const { key, label } of MCP_ANNOTATION_HINTS) {
    const value = annotations[key];
    if (typeof value === 'boolean') hints.push({ key, label, value });
  }
  return hints;
}

/** Group capability items by kind, in the canonical {@link MCP_CAPABILITY_KINDS} order. */
export function mcpGroupItemsByType(
  items: McpCapabilityItem[],
): Array<{ key: string; label: string; items: McpCapabilityItem[] }> {
  return MCP_CAPABILITY_KINDS.map(({ key, label }) => ({
    key,
    label,
    items: items.filter((it) => it.item_type === key),
  })).filter((group) => group.items.length > 0);
}

/** Map a 0-100 quality score to a Badge variant (NULL → neutral "secondary"). */
export function mcpScoreVariant(score: number | null): McpBadgeVariant {
  if (score === null) return 'secondary';
  if (score >= 90) return 'success';
  if (score >= 70) return 'default';
  if (score >= 50) return 'warning';
  return 'error';
}

/** Human-readable score+grade label, e.g. "87 · B"; "Unscored" when there is no score. */
export function mcpScoreLabel(score: number | null, grade: string | null): string {
  if (score === null) return 'Unscored';
  return grade ? `${score} · ${grade}` : String(score);
}

/** Format an ISO timestamp for the "last discovered" column; "Never" when absent/invalid. */
export function formatLastDiscovered(iso: string | null): string {
  if (!iso) return 'Never';
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return 'Never';
  return new Date(ms).toLocaleString();
}

/** True when an endpoint matches a free-text query (name / slug / host / URL / category). */
export function mcpEndpointMatchesQuery(endpoint: McpBrowseEndpoint, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    endpoint.name.toLowerCase().includes(q) ||
    endpoint.slug.toLowerCase().includes(q) ||
    endpoint.host.toLowerCase().includes(q) ||
    endpoint.endpoint_url.toLowerCase().includes(q) ||
    (endpoint.category ?? '').toLowerCase().includes(q)
  );
}

/**
 * Filter host groups by a free-text query, keeping only matching endpoints and dropping any
 * group left empty. Each surviving group's counts are recomputed from its filtered endpoints.
 */
export function mcpFilterGroups(groups: McpBrowseHostGroup[], query: string): McpBrowseHostGroup[] {
  if (!query.trim()) return groups;
  const result: McpBrowseHostGroup[] = [];
  for (const group of groups) {
    const endpoints = group.endpoints.filter((e) => mcpEndpointMatchesQuery(e, query));
    if (endpoints.length === 0) continue;
    result.push({
      host: group.host,
      endpoint_count: endpoints.length,
      capability_count: endpoints.reduce((sum, e) => sum + e.capability_count, 0),
      endpoints,
    });
  }
  return result;
}
