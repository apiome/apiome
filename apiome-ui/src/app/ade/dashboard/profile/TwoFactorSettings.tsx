'use client';

/**
 * Profile TOTP settings (OLO-9.13 #5014 + OLO-9.15 #5015 + OLO-9.50 #5070; re-skinned by
 * HIVE-4.7, #5301).
 *
 * Password-gated enable (QR + confirm + one-time backup reveal) and disable, plus self-service
 * management when enrolled: remaining backup-code count, password-gated regenerate, forget-this-
 * device (per-browser trust cookie), recovery guidance, and Email OTP availability when SendGrid
 * is configured (server-level OTP — no separate enroll).
 *
 * ## What HIVE-4.7 changed, and what it did not
 *
 * **Not** the behaviour. Every call, every error string, every busy label and every `data-testid`
 * is the one `tests/two-factor-settings.test.tsx` already pins, and that suite passes against
 * this file unchanged — which is the point: this is the most complex form cluster in the app,
 * and a redesign that quietly altered a 2FA flow would be a security change wearing a
 * stylesheet's clothes.
 *
 * What changed is everything a token can reach. The six nested boxes were
 * `border-gray-200 dark:border-gray-700` rectangles with `text-emerald-500`, `text-amber-500`,
 * `text-sky-500` and `text-indigo-500` glyphs, and the three dialogs opened with
 * `bg-emerald-100 dark:bg-emerald-900/40` tiles — eleven named colours that froze on one
 * palette. They are icon tiles and hairlines drawn from role tokens now, so the cluster follows
 * all nine themes.
 *
 * Two things are genuinely new, both from the mockup's Adds list: the multi-step dialogs carry
 * the shared {@link import('@/app/components/ui/Stepper').Stepper} in their headers, so a reader
 * can see how far through enrolment they are, and the revealed backup codes can be downloaded as
 * well as copied ({@link import('@/app/components/ade/account/BackupCodes').BackupCodes}).
 *
 * One deliberate deviation from `docs/mockups/account/profile.html`: the mockup prints the
 * two-factor state three times — a badge in the Security card's header, a badge on this row, and
 * "2FA on" in the identity hero. Two of those are kept (the hero's summary and this row's, which
 * is the one beside the control that changes it); the card header carries none, because the third
 * copy says nothing the first two did not.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Check,
  KeyRound,
  Mail,
  MonitorSmartphone,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
  ShieldPlus,
  X,
} from 'lucide-react';
import { authClient } from '@lib/auth/auth-client';
import { signIn, useAuthSession } from '@lib/auth/session-client';
import {
  getBackupCodeStatus,
  getEmailOtpAvailability,
  getTrustedDeviceStatus,
  revokeThisTrustedDevice,
} from '@lib/auth/two-factor-profile-actions';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/app/components/ui/Dialog';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Card } from '@/app/components/ui/Card';
import { Stepper } from '@/app/components/ui/Stepper';
import { ICON_SIZE } from '@/app/components/ui/iconSizes';
import { DismissibleCallout } from '@/app/components/ui/DismissibleCallout';
import { BackupCodes } from '@/app/components/ade/account/BackupCodes';
import {
  TwoFactorEnrollDialog,
  withIdentityStep,
} from '@/app/components/ade/account/TwoFactorEnrollDialog';
import { TwoFactorReauthNotice } from '@/app/components/ade/account/TwoFactorReauthNotice';
import { useTwoFactorReauth } from '@/app/components/ade/account/useTwoFactorReauth';
import { REAUTH_REQUIRED_CODE, TRUST_DEVICE_DAYS } from '@lib/auth/two-factor-policy';
import { cn } from '@lib/utils';

type RegenStep = 'password' | 'reveal';

/** The regenerate wizard's steps. */
const REGEN_STEPS = [
  { id: 'password', label: 'Confirm password' },
  { id: 'reveal', label: 'Save new codes' },
] as const;

/**
 * The `hive.seen.<id>` key of the "turn on two-factor" reminder (TFA-1.4 #5658). It shows while
 * two-factor is off — whether the reader skipped it during onboarding or never met it — until
 * they press **Got it** on this device; the **Enable 2FA** button stays either way.
 */
export const TWO_FACTOR_REMINDER_ID = 'profile-two-factor-reminder';

interface TwoFactorSettingsProps {
  /** Optional class for the outer status block. */
  className?: string;
}

/**
 * Status + enable/disable/self-service controls for authenticator (TOTP) 2FA on the Profile
 * Security card.
 *
 * @param props.className Optional wrapper class.
 * @returns The two-factor block and its three dialogs.
 */
