/**
 * API products in the UI — APX-1.1 (#6098).
 *
 * An API product bundles Projects (at a version, a `2.x` range or latest), MCP servers and catalog
 * items under one name, owner team, visibility and lifecycle state (apiome-rest
 * `/v1/tenants/{t}/products`). This module holds the wire types, the words the screens use for each
 * value, the proxy's allow-list (which paths and methods `/api/products/…` forwards, and which body
 * fields each write may carry) and the small pure rules the list and editor share. Plans (APX-1.2)
 * have their own module, `@lib/api-plans`; their paths go through the same proxy.
 */

import { PLAN_CREATE_FIELDS, PLAN_MIGRATE_FIELDS, PLAN_PATCH_FIELDS } from './api-plans';

/** Where the products list lives (Ship → Products). */
export const PRODUCTS_HREF = '/ade/dashboard/products';

export const PRODUCT_VISIBILITIES = ['private', 'workspace', 'portal'] as const;
export type ProductVisibility = (typeof PRODUCT_VISIBILITIES)[number];

export const PRODUCT_STATES = ['draft', 'published', 'deprecated', 'retired'] as const;
export type ProductState = (typeof PRODUCT_STATES)[number];

export const PRODUCT_MEMBER_KINDS = ['project_latest', 'project_version', 'mcp_server', 'catalog_item'] as const;
export type ProductMemberKind = (typeof PRODUCT_MEMBER_KINDS)[number];

/** How each visibility reads, and what it means. */
export const VISIBILITY_LABELS: Readonly<Record<ProductVisibility, { label: string; hint: string }>> = {
  private: { label: 'Private', hint: 'Only the owner team and workspace admins see it.' },
  workspace: { label: 'Workspace', hint: 'Everyone in this workspace sees it.' },
  portal: { label: 'Portal', hint: 'Listed on the developer portal. Every member must be published.' },
};

/** How each lifecycle state reads. */
export const STATE_LABELS: Readonly<Record<ProductState, string>> = {
  draft: 'Draft',
  published: 'Published',
  deprecated: 'Deprecated',
  retired: 'Retired',
};

/** How each member kind reads in the editor's kind picker. */
export const MEMBER_KIND_LABELS: Readonly<Record<ProductMemberKind, { label: string; hint: string }>> = {
  project_latest: { label: 'Project at latest', hint: 'Follows every new publish of the project.' },
  project_version: { label: 'Project at a version', hint: 'An exact version (1.4.0) or a range (2.x).' },
  mcp_server: { label: 'MCP server', hint: 'An MCP server from the catalog.' },
  catalog_item: { label: 'Catalog item', hint: 'A spec in the catalog that is not a project.' },
};

/** The team that owns a product. */
export interface ProductOwnerTeam {
  slug: string;
  name: string;
}

/** The version a Project member resolves to today. */
export interface ProductMemberVersion {
  id: string;
  label: string | null;
  published: boolean;
}

/** One member, as REST returns it. */
export interface ProductMember {
  id: string;
  kind: ProductMemberKind;
  ref: string;
  slug: string | null;
  name: string | null;
  version_selector: string | null;
  environment: string | null;
  resolved_version: ProductMemberVersion | null;
  published: boolean;
  missing: boolean;
  created_at: string | null;
}

/** One product, as REST returns it. `members` and `portal_ready` come with single-product reads. */
export interface ApiProduct {
  id: string;
  slug: string;
  name: string;
  summary: string | null;
  owner_team: ProductOwnerTeam | null;
  visibility: ProductVisibility;
  state: ProductState;
  /** APX-1.4 (#6101): when the product was deprecated, when it retires, the message, when it retired. */
  deprecated_at?: string | null;
  retire_at?: string | null;
  retired_at?: string | null;
  deprecation_message?: string | null;
  member_count: number;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  members: ProductMember[] | null;
  portal_ready: boolean | null;
}

/** A product to create. */
export interface ApiProductInput {
  name: string;
  slug?: string;
  summary?: string;
  owner_team?: string;
  visibility?: ProductVisibility;
  state?: ProductState;
}

/** A partial update; `null` clears `summary` or `owner_team`. */
export interface ApiProductPatch {
  name?: string;
  summary?: string | null;
  owner_team?: string | null;
  visibility?: ProductVisibility;
  state?: ProductState;
  /** Deprecated products only (APX-1.4). */
  retire_at?: string | null;
  deprecation_message?: string | null;
}

/** A member to add. */
export interface ProductMemberInput {
  kind: ProductMemberKind;
  ref: string;
  version?: string;
  environment?: string;
}

/** A product slug: lowercase letters, digits and hyphens (REST's shape). */
const SLUG = /^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$/;
/** A member id (a UUID). */
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

/**
 * Whether a value has the product-slug shape.
 *
 * @param value - The candidate.
 * @returns True for a valid slug.
 */
export function isProductSlug(value: string): boolean {
  return SLUG.test(value);
}

/**
 * The UI page of one product.
 *
 * @param slug - The product's slug.
 * @returns Its editor's path.
 */
