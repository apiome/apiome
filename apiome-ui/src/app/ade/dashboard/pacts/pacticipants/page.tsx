import { PacticipantsListClient } from '@/app/components/ade/pactPacticipants';

/**
 * `/ade/dashboard/pacts/pacticipants` — the workspace's pacticipants (PFX-5.1, #6945).
 *
 * @returns The page.
 */
export default function PacticipantsPage() {
  return <PacticipantsListClient />;
}