export function TwoFactorSettings({ className }: TwoFactorSettingsProps) {
  const { data: session, update } = useAuthSession();
  const enabled = Boolean(session?.user?.twoFactorEnabled);

  const [enrollOpen, setEnrollOpen] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);
  const [regenOpen, setRegenOpen] = useState(false);
  const [regenStep, setRegenStep] = useState<RegenStep>('password');
  const [password, setPassword] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [trusted, setTrusted] = useState(false);
  const [statusLoading, setStatusLoading] = useState(false);
  const [emailOtpAvailable, setEmailOtpAvailable] = useState(false);
  /** How this account confirms it is them (TFA-1.1 #5655) — shared with the enrolment dialog. */
  const reauthState = useTwoFactorReauth();
  const { reauth, passwordless, needsReauth, markStale } = reauthState;

  /**
   * Show a refused change, and switch the open dialog to "sign in again" when the server says
   * the session has gone stale since the page loaded.
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

  /**
   * Send the reader through their provider again and bring them back to this page.
   *
   * @param providerId The linked provider to sign in with.
   */
  const handleReauth = (providerId: string) => {
    void signIn(providerId, { callbackUrl: window.location.pathname });
  };

  const refreshManagementStatus = useCallback(async () => {
    if (!enabled) {
      setRemaining(null);
      setTrusted(false);
      setEmailOtpAvailable(false);
      return;
    }
    setStatusLoading(true);
    try {
      const [codes, device, emailOtp] = await Promise.all([
        getBackupCodeStatus(),
        getTrustedDeviceStatus(),
        getEmailOtpAvailability(),
      ]);
      setRemaining(codes.remaining);
      setTrusted(device.trusted);
      setEmailOtpAvailable(emailOtp.available);
    } catch {
      setRemaining(null);
      setTrusted(false);
      setEmailOtpAvailable(false);
    } finally {
      setStatusLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    void refreshManagementStatus();
  }, [refreshManagementStatus]);

  const resetRegen = () => {
    setRegenStep('password');
    setPassword('');
    setBackupCodes([]);
    setError('');
    setBusy(false);
  };

  const openEnroll = () => {
    setError('');
    setEnrollOpen(true);
  };

  const openDisable = () => {
    setPassword('');
    setError('');
    setBusy(false);
    setDisableOpen(true);
  };

  const openRegen = () => {
    resetRegen();
    setRegenOpen(true);
  };

  const refreshSessionFlag = async () => {
    // update() always refetches; the server session now carries the flipped twoFactorEnabled.
    await update({});
  };

  const handleDisable = async () => {
    if (!passwordless && !password) {
      setError('Enter your current password to disable two-factor authentication.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const res = await authClient.twoFactor.disable(passwordless ? {} : { password });
      if (res?.error) {
        showRefusal(res.error, 'Could not disable 2FA. Check your password and try again.');
        setBusy(false);
        return;
      }
      await refreshSessionFlag();
      setDisableOpen(false);
      setPassword('');
      setRemaining(null);
      setTrusted(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Disable failed.');
    } finally {
      setBusy(false);
    }
  };

  const handleRegenerate = async () => {
    if (!passwordless && !password) {
      setError('Enter your current password to regenerate backup codes.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const res = await authClient.twoFactor.generateBackupCodes(passwordless ? {} : { password });
      if (res?.error) {
        showRefusal(res.error, 'Could not regenerate codes. Check your password and try again.');
        setBusy(false);
        return;
      }
      const data = res.data as { backupCodes?: string[] } | null;
      const nextCodes = Array.isArray(data?.backupCodes) ? data.backupCodes : [];
      if (nextCodes.length === 0) {
        setError('No backup codes were returned. Please try again.');
        setBusy(false);
        return;
      }
      setBackupCodes(nextCodes);
      setRemaining(nextCodes.length);
      setRegenStep('reveal');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Regenerate failed.');
    } finally {
      setBusy(false);
    }
  };

  /**
   * The first step for an account without a password, in place of the password box.
   *
   * @returns The shared notice; `null` for an account with a password.
   */
  const renderReauthNotice = () =>
    reauth && (
      <TwoFactorReauthNotice reauth={reauth} busy={busy} onReauth={handleReauth} />
    );

  const handleForgetDevice = async () => {
    setBusy(true);
    setError('');
    try {
      const res = await revokeThisTrustedDevice();
      if (!res.ok) {
        setError('Could not forget this device. Try again.');
        return;
      }
      setTrusted(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not forget this device.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn('acct-2fa', className)} data-testid="two-factor-settings">
      <div className="acct-row">
        <span className={enabled ? 'acct-glyph acct-glyph--ok' : 'acct-glyph'} aria-hidden>
          <ShieldCheck />
        </span>
        <div className="acct-row__body">
          <div className="acct-row__title">
            Authenticator app (TOTP)
            <Badge status={enabled ? 'active' : 'disabled'} data-testid="two-factor-status">
              {enabled ? 'Enabled' : 'Off'}
            </Badge>
          </div>
          <p className="acct-row__desc">
            Require a code from Authy or Google Authenticator each time you sign in.
          </p>
        </div>
        {enabled && (
          <Button
            size="sm"
            variant="outline"
            onClick={openDisable}
            data-testid="two-factor-disable-open"
          >
            <ShieldOff aria-hidden />
            Disable 2FA
          </Button>
        )}
      </div>

      {enabled ? (
        <>
          <Card variant="soft" className="acct-methods" data-testid="two-factor-methods">
            <div className="acct-caps">Sign-in methods</div>
            <ul className="acct-methods__list">
              <li>
                <Check size={ICON_SIZE.dense} className="text-ok" aria-hidden />
                Authenticator app (TOTP)
              </li>
              {emailOtpAvailable && (
                <li data-testid="two-factor-method-email-otp">
                  <Check size={ICON_SIZE.dense} className="text-ok" aria-hidden />
                  Email OTP — available at sign-in (no separate enrollment)
                </li>
              )}
            </ul>
          </Card>

          <div className="acct-mfa">
            {emailOtpAvailable && (
              <div className="acct-mfa__box" data-testid="two-factor-email-otp-info">
                <div className="acct-mfa__title">
                  <Mail size={ICON_SIZE.dense} aria-hidden />
                  Email one-time code
                </div>
                <p className="acct-mfa__desc">
                  When you sign in, you can request a code emailed to your account address
                  instead of (or in addition to) using your authenticator app.
                </p>
              </div>
            )}

            <div className="acct-mfa__box">
              <div className="acct-mfa__title">
                <KeyRound size={ICON_SIZE.dense} aria-hidden />
                Backup codes
              </div>
              <p className="acct-mfa__desc" data-testid="two-factor-backup-remaining">
                {statusLoading
                  ? 'Checking remaining codes…'
                  : remaining === null
                    ? 'Remaining count unavailable'
                    : `${remaining} remaining`}
              </p>
              <Button
                size="sm"
                variant="outline"
                onClick={openRegen}
                data-testid="two-factor-regen-open"
              >
                <RefreshCw aria-hidden />
                Regenerate backup codes
              </Button>
            </div>

            <div className="acct-mfa__box">
              <div className="acct-mfa__title">
                <MonitorSmartphone size={ICON_SIZE.dense} aria-hidden />
                Trusted device
              </div>
              <p className="acct-mfa__desc" data-testid="two-factor-trusted-status">
                {statusLoading
                  ? 'Checking this browser…'
                  : trusted
                    ? `This browser is trusted (skips 2FA for ${TRUST_DEVICE_DAYS} days when signing in).`
                    : 'This browser is not marked as trusted.'}
              </p>
              {trusted && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleForgetDevice}
                  disabled={busy}
                  data-testid="two-factor-forget-device"
                >
                  <X aria-hidden />
                  {busy ? 'Working…' : 'Forget this device'}
                </Button>
              )}
            </div>
          </div>

          <Alert variant="info" data-testid="two-factor-recovery-guidance">
            <span className="font-semibold">Recovery.</span> Store backup codes somewhere safe. If
            you lose your authenticator, use a backup code at sign-in or contact an admin. After recovery, regenerate codes so old ones cannot be reused.
          </Alert>

          {error && !disableOpen && !regenOpen && !enrollOpen && (
            <Alert variant="error">{error}</Alert>
          )}
        </>
      ) : (
        <>
          <DismissibleCallout
            id={TWO_FACTOR_REMINDER_ID}
            reopenFrom="Enable 2FA (Security card)"
            tone="honey"
            icon={<ShieldPlus aria-hidden />}
          >
            <span data-testid="two-factor-reminder">
              <strong>Two-factor is off.</strong> Turn it on to ask for a code from Authy or Google
              Authenticator whenever you sign in.
            </span>
          </DismissibleCallout>
          <Button
            variant="primary"
            className="w-full"
            onClick={openEnroll}
            data-testid="two-factor-enable-open"
          >
            <ShieldPlus aria-hidden />
            Enable 2FA
          </Button>
        </>
      )}

      <TwoFactorEnrollDialog
        open={enrollOpen}
        onClose={() => {
          setEnrollOpen(false);
          void refreshManagementStatus();
        }}
        reauth={reauthState}
      />

      {/* Regenerate backup codes */}
      <Dialog
        open={regenOpen}
        onOpenChange={(open) => {
          if (busy) return;
          setRegenOpen(open);
          if (!open) resetRegen();
        }}
      >
        <DialogContent size="sm">
          <DialogHeader className="acct-dialog__header acct-dialog__header--stacked">
            <div className="acct-dialog__lead">
              <span className="acct-glyph acct-glyph--warn" aria-hidden>
                <RefreshCw />
              </span>
              <div className="acct-dialog__heading">
                <DialogTitle>
                  {regenStep === 'password' ? 'Regenerate backup codes' : 'Save new backup codes'}
                </DialogTitle>
                <DialogDescription>
                  {regenStep === 'password'
                    ? passwordless
                      ? 'Confirm it is you. This replaces your existing backup codes immediately.'
                      : 'Enter your password. This replaces your existing backup codes immediately.'
                    : 'Copy these codes now. The previous set is no longer valid.'}
                </DialogDescription>
              </div>
            </div>
            <Stepper
              steps={passwordless ? withIdentityStep(REGEN_STEPS) : REGEN_STEPS}
              current={regenStep}
              fill
              aria-label="Regeneration progress"
              data-testid="two-factor-regen-stepper"
            />
          </DialogHeader>

          <div className="acct-dialog__body">
            {error && <Alert variant="error">{error}</Alert>}
            {regenStep === 'password' && (
              <>
                {passwordless ? (
                  renderReauthNotice()
                ) : (
                  <div className="acct-field">
                    <Label htmlFor="tfa-regen-password">Current password</Label>
                    <Input
                      id="tfa-regen-password"
                      type="password"
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      disabled={busy}
                      autoFocus
                      data-testid="two-factor-regen-password"
                      onKeyDown={(e) => e.key === 'Enter' && !busy && handleRegenerate()}
                    />
                  </div>
                )}
                {remaining !== null && (
                  <Alert variant="warn">
                    Your {remaining} remaining codes stop working the moment new ones are issued.
                  </Alert>
                )}
              </>
            )}
            {regenStep === 'reveal' && <BackupCodes codes={backupCodes} />}
          </div>

          <DialogFooter>
            {regenStep === 'password' && (
              <>
                <Button variant="outline" onClick={() => setRegenOpen(false)} disabled={busy}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={handleRegenerate}
                  disabled={busy || needsReauth}
                  data-testid="two-factor-regen-confirm"
                >
                  {busy ? 'Working…' : 'Regenerate'}
                </Button>
              </>
            )}
            {regenStep === 'reveal' && (
              <Button
                variant="primary"
                onClick={() => {
                  setRegenOpen(false);
                  resetRegen();
                }}
                data-testid="two-factor-regen-done"
              >
                Done
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Disable dialog */}
      <Dialog
        open={disableOpen}
        onOpenChange={(open) => {
          if (busy) return;
          setDisableOpen(open);
          if (!open) {
            setPassword('');
            setError('');
          }
        }}
      >
        <DialogContent size="sm" role="alertdialog">
          <DialogHeader className="acct-dialog__header">
            <span className="acct-glyph acct-glyph--danger" aria-hidden>
              <ShieldOff />
            </span>
            <div className="acct-dialog__heading">
              <DialogTitle>Disable two-factor authentication</DialogTitle>
              <DialogDescription>
                {passwordless
                  ? 'Confirm it is you to turn off authenticator codes on this account.'
                  : 'Enter your password to turn off authenticator codes on this account.'}
              </DialogDescription>
            </div>
          </DialogHeader>
          <div className="acct-dialog__body">
            {error && <Alert variant="error">{error}</Alert>}
            {passwordless ? (
              renderReauthNotice()
            ) : (
              <div className="acct-field">
                <Label htmlFor="tfa-disable-password">Current password</Label>
                <Input
                  id="tfa-disable-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={busy}
                  autoFocus
                  data-testid="two-factor-disable-password"
                  onKeyDown={(e) => e.key === 'Enter' && !busy && handleDisable()}
                />
              </div>
            )}
            <p className="acct-hint">
              Backup codes and the trusted-device cookie are cleared too. You can re-enable 2FA any
              time.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDisableOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleDisable}
              disabled={busy || needsReauth}
              data-testid="two-factor-disable-confirm"
            >
              {busy ? 'Disabling…' : 'Disable 2FA'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
