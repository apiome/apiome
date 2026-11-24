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

/** Most versions of one project a `project_version` member's selector is matched against. */
export const MEMBER_VERSION_SCAN_LIMIT = 200;

/**
 * `$1` project ids, `$2` how many versions each needs (same order) → each project's newest public
 * published version labels, newest publish first.
 *
 * Bounded per project (DBP-1.27, #7210): a `project_latest` member needs one label and a
 * `project_version` member the newest {@link MEMBER_VERSION_SCAN_LIMIT} to match its selector
 * against, where the statement used to return every public version of every member project.
 */
export const MEMBER_PUBLIC_VERSIONS_SQL = `
       SELECT m.project_id::text AS project_id, v.label
       FROM unnest($1::uuid[], $2::int[]) AS m(project_id, wanted)
       CROSS JOIN LATERAL (
         SELECT mv.version_id AS label, mv.published_at, mv.created_at
         FROM apiome.versions mv
         WHERE mv.project_id = m.project_id
           AND mv.published = true
           AND mv.visibility = 'public'
           AND mv.deleted_at IS NULL
         ORDER BY mv.published_at DESC NULLS LAST, mv.created_at DESC
         LIMIT m.wanted
       ) v
       ORDER BY m.project_id, v.published_at DESC NULLS LAST, v.created_at DESC`;

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

/**
 * APX-1.4 (#6101). `$1` tenant slug, `$2` project id → the lifecycle news for that API's changelog:
 * one row per portal product that includes the project (a non-MCP member) and is deprecated or has
 * a deprecated portal plan — with that plan's columns when there is one (`plan_slug` null
 * otherwise). A successor is named only when it is itself a portal plan. Only public columns.
 */
export const PRODUCT_LIFECYCLE_FOR_PROJECT_SQL = `
       SELECT ap.slug, ap.name, ap.state, ap.retire_at, ap.deprecation_message,
              pl.slug AS plan_slug, pl.name AS plan_name, pl.retire_at AS plan_retire_at,
              pl.deprecation_message AS plan_deprecation_message, s.name AS successor_name
       FROM apiome.api_products ap
       JOIN apiome.tenants t ON t.id = ap.tenant_id
       LEFT JOIN apiome.api_plans pl
              ON pl.product_id = ap.id AND pl.tenant_id = ap.tenant_id
             AND pl.state = 'deprecated' AND pl.deleted_at IS NULL
       LEFT JOIN apiome.api_plans s
              ON s.id = pl.successor_plan_id AND s.tenant_id = ap.tenant_id
             AND s.state IN ${PLAN_STATES} AND s.deleted_at IS NULL
       WHERE t.slug = $1
         AND ${PORTAL_PRODUCT_GATES}
         AND EXISTS (SELECT 1 FROM apiome.api_product_members m
                     WHERE m.product_id = ap.id AND m.tenant_id = ap.tenant_id
                       AND m.member_kind <> 'mcp_server' AND m.member_ref = $2::uuid)
         AND (ap.state = 'deprecated' OR pl.id IS NOT NULL)
       ORDER BY lower(ap.name), ap.slug, pl.retire_at NULLS LAST, lower(pl.name)`;
