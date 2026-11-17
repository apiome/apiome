/**
 * The statements behind the portal's product pages — APX-1.3 (#6100).
 *
 * Pure strings, so a test can read them without a database: what each one gates on, and that none
 * selects a private column (`billing_ref`, `environments`, `declared_only`, `owner_team_id`).
 * `lib/db/products.ts` runs them.
 *
 * Every read gates on the same rules: the tenant is live; the product is live, `visibility =
 * 'portal'` and `published` or `deprecated` (a draft is not offered yet, a retired one is gone); a
 * plan is live and `published` or `deprecated`.
 */

import { PORTAL_PLAN_STATES, PORTAL_PRODUCT_STATES } from './portalProducts';

/** `('published', 'deprecated')` — the product states the portal lists. */
const PRODUCT_STATES = `(${PORTAL_PRODUCT_STATES.map((s) => `'${s}'`).join(', ')})`;

/** `('published', 'deprecated')` — the plan states the portal lists. */
const PLAN_STATES = `(${PORTAL_PLAN_STATES.map((s) => `'${s}'`).join(', ')})`;

/** The product's own gate, for a product aliased `ap` (catalog search joins the tenant itself). */
export const PORTAL_PRODUCT_ROW_GATES = `ap.visibility = 'portal'
         AND ap.state IN ${PRODUCT_STATES}
         AND ap.deleted_at IS NULL`;

/** The product gate, for a product aliased `ap` joined to its tenant `t`. */
export const PORTAL_PRODUCT_GATES = `${PORTAL_PRODUCT_ROW_GATES}
         AND t.deleted_at IS NULL`;

/** The plan gate, for a plan aliased `pl`. */
export const PORTAL_PLAN_GATES = `pl.state IN ${PLAN_STATES}
         AND pl.deleted_at IS NULL`;

/** `$1` tenant slug → the tenant's portal products, by name, with member and plan counts. */
export const PORTAL_PRODUCTS_FOR_TENANT_SQL = `
       SELECT ap.slug, ap.name, ap.summary, ap.state,
              (SELECT COUNT(*)::int FROM apiome.api_product_members m
                WHERE m.product_id = ap.id AND m.tenant_id = ap.tenant_id) AS member_count,
              (SELECT COUNT(*)::int FROM apiome.api_plans pl
                WHERE pl.product_id = ap.id AND pl.tenant_id = ap.tenant_id
                  AND ${PORTAL_PLAN_GATES}) AS plan_count
       FROM apiome.api_products ap
       JOIN apiome.tenants t ON t.id = ap.tenant_id
       WHERE t.slug = $1
         AND ${PORTAL_PRODUCT_GATES}
       ORDER BY lower(ap.name), ap.slug`;

/** `$1` tenant slug, `$2` product slug → the product with its tenant and owner team names. */
export const PORTAL_PRODUCT_SQL = `
       SELECT ap.id, ap.tenant_id, ap.slug, ap.name, ap.summary, ap.state, ap.updated_at,
              t.slug AS tenant_slug, t.name AS tenant_name,
              tm.name AS owner_team
       FROM apiome.api_products ap
       JOIN apiome.tenants t ON t.id = ap.tenant_id
       LEFT JOIN apiome.teams tm ON tm.id = ap.owner_team_id AND tm.deleted_at IS NULL
       WHERE t.slug = $1
         AND ap.slug = $2
         AND ${PORTAL_PRODUCT_GATES}
       LIMIT 1`;

/**
 * `$1` tenant id, `$2` product id → the members with their entities' names and slugs, Projects first
 * by name, then MCP servers. `mcp_public` says whether the MCP server is in the public catalog view.
 * A member whose entity was deleted is left out.
 */
export const PORTAL_PRODUCT_MEMBERS_SQL = `
       SELECT m.member_kind AS kind, m.member_ref::text AS ref, m.version_selector, m.environment,
              COALESCE(p.name, e.name) AS name,
              CASE WHEN m.member_kind IN ('project_latest', 'project_version') THEN p.slug END AS project_slug,
              e.slug AS mcp_slug,
              (pe.id IS NOT NULL) AS mcp_public
       FROM apiome.api_product_members m
       LEFT JOIN apiome.projects p
              ON m.member_kind <> 'mcp_server' AND p.id = m.member_ref AND p.tenant_id = m.tenant_id
             AND p.deleted_at IS NULL
       LEFT JOIN apiome.mcp_endpoints e
              ON m.member_kind = 'mcp_server' AND e.id = m.member_ref AND e.tenant_id = m.tenant_id
             AND e.deleted_at IS NULL
       LEFT JOIN apiome.mcp_v_public_endpoints pe ON pe.id = e.id
       WHERE m.tenant_id = $1 AND m.product_id = $2
         AND (p.id IS NOT NULL OR e.id IS NOT NULL)
       ORDER BY (m.member_kind = 'mcp_server'), lower(COALESCE(p.name, e.name, '')), m.created_at, m.id`;

/** `$1` project ids → each project's public published version labels, newest publish first. */
export const MEMBER_PUBLIC_VERSIONS_SQL = `
       SELECT v.project_id::text AS project_id, v.version_id AS label
       FROM apiome.versions v
       WHERE v.project_id = ANY($1::uuid[])
         AND v.published = true
         AND v.visibility = 'public'
         AND v.deleted_at IS NULL
       ORDER BY v.project_id, v.published_at DESC NULLS LAST, v.created_at DESC`;

/**
 * `$1` tenant id, `$2` product id → the portal plans, by name. Only the public columns are selected:
 * never `billing_ref`, `environments` or `declared_only`.
 */
export const PORTAL_PRODUCT_PLANS_SQL = `
       SELECT pl.slug, pl.name, pl.description, pl.auth_strategy, pl.auth_config, pl.limits,
              pl.concurrency, pl.approval, pl.credential_ttl_days, pl.terms_url, pl.pricing_note,
              pl.state
       FROM apiome.api_plans pl
       WHERE pl.tenant_id = $1 AND pl.product_id = $2
         AND ${PORTAL_PLAN_GATES}
       ORDER BY lower(pl.name), pl.slug`;
