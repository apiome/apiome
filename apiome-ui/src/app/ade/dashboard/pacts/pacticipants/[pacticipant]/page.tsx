import { PacticipantRouteClient } from '@/app/components/ade/pactPacticipants';

/**
 * `/ade/dashboard/pacts/pacticipants/{handle}` — one pacticipant's versions, branches, tags and
 * environments (PFX-5.1, #6945). A thin server wrapper that unwraps the handle; an id address (a
 * team's owned-entity link, PFX-6.4) is resolved to the handle's.
 *
 * @param props - The route params.
 * @returns The page.
 */
export default async function PacticipantPage({ params }: { params: Promise<{ pacticipant: string }> }) {
  const { pacticipant } = await params;
  return <PacticipantRouteClient reference={pacticipant} />;
}
