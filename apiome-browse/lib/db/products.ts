'use server';

/**
 * Portal product reads — APX-1.3 (#6100).
 *
 * Runs the statements in `lib/products/sql.ts` and maps their rows with `lib/products/portalProducts.ts`.
 * Fail-soft like the rest of `lib/db`: a failing statement is logged and reads as "no products" (or
 * "not found"), never a 500 for a visitor.
 */

import { unstable_noStore as noStore } from 'next/cache';
import connectionPool from './db';
import {
  toPortalMember,
  toPortalPlan,
  type MemberRow,
  type PlanRow,
  type PortalProduct,
  type PortalProductSummary,
  type PortalState,
  type PublicVersionRow,
} from '../products/portalProducts';
import { toLifecycleNotices, type LifecycleNotice, type LifecycleRow } from '../products/lifecycle';
import {
  MEMBER_PUBLIC_VERSIONS_SQL,
  PORTAL_PRODUCT_MEMBERS_SQL,
  PORTAL_PRODUCT_PLANS_SQL,
  PORTAL_PRODUCT_SQL,
  PORTAL_PRODUCTS_FOR_TENANT_SQL,
  PRODUCT_LIFECYCLE_FOR_PROJECT_SQL,
} from '../products/sql';

function logError(scope: string, err: unknown) {
  const e = err as { message?: string };
  console.error(`[db] ${scope}:`, e?.message ?? err);
}

/**
 * The portal products of one tenant, for the tenant page.
 *
 * @param tenantSlug - The tenant.
 * @returns Its `portal` products that are published or deprecated, by name; empty on failure.
 */
export async function getPortalProductsForTenant(tenantSlug: string): Promise<PortalProductSummary[]> {
  noStore();
  try {
    const result = await connectionPool.query(PORTAL_PRODUCTS_FOR_TENANT_SQL, [tenantSlug]);
    return result.rows.map((row) => ({
      slug: row.slug,
      name: row.name,
      summary: row.summary ?? null,
      state: row.state as PortalState,
      memberCount: Number(row.member_count) || 0,
      planCount: Number(row.plan_count) || 0,
    }));
  } catch (err) {
    logError('getPortalProductsForTenant', err);
    return [];
  }
}

/**
 * One portal product with its members and plans, for the product page.
 *
 * @param tenantSlug - The tenant.
 * @param productSlug - The product.
 * @returns The product, or null when it is not on the portal (or the read fails).
 */
export async function getPortalProduct(tenantSlug: string, productSlug: string): Promise<PortalProduct | null> {
  noStore();
  try {
    const productResult = await connectionPool.query(PORTAL_PRODUCT_SQL, [tenantSlug, productSlug]);
    const product = productResult.rows[0];
    if (!product) return null;

    const [memberResult, planResult] = await Promise.all([
      connectionPool.query<MemberRow & { ref: string; mcp_public: boolean }>(PORTAL_PRODUCT_MEMBERS_SQL, [
        product.tenant_id,
        product.id,
      ]),
      connectionPool.query<PlanRow>(PORTAL_PRODUCT_PLANS_SQL, [product.tenant_id, product.id]),
    ]);

    const projectIds = [
      ...new Set(memberResult.rows.filter((row) => row.project_slug).map((row) => row.ref)),
    ];
    const versions = new Map<string, PublicVersionRow[]>();
    if (projectIds.length > 0) {
      const versionResult = await connectionPool.query<{ project_id: string; label: string }>(
        MEMBER_PUBLIC_VERSIONS_SQL,
        [projectIds]
      );
      for (const row of versionResult.rows) {
        const list = versions.get(row.project_id) ?? [];
        list.push({ label: row.label });
        versions.set(row.project_id, list);
      }
    }

    return {
      slug: product.slug,
      name: product.name,
      summary: product.summary ?? null,
      state: product.state as PortalState,
      ownerTeam: product.owner_team ?? null,
      tenantSlug: product.tenant_slug,
      tenantName: product.tenant_name,
      updatedAt: product.updated_at ? new Date(product.updated_at).toISOString() : null,
      members: memberResult.rows.map((row) =>
        toPortalMember(product.tenant_slug, row, versions.get(row.ref) ?? [], Boolean(row.mcp_public))
      ),
      plans: planResult.rows.map(toPortalPlan),
    };
  } catch (err) {
    logError('getPortalProduct', err);
    return null;
  }
}

/**
 * The lifecycle news for one API's changelog (APX-1.4, #6101): the portal products that include it
 * and are deprecated or have a deprecated plan.
 *
 * @param tenantSlug - The tenant.
 * @param projectId - The project (the API).
 * @returns One notice per product; empty when there is nothing to say or the read fails.
 */
export async function getProductLifecycleForProject(tenantSlug: string, projectId: string): Promise<LifecycleNotice[]> {
  noStore();
  try {
    const result = await connectionPool.query<LifecycleRow>(PRODUCT_LIFECYCLE_FOR_PROJECT_SQL, [tenantSlug, projectId]);
    return toLifecycleNotices(result.rows);
  } catch (err) {
    logError('getProductLifecycleForProject', err);
    return [];
  }
}
