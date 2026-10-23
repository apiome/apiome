'use client';

/**
 * How the signed-in account confirms it is them before a two-factor change (TFA-1.1 #5655),
 * as a hook shared by Profile's `TwoFactorSettings` and the onboarding wizard's
 * **Protect your account** step (TFA-1.4 #5658).
 */

import { useCallback, useEffect, useState } from 'react';
import {
  getTwoFactorReauthStatus,
  type TwoFactorReauthStatus,
} from '@lib/auth/two-factor-profile-actions';

/** What {@link useTwoFactorReauth} returns. */
export interface TwoFactorReauth {
  /**
   * The status of an account that has no password; `null` until the server answers, and for an
   * account with a password — both of which mean "ask for the password".
   */
  reauth: TwoFactorReauthStatus | null;
  /** An account that signs in only through a provider: there is no password to ask for. */
  passwordless: boolean;
  /** Passwordless and signed in too long ago: the change is refused until they sign in again. */
  needsReauth: boolean;
  /** Record that the server refused a change because the sign-in has gone stale. */
  markStale: () => void;
}

/**
 * Load the account's re-authentication status once on mount.
 *
 * A failed lookup leaves `reauth` at `null`, so the dialogs fall back to asking for a password —
 * the server refuses the change anyway if that is wrong.
 *
 * @returns See {@link TwoFactorReauth}.
 */
export function useTwoFactorReauth(): TwoFactorReauth {
  const [reauth, setReauth] = useState<TwoFactorReauthStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getTwoFactorReauthStatus()
      .then((status) => {
        if (!cancelled) setReauth(status.hasPassword ? null : status);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const markStale = useCallback(() => {
    setReauth((current) => (current ? { ...current, fresh: false } : current));
  }, []);

  const passwordless = reauth !== null && !reauth.hasPassword;
  return { reauth, passwordless, needsReauth: passwordless && !reauth.fresh, markStale };
}
