'use client';

/**
 * The "confirm it's you" notice for an account without a password (TFA-1.1 #5655), shared by
 * every two-factor dialog that would otherwise ask for one (moved out of `TwoFactorSettings` by
 * TFA-1.4 #5658, so the onboarding wizard's enrolment draws the same notice).
 */

import { KeyRound } from 'lucide-react';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { REAUTH_WINDOW_MINUTES } from '@lib/auth/two-factor-policy';
import type { TwoFactorReauthStatus } from '@lib/auth/two-factor-profile-actions';

/** Props for {@link TwoFactorReauthNotice}. */
export interface TwoFactorReauthNoticeProps {
  /** How this passwordless account confirms it is them. */
  reauth: TwoFactorReauthStatus;
  /** True while a change is in flight — the sign-in buttons wait for it. */
  busy: boolean;
  /** Sign in again with the provider the reader chose. */
  onReauth: (providerId: string) => void;
}

/**
 * Recently signed in: one line saying why nothing is asked. Otherwise: why the change is on
 * hold, and a button per linked provider to sign in again.
 *
 * @param props See {@link TwoFactorReauthNoticeProps}.
 * @returns The notice.
 */
export function TwoFactorReauthNotice({
  reauth,
  busy,
  onReauth,
}: TwoFactorReauthNoticeProps) {
  if (!reauth.fresh) {
    return (
      <div className="acct-field" data-testid="two-factor-reauth-required">
        <Alert variant="warn">
          This account has no password, so confirm it is you by signing in again. You can change
          two-factor settings for {REAUTH_WINDOW_MINUTES} minutes after you sign in.
        </Alert>
        {reauth.providers.length > 0 ? (
          reauth.providers.map((provider) => (
            <Button
              key={provider.id}
              variant="outline"
              onClick={() => onReauth(provider.id)}
              disabled={busy}
              data-testid={`two-factor-reauth-${provider.id}`}
            >
              <KeyRound aria-hidden />
              Sign in again with {provider.label}
            </Button>
          ))
        ) : (
          <p className="acct-hint">Sign out, then sign in again and come back to this page.</p>
        )}
      </div>
    );
  }
  return (
    <p className="acct-hint" data-testid="two-factor-reauth-fresh">
      This account has no password. You signed in a moment ago, so nothing more is needed to
      confirm it is you.
    </p>
  );
}

export default TwoFactorReauthNotice;
