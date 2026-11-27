import { VerifyRunClient } from '@/app/components/ade/pactVerifyRun';

/**
 * `/ade/dashboard/pacts/verification/new` — **Run a verification** (PFX-8.8, #7305): the provider
 * and the version under test, hosted or self-run, the pacts to verify as sentences, how provider
 * states are set up and whether requests that change data are sent; a preview of what will run
 * before anything is sent. `?provider=` starts with that provider. A thin server wrapper that
 * unwraps the query.
 *
 * @param props - The query.
 * @returns The page.
 */
export default async function RunVerificationPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const provider = typeof query.provider === 'string' && query.provider.trim() ? query.provider.trim().slice(0, 255) : null;
  return <VerifyRunClient initialProvider={provider} />;
}
