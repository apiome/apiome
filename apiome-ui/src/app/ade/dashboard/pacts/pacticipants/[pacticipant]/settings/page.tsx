import { PacticipantSettingsClient } from '@/app/components/ade/pactPacticipants';

/**
 * `/ade/dashboard/pacts/pacticipants/{handle}/settings` — a pacticipant's name, display name, main
 * branch, repository, owner, linked project and labels, and its delete (PFX-8.10, #7307). A thin
 * server wrapper that unwraps the handle; reads and writes go through `/api/pact/pacticipants/*`.
 *
 * @param props - The route params.
 * @returns The page.
 */
export default async function PacticipantSettingsPage({
  params,
}: {
  params: Promise<{ pacticipant: string }>;
}) {
  const { pacticipant } = await params;
  return <PacticipantSettingsClient slug={pacticipant} />;
}
