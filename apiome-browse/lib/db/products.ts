'use server';

/**
 * Portal product reads — APX-1.3 (#6100).
 *
 * Runs the statements in `lib/products/sql.ts` and maps their rows with `lib/products/portalProducts.ts`.
 *
 * Failure handling (DBP-1.27, #7210; `lib/db/errors.ts`): the two lists that decorate another page —
 * an organization's products, an API's lifecycle news — log a failing statement and read as empty.
 * {@link getPortalProduct} is the product page itself: it throws `DatabaseUnavailableError`, so a
 * database failure is an error page and never "product not found".
 */

import { unstable_noStore as noStore } from 'next/cache';
import { dbQuery } from './query';
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
  MEMBER_VERSION_SCAN_LIMIT,
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
    const result = await dbQuery('getPortalProductsForTenant', PORTAL_PRODUCTS_FOR_TENANT_SQL, [tenantSlug]);
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
 * @returns The product, or null when it is not on the portal.
 * @throws DatabaseUnavailableError When the database fails.
 */
export async function getPortalProduct(tenantSlug: string, productSlug: string): Promise<PortalProduct | null> {
  noStore();
  const productResult = await dbQuery('getPortalProduct', PORTAL_PRODUCT_SQL, [tenantSlug, productSlug]);
  const product = productResult.rows[0];
  if (!product) return null;

  const [memberResult, planResult] = await Promise.all([
    dbQuery<MemberRow & { ref: string; mcp_public: boolean }>('getPortalProduct.members', PORTAL_PRODUCT_MEMBERS_SQL, [
      product.tenant_id,
      product.id,
    ]),
    dbQuery<PlanRow>('getPortalProduct.plans', PORTAL_PRODUCT_PLANS_SQL, [product.tenant_id, product.id]),
  ]);

  // How many version labels each member project needs: its latest for a `project_latest` member,
  // enough to match a selector against for a `project_version` member.
  const wanted = new Map<string, number>();
  for (const row of memberResult.rows) {
    if (!row.project_slug) continue;
    const need = row.kind === 'project_version' ? MEMBER_VERSION_SCAN_LIMIT : 1;
    wanted.set(row.ref, Math.max(wanted.get(row.ref) ?? 0, need));
  }
  const versions = new Map<string, PublicVersionRow[]>();
  if (wanted.size > 0) {
    const versionResult = await dbQuery<{ project_id: string; label: string }>(
      'getPortalProduct.versions',
      MEMBER_PUBLIC_VERSIONS_SQL,
      [[...wanted.keys()], [...wanted.values()]]
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
    const result = await dbQuery<LifecycleRow>('getProductLifecycleForProject', PRODUCT_LIFECYCLE_FOR_PROJECT_SQL, [
      tenantSlug,
      projectId,
    ]);
    return toLifecycleNotices(result.rows);
  } catch (err) {
    logError('getProductLifecycleForProject', err);
    return [];
  }
}
