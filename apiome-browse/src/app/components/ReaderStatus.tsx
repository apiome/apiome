/**
 * The reader's sign-in state on a portal (tenant) page — PCX-1.1 (#5889).
 *
 * A Server Component: the session cookie is `HttpOnly`, so only the server can read it. Signed in to
 * *this* tenant, it shows the reader's address and a **Sign out** button; otherwise a **Sign in** link
 * that returns here afterwards. A session for another tenant counts as signed out here.
 */

import Link from 'next/link';

import { portalPath } from '../../../lib/portal/session';
import { getReaderSession, withBasePath } from '../portal/readerSession';

interface ReaderStatusProps {
  /** The portal the page belongs to. */
  tenantSlug: string;
  /** The page to return to after signing in. */
  returnTo: string;
}

export async function ReaderStatus({ tenantSlug, returnTo }: ReaderStatusProps) {
  const session = await getReaderSession(tenantSlug);

  if (!session) {
    return (
      <Link
        className="reader-chip"
        href={portalPath('/portal/sign-in', { tenant: tenantSlug, return_to: returnTo })}
        data-testid="reader-sign-in-link"
      >
        <span>Reader access</span>
        <span className="reader-chip-action">Sign in</span>
      </Link>
    );
  }

  return (
    <form method="post" action={withBasePath('/portal/sign-out')} className="reader-chip" data-testid="reader-chip">
      <span>
        Signed in as <strong>{session.reader.email}</strong>
      </span>
      <button type="submit" className="reader-chip-action">
        Sign out
      </button>
    </form>
  );
}
