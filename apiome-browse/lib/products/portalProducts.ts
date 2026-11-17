/**
 * API products on the portal — APX-1.3 (#6100).
 *
 * An **API product** (APX-1.1, apiome-db V387) bundles projects, versions and MCP servers into one
 * thing a consumer asks for ("Payments API"); its **plans** (APX-1.2, V388) are the tiers it offers
 * — how a consumer authenticates, the limits it promises, whether a person approves. Browse shows a
 * product on its tenant's portal when the product's `visibility` is `portal`.
 *
 * This module holds the pure rules the product page, the tenant page and search share: which
 * products and plans a reader may see, which version a member links to, and how a plan reads. It is
 * framework-free so the Vitest setup (node, `lib/**`) covers it; `lib/db/products.ts` runs the reads.
 *
 * **Never on the portal:** a plan's `billing_ref` (an external billing id), its `environments`
 * (gateway config ids), `declared_only`, and an OAuth plan's `idp_config_id`. The reads do not select
 * them and {@link toPortalPlan} copies only the fields a reader may see, so a column added later
 * stays private until someone lists it here.
 */

/** Product states a reader sees: a draft is not offered yet and a retired product is gone. */
export const PORTAL_PRODUCT_STATES = ['published', 'deprecated'] as const;

/** Plan states a reader sees, for the same reasons. */
export const PORTAL_PLAN_STATES = ['published', 'deprecated'] as const;

/** A product or plan state shown on the portal. */
export type PortalState = (typeof PORTAL_PRODUCT_STATES)[number];

/** How a plan's consumers authenticate (V388 `auth_strategy`). */
export type AuthStrategy = 'key_auth' | 'oauth2_client_credentials' | 'mtls' | 'none';

/** Whether a subscription is approved at once or by a person (V388 `approval`). */
export type Approval = 'auto' | 'manual';

/** One declared limit: so many requests per window. */
export interface PlanLimit {
  window: 'second' | 'minute' | 'hour' | 'day' | 'month';
  requests: number;
}

/** A plan as the portal shows it — never its billing reference, environments or IdP config id. */
export interface PortalPlan {
  slug: string;
  name: string;
  description: string | null;
  authStrategy: AuthStrategy;
  /** `key_auth` only: the header the key travels in, when the plan names one. */
  headerName: string | null;
  /** `oauth2_client_credentials` only: the scopes a client is granted. */
  scopes: string[];
  limits: PlanLimit[];
  concurrency: number | null;
  approval: Approval;
  credentialTtlDays: number | null;
  termsUrl: string | null;
  pricingNote: string | null;
  state: PortalState;
}

/** What a product member is (V387 `member_kind`). */
export type MemberKind = 'project_version' | 'project_latest' | 'mcp_server' | 'catalog_item';

/** One member as the portal shows it, with where it links (null when a reader cannot open it). */
export interface PortalMember {
  kind: MemberKind;
  name: string;
  /** The version label a Project member resolves to on the portal, or null. */
  versionLabel: string | null;
  /** The `project_version` selector (`1.4.0`, `2.x`), or null. */
  versionSelector: string | null;
  environment: string | null;
  /** The Browse path the member opens, or null when it has no public page. */
  href: string | null;
}

/** A product as its portal page shows it. */
export interface PortalProduct {
  slug: string;
  name: string;
  summary: string | null;
  state: PortalState;
  ownerTeam: string | null;
  tenantSlug: string;
  tenantName: string;
  updatedAt: string | null;
  members: PortalMember[];
  plans: PortalPlan[];
}

/** A product as the tenant page's list and search show it. */
export interface PortalProductSummary {
  slug: string;
  name: string;
  summary: string | null;
  state: PortalState;
  memberCount: number;
  planCount: number;
}

/** A version of a member's project: its label, newest publish first. */
export interface PublicVersionRow {
  label: string;
}

/**
 * The Browse path of a product page.
 *
 * @param tenantSlug - The tenant (portal) the product belongs to.
 * @param productSlug - The product's slug.
 * @returns `/tenant/<tenant>/products/<product>`.
 */
export function productHref(tenantSlug: string, productSlug: string): string {
  return `/tenant/${encodeURIComponent(tenantSlug)}/products/${encodeURIComponent(productSlug)}`;
}

