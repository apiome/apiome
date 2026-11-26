import { MatrixClient } from '@/app/components/ade/pactMatrix';
import { searchParamsFrom } from '@lib/pact-matrix';

/**
 * `/ade/dashboard/pacts/matrix` — the Pact Broker matrix with a query builder, its grid and the
 * verdict explained (PFX-5.4, #6948). A thin server wrapper that hands the address's query to the
 * client, which reads it (and says why when it cannot).
 *
 * @param props - The route's search parameters.
 * @returns The page.
 */
export default async function PactMatrixPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = searchParamsFrom(await searchParams).toString();
  return <MatrixClient initialQuery={query} />;
}
