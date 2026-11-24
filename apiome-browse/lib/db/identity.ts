/**
 * Lean identity lookups (DBP-1.27, #7210).
 *
 * Most routes only need to know that an organization or an API is public, and its name. The
 * helpers they used for that computed card facts, operation and schema counts and an SDK probe, or
 * ran `SELECT DISTINCT` over every public version of the organization (32 ms for a 5,000-project
 * organization). These read `apiome.browse_public_projects` (V431) instead: an index probe.
 *
 * Both are wrapped in React's `cache()`, so a page and its `generateMetadata` share one read per
 * request. Both throw `DatabaseUnavailableError` when the database fails — a caller can trust that
 * `null` means "not public or does not exist" and answer 404.
 */

import { cache } from 'react';
import { dbQuery } from './query';

/** An organization with at least one public API. */
export interface PublicTenantIdentity {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  created_at: Date | string;
}

/** A public API (project) and the organization that owns it. */
export interface PublicProjectIdentity {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  tenant_name: string;
  tenant_slug: string;
  /** Its published public versions. */
  version_count: number;
}

/**
 * An organization, when it has at least one public API.
 *
 * @param tenantSlug - The organization's slug.
 * @returns The organization, or null when it does not exist or publishes nothing publicly.
 * @throws DatabaseUnavailableError When the database fails.
 */
export const getPublicTenantIdentity = cache(async (tenantSlug: string): Promise<PublicTenantIdentity | null> => {
  const result = await dbQuery<PublicTenantIdentity>(
    'getPublicTenantIdentity',
    `SELECT t.id, t.name, t.slug, t.description, t.created_at
       FROM apiome.tenants t
      WHERE t.slug = $1
        AND t.deleted_at IS NULL
        AND EXISTS (SELECT 1 FROM apiome.browse_public_projects b WHERE b.tenant_id = t.id)`,
    [tenantSlug]
  );
  return result.rows[0] ?? null;
});

/**
 * A public API, by its organization and project slugs.
 *
 * @param tenantSlug - The organization's slug.
 * @param projectSlug - The project's slug.
 * @returns The project, or null when it does not exist or has no public version.
 * @throws DatabaseUnavailableError When the database fails.
 */
export const getPublicProjectIdentity = cache(
  async (tenantSlug: string, projectSlug: string): Promise<PublicProjectIdentity | null> => {
    const result = await dbQuery<PublicProjectIdentity>(
      'getPublicProjectIdentity',
      `SELECT p.id, p.name, p.slug, p.description,
              t.name AS tenant_name, t.slug AS tenant_slug,
              b.version_count
         FROM apiome.tenants t
         JOIN apiome.projects p ON p.tenant_id = t.id
         JOIN apiome.browse_public_projects b ON b.project_id = p.id
        WHERE t.slug = $1
          AND p.slug = $2
          AND t.deleted_at IS NULL
          AND p.deleted_at IS NULL`,
      [tenantSlug, projectSlug]
    );
    return result.rows[0] ?? null;
  }
);
