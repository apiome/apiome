'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ShieldAlert, X } from 'lucide-react';
import { useAuthSession } from '@lib/auth/session-client';
import {
  dismissTwoFactorResetNotice,
  getTwoFactorResetNotice,
} from '@lib/auth/two-factor-profile-actions';
import { Button } from '@/app/components/ui/Button';

/** Where two-factor is set up. */
const PROFILE_PATH = '/ade/dashboard/profile';

/**
 * "An administrator reset your two-factor" — the prompt to enrol again (TFA-1.2, #5656).
 *
 * After an administrator resets someone's two-factor they sign in with their first factor only,
 * and nothing on the screen would otherwise tell them a protection they had chosen is gone. This
 * notice does, on every signed-in page, until they set two-factor up again or dismiss it.
 *
 * It floats above the page rather than taking a row of the layout: the signed-in shell is a
 * fixed-height box that each route fills, and a banner pushed into it would shorten every page.
 * `role="status"` — it is news, not an error, and must not interrupt a screen reader.
 *
 * Renders nothing when there is no outstanding reset, which is nearly always.
 *
 * @returns The notice, or `null`.
 */
export function TwoFactorResetNotice() {
  const { data: session } = useAuthSession();
  const signedIn = Boolean(session?.user);
  const enrolled = Boolean(session?.user?.twoFactorEnabled);
  /** Whether the server reported an outstanding reset, and the reader has not dismissed it. */
  const [outstanding, setOutstanding] = useState(false);

  useEffect(() => {
    if (!signedIn || enrolled) return;
    let cancelled = false;
    void getTwoFactorResetNotice()
      .then((notice) => {
        if (!cancelled) setOutstanding(Boolean(notice.resetAt));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [signedIn, enrolled]);

  // Enrolling again is the other way the notice ends: it is derived here rather than stored, so
  // the notice goes the moment the session says two-factor is back on.
  if (!signedIn || enrolled || !outstanding) return null;

  /** Hide the notice now and clear the stamp, so it does not return on the next page. */
  const dismiss = () => {
    setOutstanding(false);
    void dismissTwoFactorResetNotice().catch(() => undefined);
  };

  return (
    <aside className="tfa-reset-notice" role="status" data-testid="two-factor-reset-notice">
      <span className="tfa-reset-notice__icon" aria-hidden="true">
        <ShieldAlert />
      </span>
      <div className="tfa-reset-notice__body">
        <p className="tfa-reset-notice__title">Your two-factor authentication was reset</p>
        <p className="tfa-reset-notice__text">
          An administrator reset it, so you now sign in without a code. Set it up again to protect
          your account.
        </p>
        <div className="tfa-reset-notice__actions">
          <Button asChild size="sm" variant="primary">
            <Link href={PROFILE_PATH} data-testid="two-factor-reset-notice-setup">
              Set up two-factor
            </Link>
          </Button>
          <Button size="sm" variant="ghost" onClick={dismiss} data-testid="two-factor-reset-notice-dismiss">
            Dismiss
          </Button>
        </div>
      </div>
      <button
        type="button"
        className="tfa-reset-notice__close"
        onClick={dismiss}
        aria-label="Dismiss the two-factor reset notice"
      >
        <X aria-hidden="true" />
      </button>
    </aside>
  );
}
