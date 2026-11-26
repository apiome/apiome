import { RepublishRequestClient } from '@/app/components/ade/pactRemediation';

/**
 * `/ade/dashboard/pacts/republish-requests/{id}` — one re-publish request: the stale pact, its
 * state and timeline, who was notified, and **Acknowledge** while it is open (PFX-6.2, #6954). A
 * thin server wrapper that unwraps the id.
 *
 * @param props - The route params.
 * @returns The page.
 */
export default async function RepublishRequestPage({ params }: { params: Promise<{ requestId: string }> }) {
  const { requestId } = await params;
  return <RepublishRequestClient id={requestId} />;
}