/** A version label without a leading `v` (`v2.1.0` → `2.1.0`), for range comparison. */
function bare(label: string): string {
  return /^[vV]\d/.test(label) ? label.slice(1) : label;
}

/**
 * Whether a version label satisfies a `project_version` selector — the same rule as apiome-rest's
 * `app.api_products.selector_matches`.
 *
 * A selector ending in `.x` (`2.x`, `2.1.x`) is a range: it matches its prefix and every label below
 * it (`2`, `2.0.0`, `2.9.1`, not `20.1`), ignoring a leading `v` on both sides. Any other selector
 * matches its exact label.
 *
 * @param selector - The member's selector.
 * @param label - A version label.
 * @returns True when the label is within the selector.
 */
export function selectorMatches(selector: string, label: string | null | undefined): boolean {
  if (!label) return false;
  if (selector.toLowerCase().endsWith('.x')) {
    const prefix = bare(selector.slice(0, -2));
    const candidate = bare(label);
    return candidate === prefix || candidate.startsWith(`${prefix}.`);
  }
  return label === selector;
}

/**
 * The version a Project member opens on the portal: the newest *public, published* version it covers.
 *
 * apiome-rest falls back to an unpublished version so a draft product still shows what it points at;
 * the portal does not, because a reader cannot open one.
 *
 * @param kind - `project_latest` (every version) or `project_version` (the selector's).
 * @param selector - The `project_version` selector; ignored for `project_latest`.
 * @param versions - The project's public published versions, newest first.
 * @returns The label, or null when none is covered.
 */
export function pickPublicVersion(
  kind: MemberKind,
  selector: string | null,
  versions: readonly PublicVersionRow[]
): string | null {
  for (const row of versions) {
    if (kind !== 'project_version' || selectorMatches(selector ?? '', row.label)) return row.label;
  }
  return null;
}

/** The plain name of each auth strategy, as a plan card reads it. */
const AUTH_STRATEGY_LABELS: Readonly<Record<AuthStrategy, string>> = {
  key_auth: 'API key',
  oauth2_client_credentials: 'OAuth 2.0 client credentials',
  mtls: 'Mutual TLS',
  none: 'No authentication',
};

/**
 * The label of an auth strategy.
 *
 * @param strategy - The stored strategy.
 * @returns Its label; an unknown value reads as itself.
 */
export function authStrategyLabel(strategy: string): string {
  return AUTH_STRATEGY_LABELS[strategy as AuthStrategy] ?? strategy;
}

/**
 * The label of an approval mode.
 *
 * @param approval - `auto` or `manual`.
 * @returns "Approved automatically" or "Approved by the API team".
 */
export function approvalLabel(approval: string): string {
  return approval === 'auto' ? 'Approved automatically' : 'Approved by the API team';
}

/**
 * One limit as a plan card reads it: `100 requests / minute`, with thousands grouped.
 *
 * @param limit - The limit.
 * @returns The text.
 */
export function formatLimit(limit: PlanLimit): string {
  const count = new Intl.NumberFormat('en-US').format(limit.requests);
  return `${count} ${limit.requests === 1 ? 'request' : 'requests'} / ${limit.window}`;
}

/** Windows in ascending length, so a card lists `/ second` before `/ day`. */
const WINDOW_ORDER: readonly PlanLimit['window'][] = ['second', 'minute', 'hour', 'day', 'month'];

/**
 * Keep the well-formed limits of a stored `limits` value, shortest window first.
 *
 * @param raw - The stored JSON (an array of `{window, requests}`), or anything else.
 * @returns The limits; an entry with an unknown window or a non-positive count is dropped.
 */
export function normalizeLimits(raw: unknown): PlanLimit[] {
  if (!Array.isArray(raw)) return [];
  const limits: PlanLimit[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const { window, requests } = entry as { window?: unknown; requests?: unknown };
    const count = Number(requests);
    if (!WINDOW_ORDER.includes(window as PlanLimit['window']) || !Number.isInteger(count) || count <= 0) continue;
    limits.push({ window: window as PlanLimit['window'], requests: count });
  }
  return limits.sort((a, b) => WINDOW_ORDER.indexOf(a.window) - WINDOW_ORDER.indexOf(b.window));
}