export function productHref(slug: string): string {
  return `${PRODUCTS_HREF}/${encodeURIComponent(slug)}`;
}

/** The HTTP methods the products proxy forwards. */
export type ProductProxyMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

/**
 * The REST path (below `/v1/tenants/{t}/`) a proxied request goes to, or `null` when the proxy does
 * not forward that path with that method.
 *
 * | Segments                   | Methods            |
 * | -------------------------- | ------------------ |
 * | (none)                     | GET, POST          |
 * | `{slug}`                   | GET, PATCH, DELETE |
 * | `{slug}/members`           | GET, POST          |
 * | `{slug}/members/{id}`      | DELETE             |
 * | `{slug}/plans`             | GET, POST          |
 * | `{slug}/plans/{plan}`      | GET, PATCH, DELETE |
 * | `{slug}/plans/{plan}/migrate` | POST           |
 *
 * @param segments - The path segments after `/api/products`.
 * @param method - The HTTP method.
 * @returns The REST path, or `null`.
 */
export function productProxyPath(segments: readonly string[], method: ProductProxyMethod): string | null {
  const [slug, sub, childId, action, ...rest] = segments;
  if (rest.length > 0) return null;
  if (action !== undefined) {
    // APX-1.4 (#6101): the one action below a plan.
    const ok = sub === 'plans' && action === 'migrate' && method === 'POST';
    return ok && isProductSlug(slug ?? '') && isProductSlug(childId ?? '') ? `products/${slug}/plans/${childId}/migrate` : null;
  }
  if (slug === undefined) return method === 'GET' || method === 'POST' ? 'products' : null;
  if (!isProductSlug(slug)) return null;
  const base = `products/${slug}`;
  if (sub === undefined) return method === 'POST' ? null : base;
  if (sub === 'plans') {
    // APX-1.2 (#6099): a plan slug has the product slug's shape.
    if (childId === undefined) return method === 'GET' || method === 'POST' ? `${base}/plans` : null;
    return method !== 'POST' && isProductSlug(childId) ? `${base}/plans/${childId}` : null;
  }
  if (sub !== 'members') return null;
  if (childId === undefined) return method === 'GET' || method === 'POST' ? `${base}/members` : null;
  return method === 'DELETE' && UUID.test(childId) ? `${base}/members/${childId}` : null;
}

/** The body fields each write may carry. */
const CREATE_FIELDS = ['name', 'slug', 'summary', 'owner_team', 'visibility', 'state'] as const;
const PATCH_FIELDS = ['name', 'summary', 'owner_team', 'visibility', 'state', 'retire_at', 'deprecation_message'] as const;
const MEMBER_FIELDS = ['kind', 'ref', 'version', 'environment'] as const;

/**
 * Keep only the fields a write to `path` may carry, so the proxy never forwards anything else.
 *
 * @param path - The REST path from {@link productProxyPath}.
 * @param method - `POST` or `PATCH`.
 * @param raw - The browser's body.
 * @returns The filtered body.
 */
export function productProxyBody(path: string, method: 'POST' | 'PATCH', raw: unknown): Record<string, unknown> {
  const source = raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  const plan = /^products\/[^/]+\/plans(\/|$)/.test(path);
  const fields: readonly string[] = path.endsWith('/migrate')
    ? PLAN_MIGRATE_FIELDS
    : plan
    ? method === 'PATCH'
      ? PLAN_PATCH_FIELDS
      : PLAN_CREATE_FIELDS
    : method === 'PATCH'
      ? PATCH_FIELDS
      : path.endsWith('/members')
        ? MEMBER_FIELDS
        : CREATE_FIELDS;
  const out: Record<string, unknown> = {};
  for (const field of fields) {
    if (field in source) out[field] = source[field];
  }
  return out;
}

/**
 * How a member's version reads: what it was added with and what it means today.
 *
 * @param member - The member.
 * @returns `latest → 1.4.0`, `2.x → 2.3.1`, `2.x → nothing yet`, or `null` for a member with no
 *   versions (an MCP server).
 */
export function memberVersionText(member: ProductMember): string | null {
  if (member.kind === 'mcp_server') return null;
  const asked = member.kind === 'project_version' ? member.version_selector ?? '' : 'latest';
  if (member.kind === 'catalog_item') return member.resolved_version?.label ?? null;
  return `${asked} → ${member.resolved_version?.label ?? 'nothing yet'}`;
}

/**
 * Validate the add-member form before it is sent.
 *
 * @param input - The form's values.
 * @returns The message to show, or `null` when the member can be sent.
 */
export function memberInputError(input: ProductMemberInput): string | null {
  if (!input.ref.trim()) return 'Name the member by its slug or id.';
  if (input.kind === 'project_version' && !(input.version ?? '').trim()) {
    return 'A project at a version needs a version, like 1.4.0 or 2.x.';
  }
  return null;
}

/**
 * The members that keep a product off the portal.
 *
 * @param members - The product's members.
 * @returns The unpublished ones, in order.
 */
export function unpublishedMembers(members: readonly ProductMember[]): ProductMember[] {
  return members.filter((member) => !member.published);
}
