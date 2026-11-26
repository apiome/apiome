import { PactVerificationClient } from '@/app/components/ade/pactVerification';

/**
 * `/ade/dashboard/pacts/pacticipants/{provider}/verification` — where a provider's verification
 * stands: each consumer's newest pact (stale or not) with **Re-run** and **Verify all stale**, and
 * every result newest first (PFX-5.5, #6949). `?consumer=` narrows the history. A thin server
 * wrapper that unwraps the handle and the query.
 *
 * @param props - The route params and the query.
 * @returns The page.
 */
export default async function PactVerificationPage({
  params,
  searchParams,
}: {
  params: Promise<{ pacticipant: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { pacticipant } = await params;
  const query = await searchParams;
  const consumer = typeof query.consumer === 'string' && query.consumer ? query.consumer : null;
  return <PactVerificationClient slug={pacticipant} consumer={consumer} />;
}
