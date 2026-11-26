import { DeploySimulatorClient } from '@/app/components/ade/pactEnvironments';
import { searchParamsFrom } from '@lib/pact-matrix';
import { environmentFromSegment } from '@lib/pact-environments';

/**
 * `/ade/dashboard/pacts/environments/{name}/simulate` — the deploy simulator: what deploying one
 * version to the environment would unblock or break, without recording anything (PFX-5.7, #6951).
 * A thin server wrapper that hands the name and the address's query to the client.
 *
 * @param props - The route params and search parameters.
 * @returns The page.
 */
export default async function PactDeploySimulatorPage({
  params,
  searchParams,
}: {
  params: Promise<{ environment: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { environment } = await params;
  const query = searchParamsFrom(await searchParams).toString();
  return <DeploySimulatorClient name={environmentFromSegment(environment)} initialQuery={query} />;
}
