import { PactOverviewClient } from '@/app/components/ade/pactOverview';
import { readOverviewQuery } from '@lib/pact-overview';

/**
 * `/ade/dashboard/pacts` — the **Contracts** landing (PFX-8.1, #7298): the area's tab row, what
 * needs attention, and every integration. `?q=`, `?filter=` (`failing`, `stale`, `bidirectional`,
 * `mine`), `?page=` and `?view=network` are kept in the address; anything there that cannot be
 * used is reported on the page. A thin server wrapper that unwraps the query.
 *
 * @param props - The query.
 * @returns The page.
 */
export default async function PactsOverviewPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return <PactOverviewClient query={readOverviewQuery(await searchParams)} />;
}
