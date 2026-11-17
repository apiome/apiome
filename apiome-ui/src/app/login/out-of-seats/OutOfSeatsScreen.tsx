'use client';

import { LogOut, UserRoundX } from 'lucide-react';

import { signOutEverywhere } from '@lib/auth/sign-out-client';
import { AuthShell } from '@/app/components/auth/AuthShell';
import { BrandMark } from '@/app/components/brand';
import { Button } from '@/app/components/ui/Button';
import { Card } from '@/app/components/ui/Card';

/** Props for {@link OutOfSeatsScreen}. */
export interface OutOfSeatsScreenProps {
  /** The workspace's display name, when the sign-in named it. */
  workspace: string | null;
  /** The signed-in address, for the top row. */
  email: string | null;
}

/**
 * "Your workspace is out of seats" — shown after a single sign-on that could not add the person to
 * their workspace because every licensed member seat is in use (EID-1.3, #5013).
 *
 * It says what happened, that the owners already know, and what will fix it; the one action is
 * **Sign out**, because nothing the reader can do here frees a seat. Signing in again once an
 * owner has made room adds them.
 *
 * @param props - See {@link OutOfSeatsScreenProps}.
 * @returns The screen.
 */
export default function OutOfSeatsScreen({ workspace, email }: OutOfSeatsScreenProps) {
  const name = workspace ?? 'Your workspace';

  return (
    <AuthShell
      wide
      topbar={
        <>
          <BrandMark variant="lockup" size={28} priority />
          <div className="auth-topbar__who">
            {email && (
              <span data-testid="out-of-seats-signed-in-as">
                Signed in as <span className="font-medium text-fg">{email}</span>
              </span>
            )}
          </div>
        </>
      }
    >
      <section aria-labelledby="out-of-seats-title" data-testid="out-of-seats-screen">
        <Card className="wiz-card">
          <div className="wiz-card__body">
            <span className="auth-icon auth-icon--honey" aria-hidden="true">
              <UserRoundX />
            </span>
            <h1 id="out-of-seats-title" className="auth-title mt-4">
              Your workspace is out of seats
            </h1>
            <p className="auth-sub mt-2" data-testid="out-of-seats-reason">
              You signed in, but <span className="font-medium text-fg">{name}</span> has no member seat
              left, so you were not added to it.
            </p>
            <p className="auth-sub mt-2">
              The workspace’s owners have been notified. Once one of them frees a seat or upgrades the
              plan, sign in again and you will be added automatically.
            </p>
          </div>
          <div className="wiz-card__foot">
            <Button variant="primary" onClick={() => signOutEverywhere('/login')} data-testid="out-of-seats-sign-out">
              <LogOut aria-hidden="true" />
              Sign out
            </Button>
          </div>
        </Card>
      </section>
    </AuthShell>
  );
}
