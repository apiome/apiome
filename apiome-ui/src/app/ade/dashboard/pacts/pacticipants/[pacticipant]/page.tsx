import { PacticipantDetailClient } from '@/app/components/ade/pactPacticipants';

/**
 * `/ade/dashboard/pacts/pacticipants/{handle}` — one pacticipant's versions, branches, tags and
 * environments (PFX-5.1, #6945). A thin server wrapper that unwraps the handle.
 *
 * @param props - The route params.
 * @returns The page.
 */
export default async function PacticipantPage({ params }: { params: Promise<{ pacticipant: string }> }) {
  const { pacticipant } = await params;
  return <PacticipantDetailClient slug={pacticipant} />;
}
