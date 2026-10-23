'use client';

/**
 * The authenticator (TOTP) enrolment dialog: confirm it's you → scan the QR → save backup codes
 * (OLO-9.13 #5014, re-skinned by HIVE-4.7 #5301, passwordless by TFA-1.1 #5655).
 *
 * Moved out of Profile's `TwoFactorSettings` by TFA-1.4 (#5658) so the onboarding wizard's
 * **Protect your account** step runs the *same* enrolment rather than a second copy of a
 * security flow. Every call, error string, busy label and `data-testid` is the one
 * `tests/two-factor-settings.test.tsx` pinned before the move.
 */

import { useState } from 'react';
import QRCode from 'react-qr-code';
import { Check, Copy, ShieldPlus } from 'lucide-react';
import { authClient } from '@lib/auth/auth-client';
import { signIn, useAuthSession } from '@lib/auth/session-client';
import { dismissTwoFactorResetNotice } from '@lib/auth/two-factor-profile-actions';
import { REAUTH_REQUIRED_CODE } from '@lib/auth/two-factor-policy';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Stepper } from '@/app/components/ui/Stepper';
import { BackupCodes } from './BackupCodes';
import { TwoFactorReauthNotice } from './TwoFactorReauthNotice';
import type { TwoFactorReauth } from './useTwoFactorReauth';

type EnrollStep = 'password' | 'qr' | 'backup';

/** The enrolment wizard's steps, in order — the header stepper and `step` share this list. */
const ENROLL_STEPS = [
  { id: 'password', label: 'Confirm password' },
  { id: 'qr', label: 'Scan QR code' },
  { id: 'backup', label: 'Save backup codes' },
] as const;

/** How long the "Copied" confirmation on the otpauth URI stays up, in milliseconds. */
const COPIED_RESET_MS = 2000;

/**
 * Relabel a wizard's first step for an account that has no password to confirm (TFA-1.1 #5655).
 *
 * @param steps A wizard's steps, the first of which is `password`.
 * @returns The same steps with the first one named for what the reader actually does.
 */
export const withIdentityStep = <T extends { id: string; label: string }>(
  steps: readonly T[]
): T[] =>
  steps.map((step) => (step.id === 'password' ? { ...step, label: "Confirm it's you" } : step));

/** Props for {@link TwoFactorEnrollDialog}. */
export interface TwoFactorEnrollDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Close the dialog. Called with `false` only — the dialog never opens itself. */
  onClose: () => void;
  /** The account's re-authentication status, from {@link useTwoFactorReauth}. */
  reauth: TwoFactorReauth;
  /** Called once the code is verified and two-factor is on (before the backup codes show). */
  onEnrolled?: () => void;
  /**
   * Where the reader can regenerate backup codes later, finishing the backup step's description.
   * Defaults to `this page` (Profile).
   */
  regenerateFrom?: string;
}

/**
 * Enrol an authenticator app.
 *
 * The dialog resets itself every time it closes, so it always opens on the first step. While a
 * call is in flight it cannot be closed.
 *
 * @param props See {@link TwoFactorEnrollDialogProps}.
 * @returns The dialog.
 */
