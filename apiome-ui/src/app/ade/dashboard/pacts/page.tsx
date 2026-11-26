import { redirect } from 'next/navigation';
import { PACTICIPANTS_ROUTE } from '@lib/pact-pacticipants';

/**
 * `/ade/dashboard/pacts` — the **Contracts** rail entry (PFX-5.1, #6945). The area opens on its
 * Pacticipants list.
 */
export default function PactsIndexPage(): never {
  redirect(PACTICIPANTS_ROUTE);
}
