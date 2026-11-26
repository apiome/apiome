import { PactDetailClient } from '@/app/components/ade/pactDetail';

/**
 * `/ade/dashboard/pacts/pacticipants/{consumer}/pacts/{provider}` — one integration's pact, its
 * interactions, verification status, changes since the previous pact and history (PFX-5.2,
 * #6946). `?version=` opens one consumer version's pact; the latest without it. A thin server
 * wrapper that unwraps the handles and the version.
 *
 * @param props - The route params and the query.
 * @returns The page.
 */
export default async function PactPage({
  params,
  searchParams,
}: {
  params: Promise<{ pacticipant: string; provider: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { pacticipant, provider } = await params;
  const query = await searchParams;
  const version = typeof query.version === 'string' && query.version ? query.version : null;
  return <PactDetailClient consumer={pacticipant} provider={provider} initialVersion={version} />;
}
