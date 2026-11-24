/**
 * The Try It relay's policy lookup (SIM-3.2, #4448), in one cached statement (DBP-1.27, #7210).
 *
 * `POST /api/try-it` runs on every relayed request. It needs three facts about the version the
 * browser names: that it is public, whether its mock is on, and which servers its spec declares.
 * It used to get them from the version page's helper — card facts, operation and schema counts
 * and an SDK probe — plus a second statement for the servers. This is one statement that reads
 * exactly those facts, and its answer is remembered for {@link TRY_IT_POLICY_TTL_MS}: a visitor
 * sending a series of requests from one page reads the database once.
 *
 * The cache is per Browse process. Its cost is a delay: after a version is unpublished, its mock
 * switched off or its servers changed, the relay can apply the previous policy for up to the
 * interval. A failed lookup is never cached, and an expired answer is never used in its place.
 */

import { LIVE_OWNER_GATES, PUBLIC_VERSION_ROW_GATES } from './gates';
import { dbQuery } from './query';
import { TtlCache } from './ttlCache';

/** How long a version's relay policy inputs are remembered, in milliseconds. */
export const TRY_IT_POLICY_TTL_MS = 30_000;

/** What the relay's allow-policy is built from. */
export interface TryItVersion {
  /** The version's label, as stored. */
  version_id: string;
  /** Whether the version's public mock is on. */
  mock_enabled: boolean;
  /** The spec's declared `servers[]` rows, in declared order. */
  servers: { url: string; variables: unknown }[];
}

/** Recent lookups, keyed by the slug chain. Unknown versions are remembered too (as null). */
const tryItCache = new TtlCache(512);

/**
 * The relay policy inputs of one published public version.
 *
 * @param tenantSlug - The organization's slug.
 * @param projectSlug - The project's slug.
 * @param versionSlug - The version's label.
 * @returns The inputs, or null when the version is not public or does not exist (the relay then
 *   refuses).
 * @throws DatabaseUnavailableError When the database fails and no fresh answer is remembered.
 */
export function getTryItVersion(
  tenantSlug: string,
  projectSlug: string,
  versionSlug: string
): Promise<TryItVersion | null> {
  return tryItCache.read<TryItVersion | null>(
    JSON.stringify([tenantSlug, projectSlug, versionSlug]),
    async () => {
      const result = await dbQuery<TryItVersion>(
        'getTryItVersion',
        `SELECT v.version_id,
                COALESCE(v.mock_enabled, false) AS mock_enabled,
                COALESCE((SELECT json_agg(json_build_object('url', vs.url, 'variables', vs.variables)
                                          ORDER BY vs.sort_order, vs.url)
                            FROM apiome.version_server vs
                           WHERE vs.version_id = v.id), '[]'::json) AS servers
           FROM apiome.versions v
           JOIN apiome.projects p ON v.project_id = p.id
           JOIN apiome.tenants t ON p.tenant_id = t.id
          WHERE t.slug = $1
            AND p.slug = $2
            AND v.version_id = $3
            AND ${PUBLIC_VERSION_ROW_GATES}
            AND ${LIVE_OWNER_GATES}`,
        [tenantSlug, projectSlug, versionSlug]
      );
      return result.rows[0] ?? null;
    },
    // An expired policy is never applied: when the refresh fails, the relay answers 503.
    { ttlMs: TRY_IT_POLICY_TTL_MS, staleOnError: false }
  );
}

/** Forget every remembered lookup. For tests. */
export function clearTryItCache(): void {
  tryItCache.clear();
}
