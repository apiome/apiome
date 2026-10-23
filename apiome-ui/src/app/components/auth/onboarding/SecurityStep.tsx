'use client';

import { useState } from 'react';
import { ArrowRight, Check, ShieldCheck, ShieldPlus } from 'lucide-react';
import { useAuthSession } from '@lib/auth/session-client';
import { TwoFactorEnrollDialog } from '../../ade/account/TwoFactorEnrollDialog';
import { useTwoFactorReauth } from '../../ade/account/useTwoFactorReauth';
import { Alert } from '../../ui/Alert';
import { Button } from '../../ui/Button';

/** What enrolment asks of the reader, in order — the same three steps the dialog's stepper shows. */
const ENROLMENT_OUTLINE = [
  'Scan a QR code with Authy or Google Authenticator.',
  'Enter the 6-digit code the app shows.',
  'Save your backup codes somewhere safe.',
] as const;

/** Where the backup-step description says codes can be regenerated, from inside the wizard. */
const REGENERATE_FROM = 'your profile';

/** Inputs and callbacks of the security step. */
export interface SecurityStepProps {
  /** Name of the tenant that was just created — the step confirms it before asking. */
  tenantName: string;
  /** Leave the step: after enrolling, or by skipping. Moves the wizard to its last screen. */
  onFinish: () => void;
}

/**
 * Last step of the first-tenant onboarding wizard (TFA-1.4, #5658): **Protect your account**.
 *
 * The organization already exists when this step shows — it follows the review step's
 * **Create organization** — so it opens by confirming that, then offers authenticator-app
 * two-factor. **Set up two-factor** opens the very enrolment dialog Profile → Security uses
 * (`TwoFactorEnrollDialog`): confirm it's you, scan the QR, save the backup codes. Closing that
 * dialog after the codes are saved finishes the step; closing it before leaves the reader here.
 *
 * **Skip for now** finishes the step with two-factor off. Nothing is lost: Profile → Security
 * keeps the **Enable 2FA** button and shows a dismissible reminder while it is off.
 *
 * The step is never resumed: once the tenant exists the onboarding guard stops drawing the
 * wizard, so a reload here lands in the dashboard — the same place a skip ends up.
 *
 * @param props The tenant name and the finish callback — see {@link SecurityStepProps}.
 * @returns The step's body band and its action band, plus the enrolment dialog.
 */
export function SecurityStep({ tenantName, onFinish }: SecurityStepProps) {
  const { data: session } = useAuthSession();
  const reauth = useTwoFactorReauth();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [enrolled, setEnrolled] = useState(false);

  /** Already on — an account that enrolled before it had a tenant, or just now. */
  const enabled =
    enrolled || Boolean((session?.user as { twoFactorEnabled?: boolean } | undefined)?.twoFactorEnabled);

  /** Closing the dialog finishes the step once enrolment went through. */
  const handleDialogClose = () => {
    setDialogOpen(false);
    if (enrolled) onFinish();
  };

  return (
    <>
      <div className="wiz-card__body" data-testid="onboarding-step-security">
        <span className="auth-icon auth-icon--honey" aria-hidden="true">
          <ShieldPlus />
        </span>
        <h1 id="first-tenant-onboarding-title" className="auth-title mt-4">
          Protect your account
        </h1>
        <p className="auth-sub mt-2">
          {tenantName} is ready. Add two-factor authentication so signing in also needs a code
          from your phone — it takes about a minute.
        </p>

        {enabled ? (
          <Alert
            variant="success"
            role="status"
            icon={<ShieldCheck aria-hidden="true" />}
            className="mt-4"
            data-testid="onboarding-two-factor-on"
          >
            Two-factor authentication is on. You can manage it from Profile → Security.
          </Alert>
        ) : (
          <ul className="mt-4 flex flex-col gap-1" aria-label="What setting it up involves">
            {ENROLMENT_OUTLINE.map((item) => (
              <li key={item} className="flex items-start gap-2 text-sm text-fg-muted">
                <Check aria-hidden="true" className="mt-px size-3.5 shrink-0 text-ok-fg" />
                {item}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="wiz-card__foot">
        {enabled ? (
          <Button
            variant="primary"
            className="ml-auto"
            onClick={onFinish}
            data-testid="onboarding-security-continue"
          >
            Continue
            <ArrowRight aria-hidden="true" />
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onFinish} data-testid="onboarding-security-skip">
              Skip for now
            </Button>
            <Button
              variant="primary"
              onClick={() => setDialogOpen(true)}
              data-testid="onboarding-security-enable"
            >
              <ShieldPlus aria-hidden="true" />
              Set up two-factor
            </Button>
          </>
        )}
      </div>

      <TwoFactorEnrollDialog
        open={dialogOpen}
        onClose={handleDialogClose}
        reauth={reauth}
        onEnrolled={() => setEnrolled(true)}
        regenerateFrom={REGENERATE_FROM}
      />
    </>
  );
}

export default SecurityStep;
