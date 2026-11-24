/**
 * What each Browse route reads from the database, as one function per route (DBP-1.27, #7210).
 *
 * A page or route handler calls its loader and renders the result; it runs no other statement.
 * That makes a route's database cost a property of one function, which
 * `lib/__tests__/routeBudget.test.ts` runs against a recording pool and holds to the number in
 * `lib/db/statementBudgets.json` — and checks that no statement runs twice within a render.
 *
 * Loaders are wrapped in React's `cache()` where a page and its `generateMetadata` both need them,
 * so the two share one read per request.
 *
 * Every loader returns `null` when the thing is not public or does not exist (→ 404) and throws
 * `DatabaseUnavailableError` when the database fails (→ 5xx; see `lib/db/errors.ts`).
 */

import { cache } from 'react';
import type { PublicVersionChangelogRow } from '../changelog/types';
import type { LifecycleNotice } from '../products/lifecycle';
import type { PortalProduct, PortalProductSummary } from '../products/portalProducts';
import type { McpPublicCollection, McpPublicEndpointDetail } from '../types';
import {
  getChangelogPage,
  getChangelogPair,
  type ChangelogPage,
  type ChangelogPageRequest,
} from './changelogs';
import { getPublicMcpCollection, getPublicMcpEndpointDetail, getPublicProjectsForTenant } from './helper';
import {
  getPublicProjectIdentity,
  getPublicTenantIdentity,
  type PublicProjectIdentity,
  type PublicTenantIdentity,
} from './identity';
import { getPortalProduct, getPortalProductsForTenant, getProductLifecycleForProject } from './products';
import {
  getPublicProjectWithFacts,
  getPublicVersionPage,
  listProjectVersions,
  listVersionLabels,
  type ProjectVersionRow,
  type PublicProjectRow,
  type PublicVersionPage,
  type VersionLabelRow,
} from './versions';

/** `/tenant/{tenant}` — the organization, its public projects and its portal products. */
export async function loadTenantPage(tenantSlug: string): Promise<{
  tenant: PublicTenantIdentity;
  // The card rows are handed to the client component as they arrive.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  projects: any[];
  products: PortalProductSummary[];
} | null> {
  const [tenant, projects, products] = await Promise.all([
    getPublicTenantIdentity(tenantSlug),
    getPublicProjectsForTenant(tenantSlug),
    getPortalProductsForTenant(tenantSlug),
  ]);
  return tenant ? { tenant, projects, products } : null;
}

/** `/tenant/{tenant}/{project}` — the project with its facts, and its newest versions. */
export async function loadProjectPage(
  tenantSlug: string,
  projectSlug: string
): Promise<{ project: PublicProjectRow; versions: ProjectVersionRow[] } | null> {
  const project = await getPublicProjectWithFacts(tenantSlug, projectSlug);
  if (!project) return null;
  return { project, versions: await listProjectVersions(project.id) };
}

/**
 * `/tenant/{tenant}/{project}/{version}` — one statement. The changelog's entries are read with it
 * only when the page opens on the Changes tab.
 */
export function loadVersionPage(
  tenantSlug: string,
  projectSlug: string,
  versionSlug: string,
  onChangesTab: boolean
): Promise<PublicVersionPage | null> {
  return getPublicVersionPage(tenantSlug, projectSlug, versionSlug, onChangesTab);
}

/** `/tenant/{tenant}/{project}/changelog` — the project, one page of its changelog, lifecycle news. */
export async function loadChangelogPage(
  tenantSlug: string,
  projectSlug: string,
  request: ChangelogPageRequest
): Promise<{ project: PublicProjectIdentity; page: ChangelogPage; lifecycle: LifecycleNotice[] } | null> {
  const project = await getPublicProjectIdentity(tenantSlug, projectSlug);
  if (!project) return null;
  const [page, lifecycle] = await Promise.all([
    getChangelogPage(project.id, request),
    getProductLifecycleForProject(tenantSlug, String(project.id)),
  ]);
  return { project, page, lifecycle };
}

/**
 * `/tenant/{tenant}/{project}/compare` — the project, its version labels, and the stored changelog
 * of the pair being compared (the page's defaults when the URL names none: the two newest).
 */
export async function loadComparePage(
  tenantSlug: string,
  projectSlug: string,
  v1?: string,
  v2?: string
): Promise<{
  project: PublicProjectIdentity;
  versions: VersionLabelRow[];
  changelogs: PublicVersionChangelogRow[];
} | null> {
  const project = await getPublicProjectIdentity(tenantSlug, projectSlug);
  if (!project) return null;
  const versions = await listVersionLabels(project.id);
  const base = v1 || versions[1]?.version_id;
  const head = v2 || versions[0]?.version_id;
  const pair = base && head && base !== head ? await getChangelogPair(project.id, base, head) : null;
  return { project, versions, changelogs: pair ? [pair] : [] };
}

/** `/tenant/{tenant}/products/{product}` — shared by the page and its metadata. */
export const loadProductPage: (tenantSlug: string, productSlug: string) => Promise<PortalProduct | null> =
  cache(getPortalProduct);

/** `/mcp/{tenant}/{endpoint}` — the endpoint and its capability items. */
export const loadMcpEndpointPage: (
  tenantSlug: string,
  endpointSlug: string
) => Promise<McpPublicEndpointDetail | null> = cache(getPublicMcpEndpointDetail);

/** `/mcp/{tenant}/collections/{collection}` — shared by the page and its metadata. */
export const loadMcpCollectionPage: (
  tenantSlug: string,
  collectionSlug: string
) => Promise<McpPublicCollection | null> = cache(getPublicMcpCollection);
