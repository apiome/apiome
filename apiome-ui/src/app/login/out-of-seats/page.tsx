import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import { getAuthSession } from '@lib/auth/server-session';
import OutOfSeatsScreen from '@/app/login/out-of-seats/OutOfSeatsScreen';

export const metadata: Metadata = { title: 'Your workspace is out of seats' };

/** Longest workspace name the page will print. */
const MAX_WORKSPACE_NAME_LENGTH = 120;

/**
 * "Your workspace is out of seats" (EID-1.3, #5013).
 *
 * Where a person lands after signing in through their workspace's identity provider when every
 * licensed member seat is already in use: the sign-in completed, but they were not added to the
 * workspace (`lib/auth/sso-resolution.ts`). The workspace's owners were told at the same moment.
 *
 * Only a signed-in person has anything to read here; anyone else is sent to the sign-in page, so
 * the address cannot be used to show a stranger arbitrary text. `workspace` is untrusted display
 * text: it is trimmed, capped and rendered as text only. It decides nothing — the page grants no
 * access and reads no workspace.
 */
export default async function OutOfSeatsPage({
  searchParams,
}: {
  searchParams: Promise<{ workspace?: string | string[] }>;
}) {
  const params = await searchParams;
  const raw = Array.isArray(params.workspace) ? params.workspace[0] : params.workspace;
  const workspace = (raw ?? '').trim().slice(0, MAX_WORKSPACE_NAME_LENGTH) || null;
  const session = await getAuthSession().catch(() => null);
  if (!session) redirect('/login');
  const email = session.user?.email ?? null;

  return <OutOfSeatsScreen workspace={workspace} email={email} />;
}
