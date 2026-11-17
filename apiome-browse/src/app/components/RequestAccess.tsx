/**
 * A plan card's **Request access** action — APX-1.3 (#6100).
 *
 * Requesting access needs a reader session (PCX-1.1, #5889). A reader who is not signed in to this
 * portal gets **Sign in to request access**, which returns to the product page afterwards. A
 * signed-in reader sees **Request access**; the request itself (choose an application, describe the
 * use case) arrives with My apps (APX-2.3, #6105), so until then the button is disabled and says so.
 *
 * Plain markup with no hooks, so a Server Component renders it; the page reads the session once and
 * passes `signedIn` to every card.
 */

import Link from 'next/link';

import { portalPath } from '../../../lib/portal/session';

interface RequestAccessProps {
  /** The portal the product belongs to. */
  tenantSlug: string;
  /** The page to return to after signing in. */
  returnTo: string;
  /** The plan's slug, for element ids. */
  planSlug: string;
  /** The plan's name, for the accessible label. */
  planName: string;
  /** Whether the reader is signed in to this portal. */
  signedIn: boolean;
}

export function RequestAccess({ tenantSlug, returnTo, planSlug, planName, signedIn }: RequestAccessProps) {
  if (!signedIn) {
    return (
      <Link
        className="product-plan-action"
        href={portalPath('/portal/sign-in', { tenant: tenantSlug, return_to: returnTo })}
        aria-label={`Sign in to request access to the ${planName} plan`}
        data-testid="plan-sign-in-to-request"
      >
        Sign in to request access
      </Link>
    );
  }

  const noteId = `plan-${planSlug}-request-note`;
  return (
    <div className="product-plan-request">
      <button
        type="button"
        className="product-plan-action"
        disabled
        aria-describedby={noteId}
        data-testid="plan-request-access"
      >
        Request access
      </button>
      <p id={noteId} className="product-plan-request-note">
        Requests from the portal open soon. Until then, contact the API team.
      </p>
    </div>
  );
}
