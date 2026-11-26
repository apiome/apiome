import { CanIDeployClient } from '@/app/components/ade/pactMatrix';
import { searchParamsFrom } from '@lib/pact-matrix';

/**
 * `/ade/dashboard/pacts/can-i-deploy` — whether one version of a pacticipant can be deployed to an
 * environment (or a tag), with the verdict explained and the CLI command (PFX-5.4, #6948). A thin
 * server wrapper that hands the address's query to the client.
 *
 * @param props - The route's search parameters.
 * @returns The page.
 */
export default async function PactCanIDeployPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = searchParamsFrom(await searchParams).toString();
  return <CanIDeployClient initialQuery={query} />;
}