/** A plan row as `lib/db/products.ts` selects it (snake_case, `auth_config` as stored). */
export interface PlanRow {
  slug: string;
  name: string;
  description: string | null;
  auth_strategy: string;
  auth_config: unknown;
  limits: unknown;
  concurrency: number | null;
  approval: string;
  credential_ttl_days: number | null;
  terms_url: string | null;
  pricing_note: string | null;
  state: string;
  [column: string]: unknown;
}

/**
 * Map a plan row to what the portal shows, copying only the public fields.
 *
 * Whatever else the row carries — `billing_ref`, `environments`, an IdP config id inside
 * `auth_config` — is left behind.
 *
 * @param row - The plan row.
 * @returns The portal plan.
 */
export function toPortalPlan(row: PlanRow): PortalPlan {
  const config = row.auth_config && typeof row.auth_config === 'object' ? (row.auth_config as Record<string, unknown>) : {};
  const strategy = row.auth_strategy as AuthStrategy;
  const headerName = strategy === 'key_auth' && typeof config.header_name === 'string' ? config.header_name : null;
  const scopes =
    strategy === 'oauth2_client_credentials' && Array.isArray(config.scopes)
      ? config.scopes.filter((scope): scope is string => typeof scope === 'string')
      : [];
  return {
    slug: row.slug,
    name: row.name,
    description: row.description,
    authStrategy: strategy,
    headerName,
    scopes,
    limits: normalizeLimits(row.limits),
    concurrency: row.concurrency ?? null,
    approval: row.approval === 'auto' ? 'auto' : 'manual',
    credentialTtlDays: row.credential_ttl_days ?? null,
    termsUrl: safeHttpUrl(row.terms_url),
    pricingNote: row.pricing_note,
    state: row.state === 'deprecated' ? 'deprecated' : 'published',
  };
}

/**
 * A terms link the page may render: only `http(s)` URLs (the database checks this too; a page link
 * never trusts that alone).
 *
 * @param raw - The stored URL.
 * @returns The URL, or null.
 */
export function safeHttpUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null;
  } catch {
    return null;
  }
}

/** A member row as `lib/db/products.ts` selects it. */
export interface MemberRow {
  kind: MemberKind;
  name: string | null;
  project_slug: string | null;
  mcp_slug: string | null;
  version_selector: string | null;
  environment: string | null;
}

/**
 * Map a member row to what the portal shows, with where it links.
 *
 * A Project member links to the version it resolves to; an MCP server to its public catalog page; a
 * catalog item has no Browse page and is listed by name only. A member with no public version (or a
 * private MCP server) is listed without a link.
 *
 * @param tenantSlug - The product's tenant.
 * @param row - The member row.
 * @param versions - The member project's public published versions, newest first.
 * @param mcpPublic - Whether the member MCP server is in the public catalog.
 * @returns The portal member.
 */
export function toPortalMember(
  tenantSlug: string,
  row: MemberRow,
  versions: readonly PublicVersionRow[],
  mcpPublic: boolean
): PortalMember {
  const tenant = encodeURIComponent(tenantSlug);
  let versionLabel: string | null = null;
  let href: string | null = null;
  if (row.kind === 'project_latest' || row.kind === 'project_version') {
    versionLabel = row.project_slug ? pickPublicVersion(row.kind, row.version_selector, versions) : null;
    if (row.project_slug && versionLabel) {
      href = `/tenant/${tenant}/${encodeURIComponent(row.project_slug)}/${encodeURIComponent(versionLabel)}`;
    }
  } else if (row.kind === 'mcp_server' && row.mcp_slug && mcpPublic) {
    href = `/mcp/${tenant}/${encodeURIComponent(row.mcp_slug)}`;
  }
  return {
    kind: row.kind,
    name: row.name ?? 'Unnamed member',
    versionLabel,
    versionSelector: row.kind === 'project_version' ? row.version_selector : null,
    environment: row.environment,
    href,
  };
}

/**
 * The label of a member's kind, as the members list reads it.
 *
 * @param kind - The member kind.
 * @returns "API", "MCP server" or "Catalog item".
 */
export function memberKindLabel(kind: MemberKind): string {
  if (kind === 'mcp_server') return 'MCP server';
  if (kind === 'catalog_item') return 'Catalog item';
  return 'API';
}
