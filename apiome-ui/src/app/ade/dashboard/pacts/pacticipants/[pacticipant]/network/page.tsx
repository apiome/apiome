import { PactNetworkClient } from '@/app/components/ade/pactNetwork';

/**
 * `/ade/dashboard/pacts/pacticipants/{handle}/network` — the pacticipants connected to one through
 * pacts, drawn with each integration's verdict (PFX-5.3, #6947). A thin server wrapper that
 * unwraps the handle.
 *
 * @param props - The route params.
 * @returns The page.
 */
export default async function PactNetworkPage({
  params,
}: {
  params: Promise<{ pacticipant: string }>;
}) {
  const { pacticipant } = await params;
  return <PactNetworkClient slug={pacticipant} />;
}
