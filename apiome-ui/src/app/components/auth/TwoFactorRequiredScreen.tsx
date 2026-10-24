'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { LogOut, ShieldAlert, ShieldPlus } from 'lucide-react';
import { signOutEverywhere } from '@lib/auth/sign-out-client';
import { requiringWorkspacesPhrase, type TwoFactorRequirementRow } from '@lib/two-factor-policy';
import { BrandMark } from '../brand';
import { TwoFactorEnrollDialog } from '../ade/account/TwoFactorEnrollDialog';
import { useTwoFactorReauth } from '../ade/account/useTwoFactorReauth';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { AuthShell } from './AuthShell';

/** Where the backup step says codes can be regenerated later. */
const REGENERATE_FROM = 'your profile';

/** Props for {@link TwoFactorRequiredScreen}. */
export interface TwoFactorRequiredScreenProps {
  /** The workspaces that require two-factor, earliest deadline first. */
  tenants: readonly TwoFactorRequirementRow[];
  /** The signed-in address, for the top row. */
  email: string | null;
}

/**
 * Format a deadline as a date the reader recognises, e.g. `23 Oct 2026`.
 *
 * @param iso - The deadline.
 * @returns The date, or `''` for an unreadable value.
 */
function formatDeadline(iso: string): string {
  const time = Date.parse(iso);
  if (Number.isNaN(time)) return '';
  return new Date(time).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

/**
 * "Set up two-factor to continue" — the blocking enrolment screen (TFA-1.3, #5657).
 *
 * `TwoFactorRequirementGuard` renders this in place of every `/ade` route once a workspace the
 * reader belongs to requires two-factor and their grace period has ended. It draws the signed-out
 * shell from inside the product, like the first-tenant wizard: a top row naming who is signed in,
 * and one card. The only ways on are **Set up two-factor** — the same enrolment dialog as Profile →
 * Security and onboarding — or **Sign out**.
 *
 * Closing the dialog after enrolling refreshes the route, so the guard reads the account again and
 * lets the reader through.
 *
 * @param props - See {@link TwoFactorRequiredScreenProps}.
 * @returns The screen.
 */
export function TwoFactorRequiredScreen({ tenants, email }: TwoFactorRequiredScreenProps) {
  const router = useRouter();
  const reauth = useTwoFactorReauth();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [enrolled, setEnrolled] = useState(false);

  const workspaces = requiringWorkspacesPhrase(tenants);
  const deadline = tenants[0] ? formatDeadline(tenants[0].dueAt) : '';
  const requires = tenants.length > 1 ? 'require' : 'requires';

  /** Closing the dialog after enrolling lets the guard re-check and open the app. */
  const handleClose = () => {
    setDialogOpen(false);
    if (enrolled) router.refresh();
  };

  return (
    <AuthShell
      wide
      topbar={
        <>
          <BrandMark variant="lockup" size={28} priority />
          <div className="auth-topbar__who">
            {email && (
              <span data-testid="two-factor-required-signed-in-as">
                Signed in as <span className="font-medium text-fg">{email}</span>
              </span>
            )}
            <Button size="sm" variant="ghost" onClick={() => signOutEverywhere('/login')}>
              <LogOut aria-hidden="true" />
              Sign out
            </Button>
          </div>
        </>
      }
    >
      <section aria-labelledby="two-factor-required-title" data-testid="two-factor-required-screen">
        <Card className="wiz-card">
          <div className="wiz-card__body">
            <span className="auth-icon auth-icon--honey" aria-hidden="true">
              <ShieldAlert />
            </span>
            <h1 id="two-factor-required-title" className="auth-title mt-4">
              Set up two-factor to continue
            </h1>
            <p className="auth-sub mt-2" data-testid="two-factor-required-reason">
              {workspaces} {requires} two-factor authentication for every member
              {deadline ? `, and your grace period ended on ${deadline}` : ''}. Set it up with Authy or
              Google Authenticator — it takes about a minute — and you can carry on.
            </p>
          </div>
          <div className="wiz-card__foot">
            <Button variant="ghost" onClick={() => signOutEverywhere('/login')} data-testid="two-factor-required-sign-out">
              <LogOut aria-hidden="true" />
              Sign out
            </Button>
            <Button variant="primary" onClick={() => setDialogOpen(true)} data-testid="two-factor-required-enable">
              <ShieldPlus aria-hidden="true" />
              Set up two-factor
            </Button>
          </div>
        </Card>
      </section>

      <TwoFactorEnrollDialog
        open={dialogOpen}
        onClose={handleClose}
        reauth={reauth}
        onEnrolled={() => setEnrolled(true)}
        regenerateFrom={REGENERATE_FROM}
      />
    </AuthShell>
  );
}

export default TwoFactorRequiredScreen;
