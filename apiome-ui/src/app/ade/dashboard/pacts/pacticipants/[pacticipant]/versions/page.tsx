import { PacticipantVersionsClient } from '@/app/components/ade/pactPacticipants';

/**
 * `/ade/dashboard/pacts/pacticipants/{handle}/versions` — a pacticipant's versions as a managed
 * list: search, views, tag, delete, restore and bulk actions (PFX-8.11, #7308). A thin server
 * wrapper that unwraps the handle; reads and writes go through `/api/pact/pacticipants/*`.
 *
 * @param props - The route params.
 * @returns The page.
 */
export default async function PacticipantVersionsPage({
  params,
}: {
  params: Promise<{ pacticipant: string }>;
}) {
  const { pacticipant } = await params;
  return <PacticipantVersionsClient slug={pacticipant} />;
}