export function TwoFactorEnrollDialog({
  open,
  onClose,
  reauth,
  onEnrolled,
  regenerateFrom = 'this page',
}: TwoFactorEnrollDialogProps) {
  const { update } = useAuthSession();
  const { passwordless, needsReauth, markStale } = reauth;

  const [step, setStep] = useState<EnrollStep>('password');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [totpURI, setTotpURI] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const reset = () => {
    setStep('password');
    setPassword('');
    setCode('');
    setTotpURI('');
    setBackupCodes([]);
    setError('');
    setBusy(false);
    setCopied(false);
  };

  /** Close and reset, so the next open starts on the first step. */
  const close = () => {
    onClose();
    reset();
  };

  /**
   * Show a refused change, and switch to "sign in again" when the server says the session has
   * gone stale since the page loaded.
   *
   * @param refusal The `error` the client call answered with.
   * @param fallback The sentence for a refusal the server did not explain.
   */
  const showRefusal = (
    refusal: { code?: string | null; message?: string | null },
    fallback: string
  ) => {
    if (refusal.code === REAUTH_REQUIRED_CODE) {
      markStale();
      setError('');
      return;
    }
    setError(refusal.message || fallback);
  };

  const handleEnablePassword = async () => {
    if (!passwordless && !password) {
      setError('Enter your current password to enable two-factor authentication.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const res = await authClient.twoFactor.enable(passwordless ? {} : { password });
      if (res?.error) {
        showRefusal(res.error, 'Could not start enrollment. Check your password and try again.');
        setBusy(false);
        return;
      }
      const data = res.data as { totpURI?: string; backupCodes?: string[] } | null;
      if (!data?.totpURI) {
        setError('Enrollment did not return a TOTP URI. Please try again.');
        setBusy(false);
        return;
      }
      setTotpURI(data.totpURI);
      setBackupCodes(Array.isArray(data.backupCodes) ? data.backupCodes : []);
      setStep('qr');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Enrollment failed.');
    } finally {
      setBusy(false);
    }
  };

  const handleConfirmTotp = async () => {
    const trimmed = code.replace(/\s/g, '');
    if (!/^\d{6}$/.test(trimmed)) {
      setError('Enter the 6-digit code from your authenticator app.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const res = await authClient.twoFactor.verifyTotp({ code: trimmed });
      if (res?.error) {
        setError(res.error.message || 'That code was not accepted. Try again.');
        setBusy(false);
        return;
      }
      // update() always refetches; the server session now carries the flipped twoFactorEnabled.
      await update({});
      // Enrolling again answers an administrator's reset (TFA-1.2 #5656): the "set two-factor up
      // again" notice has done its job. Best-effort — the notice also hides itself once enrolled.
      void dismissTwoFactorResetNotice().catch(() => undefined);
      setStep('backup');
      onEnrolled?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verification failed.');
    } finally {
      setBusy(false);
    }
  };

  const handleCopyUri = async () => {
    try {
      await navigator.clipboard.writeText(totpURI);
      setCopied(true);
      setTimeout(() => setCopied(false), COPIED_RESET_MS);
    } catch {
      // Clipboard unavailable — the URI is on screen and the QR is beside it.
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (busy || next) return;
        close();
      }}
    >
      <DialogContent size="lg">
        <DialogHeader className="acct-dialog__header acct-dialog__header--stacked">
          <div className="acct-dialog__lead">
            <span className="acct-glyph acct-glyph--ok" aria-hidden>
              <ShieldPlus />
            </span>
            <div className="acct-dialog__heading">
              <DialogTitle>Enable two-factor authentication</DialogTitle>
              <DialogDescription>
                {step === 'password' &&
                  (passwordless
                    ? 'Confirm it is you to start enrollment. You will scan a QR code next.'
                    : 'Confirm your password to start enrollment. You will scan a QR code next.')}
                {step === 'qr' &&
                  'Scan this QR with Authy or Google Authenticator, then enter the 6-digit code.'}
                {step === 'backup' &&
                  `Store these one-time codes somewhere safe. You can regenerate a new set later from ${regenerateFrom}.`}
              </DialogDescription>
            </div>
          </div>
          <Stepper
            steps={passwordless ? withIdentityStep(ENROLL_STEPS) : ENROLL_STEPS}
            current={step}
            fill
            aria-label="Enrollment progress"
            data-testid="two-factor-enroll-stepper"
          />
        </DialogHeader>

        <div className="acct-dialog__body">
          {error && <Alert variant="error">{error}</Alert>}

          {step === 'password' && passwordless && reauth.reauth && (
            <TwoFactorReauthNotice
              reauth={reauth.reauth}
              busy={busy}
              onReauth={(providerId) =>
                void signIn(providerId, { callbackUrl: window.location.pathname })
              }
            />
          )}
          {step === 'password' && !passwordless && (
            <div className="acct-field">
              <Label htmlFor="tfa-enroll-password">Current password</Label>
              <Input
                id="tfa-enroll-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={busy}
                autoFocus
                data-testid="two-factor-enroll-password"
                onKeyDown={(e) => e.key === 'Enter' && !busy && handleEnablePassword()}
              />
            </div>
          )}

          {step === 'qr' && (
            <div className="acct-enroll">
              {/* Literally white, and deliberately so: a QR code is read by a camera, and
                  the quiet zone has to stay light in every theme for it to scan. */}
              <div className="acct-qr bg-white" data-testid="two-factor-qr">
                <QRCode value={totpURI} size={180} />
              </div>
              <div className="acct-enroll__fields">
                <div className="acct-field">
                  <div className="acct-caps">Or enter this URI</div>
                  <div className="acct-uri">
                    <code className="mono">{totpURI}</code>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={handleCopyUri}
                      aria-label={copied ? 'Copied URI' : 'Copy URI'}
                      title={copied ? 'Copied URI' : 'Copy URI'}
                      data-testid="two-factor-copy-uri"
                    >
                      {copied ? <Check className="text-ok" aria-hidden /> : <Copy aria-hidden />}
                    </Button>
                  </div>
                </div>
                <div className="acct-field">
                  <Label htmlFor="tfa-enroll-code">Authentication code</Label>
                  <Input
                    id="tfa-enroll-code"
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    placeholder="000000"
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    disabled={busy}
                    className="acct-code-input mono"
                    data-testid="two-factor-enroll-code"
                    onKeyDown={(e) => e.key === 'Enter' && !busy && handleConfirmTotp()}
                  />
                </div>
              </div>
            </div>
          )}

          {step === 'backup' && <BackupCodes codes={backupCodes} />}
        </div>

        <DialogFooter>
          {step !== 'backup' && (
            <Button variant="outline" onClick={close} disabled={busy}>
              Cancel
            </Button>
          )}
          {step === 'password' && (
            <Button
              variant="primary"
              onClick={handleEnablePassword}
              disabled={busy || needsReauth}
              data-testid="two-factor-enroll-continue"
            >
              {busy ? 'Working…' : 'Continue'}
            </Button>
          )}
          {step === 'qr' && (
            <Button
              variant="primary"
              onClick={handleConfirmTotp}
              disabled={busy || code.length !== 6}
              data-testid="two-factor-enroll-verify"
            >
              {busy ? 'Verifying…' : 'Confirm and enable'}
            </Button>
          )}
          {step === 'backup' && (
            <Button variant="primary" onClick={close} data-testid="two-factor-enroll-done">
              Done
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default TwoFactorEnrollDialog;
