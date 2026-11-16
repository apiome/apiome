import {
  getPublicTenants,
  getRecentlyPublishedVersions,
  getMostVersionedProjects,
  getNewestTenants,
} from '../../lib/db/helper';
import { PROJECT_RAIL_SORT_PARAM, parseProjectRailSort } from '../../lib/cardFacts';
import { HomeClient } from './HomeClient';

export const dynamic = 'force-dynamic';

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  // BDX-2.2: `?projects=operations|grade` re-orders the project rail on the server.
  const railSort = parseProjectRailSort((await searchParams)[PROJECT_RAIL_SORT_PARAM]);
  const [tenants, recentVersions, popularProjects, newestTenants] = await Promise.all([
    getPublicTenants(),
    getRecentlyPublishedVersions(8),
    getMostVersionedProjects(8, railSort),
    getNewestTenants(8),
  ]);

  return (
    <HomeClient
      tenants={tenants}
      recentVersions={recentVersions}
      popularProjects={popularProjects}
      newestTenants={newestTenants}
      railSort={railSort}
    />
  );
}
