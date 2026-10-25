/**
 * The vocabulary of things the catalog search can return, and how the UI groups them.
 *
 * A *kind* is one row type the SQL union produces (`operation`, `schema`, …). A *scope* is a tab on
 * the results page that bundles related kinds ("Operations" is operations plus their parameters,
 * bodies and responses). Both are URL-visible (`type=` and `scope=`), so the names here are a
 * contract with every shared link.
 *
 * Pure; shared by the SQL builder, the URL codec and the components.
 */

export const HIT_KINDS = [
  'organization',
  'project',
  'version',
  'tag',
  'operation',
  'parameter',
  'request_body',
  'response',
  'schema',
  'property',
] as const;

export type HitKind = (typeof HIT_KINDS)[number];

/** Singular / plural labels for each kind, as the chips and counts read them. */
export const HIT_KIND_LABELS: Readonly<Record<HitKind, { one: string; many: string }>> = {
  organization: { one: 'Organization', many: 'Organizations' },
  project: { one: 'Project', many: 'Projects' },
  version: { one: 'Version notes', many: 'Version notes' },
  tag: { one: 'Tag', many: 'Tags' },
  operation: { one: 'Operation', many: 'Operations' },
  parameter: { one: 'Parameter', many: 'Parameters' },
  request_body: { one: 'Request body', many: 'Request bodies' },
  response: { one: 'Response', many: 'Responses' },
  schema: { one: 'Schema', many: 'Schemas' },
  property: { one: 'Property', many: 'Properties' },
};

/**
 * Relative weight of each kind in the relevance ranking: when two items match the words equally
 * well, the one a visitor more likely wants comes first. Projects and operations lead because
 * they are what people navigate *to*; inline bodies and responses trail because they are what
 * people arrive *at*.
 */
export const HIT_KIND_WEIGHT: Readonly<Record<HitKind, number>> = {
  project: 9,
  organization: 8,
  operation: 8,
  schema: 7,
  tag: 5,
  version: 5,
  property: 4,
  parameter: 4,
  request_body: 2,
  response: 2,
};

export const SEARCH_SCOPES = ['all', 'operations', 'schemas', 'catalog', 'mcp'] as const;
export type SearchScope = (typeof SEARCH_SCOPES)[number];

/** Labels for the scope tabs. */
export const SEARCH_SCOPE_LABELS: Readonly<Record<SearchScope, string>> = {
  all: 'All',
  operations: 'Operations',
  schemas: 'Schemas',
  catalog: 'Projects & orgs',
  mcp: 'MCP servers',
};

/** The kinds each scope covers. `mcp` is served by a different engine, so it maps to none. */
export const SCOPE_KINDS: Readonly<Record<SearchScope, readonly HitKind[]>> = {
  all: HIT_KINDS,
  operations: ['operation', 'parameter', 'request_body', 'response'],
  schemas: ['schema', 'property'],
  catalog: ['organization', 'project', 'version', 'tag'],
  mcp: [],
};

/** Aliases a visitor may type after `type:`; the canonical kind names also work. */
const KIND_ALIASES: Readonly<Record<string, HitKind>> = {
  org: 'organization',
  tenant: 'organization',
  organisation: 'organization',
  api: 'project',
  notes: 'version',
  release: 'version',
  op: 'operation',
  path: 'operation',
  endpoint: 'operation',
  route: 'operation',
  param: 'parameter',
  query: 'parameter',
  header: 'parameter',
  body: 'request_body',
  request: 'request_body',
  requestbody: 'request_body',
  resp: 'response',
  model: 'schema',
  type: 'schema',
  class: 'schema',
  component: 'schema',
  field: 'property',
  prop: 'property',
  attribute: 'property',
};

/**
 * Resolve a `type:` value or URL token to a kind, or null when unknown.
 */
export function resolveHitKind(raw: string | null | undefined): HitKind | null {
  const key = (raw ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_');
  if ((HIT_KINDS as readonly string[]).includes(key)) return key as HitKind;
  return KIND_ALIASES[key.replace(/_/g, '')] ?? KIND_ALIASES[key] ?? null;
}

/**
 * Resolve a `scope=` token to a scope, defaulting to `all`.
 */
export function resolveScope(raw: string | null | undefined): SearchScope {
  const key = (raw ?? '').trim().toLowerCase();
  return (SEARCH_SCOPES as readonly string[]).includes(key) ? (key as SearchScope) : 'all';
}

/** The scope a kind belongs to (the tab a single-kind link should open on). */
export function scopeOfKind(kind: HitKind): SearchScope {
  for (const scope of ['operations', 'schemas', 'catalog'] as const) {
    if (SCOPE_KINDS[scope].includes(kind)) return scope;
  }
  return 'all';
}
