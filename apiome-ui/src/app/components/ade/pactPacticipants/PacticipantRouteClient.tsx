'use client';

/**
 * Resolve a pacticipant address to its handle — PFX-6.4 (#6956).
 *
 * Pacticipant pages are addressed by handle, but owner rows (a team's **Owned** list) name the
 * pacticipant by id. An id-shaped address is read first (`GET …/pacticipants/{ref}` accepts a
 * handle, an id or a display name); when it names a pacticipant with a different handle the page
 * replaces the address with the handle's. Any other address — and an id-shaped handle, or a read
 * that fails — renders the page as it is, which shows its own error.
 */

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { LoadingState } from '@/app/components/ui';
import { pacticipantRoute } from '@lib/pact-pacticipants';
import PacticipantDetailClient from './PacticipantDetailClient';
import { fetchPacticipant } from './pacticipantsApi';

/** A pacticipant id: a UUID. */
const PACTICIPANT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Whether an address segment could be a pacticipant id rather than a handle.
 *
 * @param ref - The route segment.
 * @returns True for a UUID.
 */
export function isPacticipantId(ref: string): boolean {
  return PACTICIPANT_ID.test(ref);
}

/**
 * The pacticipant page, after resolving an id address to its handle.
 *
 * @param props - The route segment.
 * @returns The page, or a loading state while an id is resolved.
 */
export default function PacticipantRouteClient({ reference }: { reference: string }) {
  const router = useRouter();
  const [resolved, setResolved] = React.useState(() => !isPacticipantId(reference));

  React.useEffect(() => {
    if (!isPacticipantId(reference)) {
      setResolved(true);
      return;
    }
    let live = true;
    setResolved(false);
    fetchPacticipant(reference)
      .then((pacticipant) => {
        if (!live) return;
        if (pacticipant.slug && pacticipant.slug !== reference) router.replace(pacticipantRoute(pacticipant.slug));
        else setResolved(true);
      })
      .catch(() => {
        if (live) setResolved(true);
      });
    return () => {
      live = false;
    };
  }, [reference, router]);

  if (!resolved) return <LoadingState message="Opening the pacticipant…" minHeightClassName="min-h-[6rem]" />;
  return <PacticipantDetailClient slug={reference} />;
}
