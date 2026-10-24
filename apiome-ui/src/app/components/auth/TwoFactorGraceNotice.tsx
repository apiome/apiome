'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ShieldAlert, X } from 'lucide-react';
import { useAuthSession } from '@lib/auth/session-client';
import { getMyTwoFactorRequirement } from '@lib/auth/two-factor-requirement-actions';
import {
  daysUntil,
  requiringWorkspacesPhrase,
  type TwoFactorRequirement,
} from '@lib/two-factor-policy';
import { Button } from '@/app/components/ui/Button';

/** Where two-factor is set up. */
const PROFILE_PATH = '/ade/dashboard/profile';

/**
 * The `sessionStorage` key that hides the notice for the rest of this browser session. Per
 * session, not forever: the reminder is the point, so it comes back on the next sign-in.
 */
export const GRACE_NOTICE_DISMISSED_KEY = 'apiome:2fa-grace-dismissed';

/**
 * Whether the reader dismissed the notice earlier in this browser session.
 *
 * @returns True when dismissed; false when not, or when storage is unavailable.
 */
function readDismissed(): boolean {
  try {
    return typeof window !== 'undefined' && window.sessionStorage.getItem(GRACE_NOTICE_DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * How long is left, in words.
 *
 * @param dueAt - The deadline (ISO-8601).
 * @returns `today`, `in 1 day` or `in N days`.
 */
export function graceRemainingPhrase(dueAt: string, now: Date = new Date()): string {
  const days = daysUntil(dueAt, now) ?? 0;
  if (days <= 0) return 'today';
  return `in ${days} ${days === 1 ? 'day' : 'days'}`;
}

/**
 * "Your workspace requires two-factor" — the grace-period reminder (TFA-1.3, #5657).
 *
 * Shown on every signed-in page while a workspace requires two-factor of the reader and their
 * deadline has not passed (after it, `TwoFactorRequirementGuard` blocks the app instead). It floats
 * in the notice stack over the bottom corner, beside the reset notice, rather than shortening every
 * page. **Dismiss** hides it until the next browser session; enrolling hides it for good.
 *
 * @returns The notice, or `null`.
 */
export function TwoFactorGraceNotice() {
  const { data: session } = useAuthSession();
  const signedIn = Boolean(session?.user);
  const enrolled = Boolean(session?.user?.twoFactorEnabled);
  const [requirement, setRequirement] = useState<TwoFactorRequirement | null>(null);
  // Read once on mount. Nothing renders until the requirement arrives, so the server render
  // (where there is no storage) and the first client render agree either way.
  const [dismissed, setDismissed] = useState(readDismissed);

  useEffect(() => {
    if (!signedIn || enrolled) return;
    let cancelled = false;
    void getMyTwoFactorRequirement()
      .then((next) => {
        if (!cancelled) setRequirement(next);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [signedIn, enrolled]);

  if (!signedIn || enrolled || dismissed || !requirement?.dueAt || requirement.overdue) return null;

  /** Hide the notice for the rest of this browser session. */
  const dismiss = () => {
    setDismissed(true);
    try {
      window.sessionStorage.setItem(GRACE_NOTICE_DISMISSED_KEY, '1');
    } catch {
      // Storage blocked: hidden for this page view only.
    }
  };

  const workspaces = requiringWorkspacesPhrase(requirement.tenants);
  const requires = requirement.tenants.length > 1 ? 'require' : 'requires';

  return (
    <aside className="tfa-reset-notice" role="status" data-testid="two-factor-grace-notice">
      <span className="tfa-reset-notice__icon" aria-hidden="true">
        <ShieldAlert />
      </span>
      <div className="tfa-reset-notice__body">
        <p className="tfa-reset-notice__title">
          Set up two-factor {graceRemainingPhrase(requirement.dueAt)}
        </p>
        <p className="tfa-reset-notice__text">
          {workspaces} {requires} two-factor authentication. After your grace period you&apos;ll need
          to set it up before you can use the app.
        </p>
        <div className="tfa-reset-notice__actions">
          <Button asChild size="sm" variant="primary">
            <Link href={PROFILE_PATH} data-testid="two-factor-grace-notice-setup">
              Set up two-factor
            </Link>
          </Button>
          <Button size="sm" variant="ghost" onClick={dismiss} data-testid="two-factor-grace-notice-dismiss">
            Dismiss
          </Button>
        </div>
      </div>
      <button
        type="button"
        className="tfa-reset-notice__close"
        onClick={dismiss}
        aria-label="Dismiss the two-factor reminder"
      >
        <X aria-hidden="true" />
      </button>
    </aside>
  );
}
