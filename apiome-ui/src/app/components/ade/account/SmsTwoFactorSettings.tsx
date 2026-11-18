'use client';

/**
 * Text-message (SMS) two-factor codes on Profile → Security (OLO-9.51 #5071).
 *
 * One box in the `.acct-mfa` row, shown only when two-factor is on and the server can send texts.
 * It walks the reader through the three things SMS codes need, in order:
 *
 * 1. **Add a phone number** — a two-step dialog: the number, then the code texted to it
 *    (`authClient.phoneNumber.sendOtp` / `.verify({ updatePhoneNumber: true })`). Nothing is
 *    stored until the code comes back, so every stored number is verified.
 * 2. **Send codes by text** — choosing SMS asks for the password (or a fresh sign-in for an
 *    account without one), because where the codes go decides who can finish a sign-in. Without
 *    a verified number the choice is not offered; the box says to add one first.
 * 3. **Change / Remove** — a new number puts codes back on email until SMS is chosen again;
 *    removing the number does the same.
 *
 * The parent owns the status (it also decides whether the email-code line still applies) and is
 * told to reload it after every change.
 */

import { useState } from 'react';
import { Mail, MessageSquare, Phone, Trash2 } from 'lucide-react';
import { authClient } from '@lib/auth/auth-client';
import { isE164PhoneNumber, normalizePhoneNumber } from '@lib/auth/phone-number-format';
import {
  removePhoneNumber,
  setTwoFactorOtpChannel,
  type OtpChannelRefusal,
  type SmsTwoFactorStatus,
} from '@lib/auth/two-factor-sms-actions';
import type { TwoFactorOtpChannel } from '@lib/auth/two-factor-otp-dispatch';
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
import { ICON_SIZE } from '@/app/components/ui/iconSizes';
import { TwoFactorReauthNotice } from './TwoFactorReauthNotice';
import type { TwoFactorReauth } from './useTwoFactorReauth';

/** The add-number dialog's steps. */
const PHONE_STEPS = [
  { id: 'number', label: 'Phone number' },
  { id: 'code', label: 'Enter code' },
] as const;

type PhoneStep = (typeof PHONE_STEPS)[number]['id'];

/** The sentence for each refusal the delivery actions can answer with. */
export const SMS_REFUSAL_COPY: Readonly<Record<OtpChannelRefusal, string>> = {
  UNAUTHENTICATED: 'Your session has ended. Sign in again and retry.',
  TWO_FACTOR_NOT_ENABLED: 'Turn on two-factor authentication first.',
  SMS_NOT_CONFIGURED: 'Text-message codes are not available on this server.',
  PHONE_NUMBER_NOT_VERIFIED:
    'Add and verify a phone number first — codes can only be texted to a number you have confirmed.',
  INVALID_PASSWORD: 'That password was not accepted.',
  REAUTH_REQUIRED: 'Sign in again to confirm it is you, then retry.',
  FAILED: 'Could not save the change. Try again.',
};

/** Why a button is greyed out while a request is in flight (the gate wants every disabled button to say). */
const BUSY_REASON = 'Wait for the current request to finish';

/** The code length the phoneNumber plugin issues. */
const CODE_LENGTH = 6;

interface SmsTwoFactorSettingsProps {
  /** The reader's SMS settings (from `getSmsTwoFactorStatus`). */
  status: SmsTwoFactorStatus;
  /** Called after any change so the parent reloads the status. */
  onChanged: () => void | Promise<void>;
  /** How this account confirms it is them (shared with the other two-factor dialogs). */
  reauth: TwoFactorReauth;
  /** Starts a provider sign-in for a passwordless account whose session is stale. */
  onReauth: (providerId: string) => void;
}

/**
 * The SMS box and its two dialogs.
 *
 * @param props See {@link SmsTwoFactorSettingsProps}.
 * @returns The box.
 */
export function SmsTwoFactorSettings({
  status,
  onChanged,
  reauth,
  onReauth,
}: SmsTwoFactorSettingsProps) {
  const [phoneOpen, setPhoneOpen] = useState(false);
  const [phoneStep, setPhoneStep] = useState<PhoneStep>('number');
  const [phoneInput, setPhoneInput] = useState('');
  const [code, setCode] = useState('');
  const [channelOpen, setChannelOpen] = useState(false);
  const [targetChannel, setTargetChannel] = useState<TwoFactorOtpChannel>('sms');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const verified = status.phoneNumber !== null;
  const usingSms = verified && status.channel === 'sms';
  const normalized = normalizePhoneNumber(phoneInput);
  const busyReason = busy ? BUSY_REASON : undefined;

  const openPhone = () => {
    setPhoneStep('number');
    setPhoneInput('');
    setCode('');
    setError('');
    setPhoneOpen(true);
  };

  const openChannel = (channel: TwoFactorOtpChannel) => {
    setTargetChannel(channel);
    setPassword('');
    setError('');
    setChannelOpen(true);
  };

  /** Text a verification code to the typed number (also the "resend" path). */
  const handleSendCode = async () => {
    if (!isE164PhoneNumber(normalized)) {
      setError('Enter the number with its country code, like +1 415 555 0123.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const res = await authClient.phoneNumber.sendOtp({ phoneNumber: normalized });
      if (res?.error) {
        setError(res.error.message || 'Could not send the code. Try again.');
        return;
      }
      setPhoneStep('code');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send the code.');
    } finally {
      setBusy(false);
    }
  };

  /** Confirm the texted code; the plugin stores the number on success. */
  const handleVerify = async () => {
    if (!new RegExp(`^\\d{${CODE_LENGTH}}$`).test(code)) {
      setError(`Enter the ${CODE_LENGTH}-digit code we texted you.`);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const res = await authClient.phoneNumber.verify({
        phoneNumber: normalized,
        code,
        updatePhoneNumber: true,
      });
      if (res?.error) {
        setError(res.error.message || 'That code was not accepted. Check it and try again.');
        return;
      }
      setPhoneOpen(false);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verification failed.');
    } finally {
      setBusy(false);
    }
  };

  /** Save the delivery choice after the identity check. */
  const handleChannel = async () => {
    if (!reauth.passwordless && !password) {
      setError('Enter your current password to change where codes are sent.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const res = await setTwoFactorOtpChannel({
        channel: targetChannel,
        password: reauth.passwordless ? undefined : password,
      });
      if (!res.ok) {
        if (res.error === 'REAUTH_REQUIRED') reauth.markStale();
        setError(SMS_REFUSAL_COPY[res.error]);
        return;
      }
      setChannelOpen(false);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : SMS_REFUSAL_COPY.FAILED);
    } finally {
      setBusy(false);
    }
  };

  /** Remove the number; codes go back to email. */
  const handleRemove = async () => {
    setBusy(true);
    setError('');
    try {
      const res = await removePhoneNumber();
      if (!res.ok) {
        setError(SMS_REFUSAL_COPY[res.error]);
        return;
      }
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : SMS_REFUSAL_COPY.FAILED);
    } finally {
      setBusy(false);
    }
  };

  const description = !verified
    ? 'Get sign-in codes by text message. Add and verify a phone number first.'
    : usingSms
      ? `Sign-in codes are texted to ${status.phoneNumber}.`
      : `${status.phoneNumber} is verified. Sign-in codes still go to your email.`;

  return (
    <div className="acct-mfa__box" data-testid="two-factor-sms">
      <div className="acct-mfa__title">
        <MessageSquare size={ICON_SIZE.dense} aria-hidden />
        Text message code
      </div>
      <p className="acct-mfa__desc" data-testid="two-factor-sms-status">
        {description}
      </p>
      {error && !phoneOpen && !channelOpen && <Alert variant="error">{error}</Alert>}
      <div className="acct-mfa__actions">
        {verified && !usingSms && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => openChannel('sms')}
            disabled={busy}
            title={busyReason}
            data-testid="two-factor-sms-use"
          >
            <MessageSquare aria-hidden />
            Send codes by text
          </Button>
        )}
        {usingSms && status.emailAvailable && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => openChannel('email')}
            disabled={busy}
            title={busyReason}
            data-testid="two-factor-sms-use-email"
          >
            <Mail aria-hidden />
            Send codes by email
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          onClick={openPhone}
          disabled={busy}
          title={busyReason}
          data-testid="two-factor-sms-add"
        >
          <Phone aria-hidden />
          {verified ? 'Change number' : 'Add phone number'}
        </Button>
        {verified && (
          <Button
            size="sm"
            variant="ghost"
            onClick={handleRemove}
            disabled={busy}
            title={busyReason}
            data-testid="two-factor-sms-remove"
          >
            <Trash2 aria-hidden />
            Remove
          </Button>
        )}
      </div>

      {/* Add / change a phone number */}
      <Dialog
        open={phoneOpen}
        onOpenChange={(open) => {
          if (busy) return;
          setPhoneOpen(open);
        }}
      >
        <DialogContent size="sm">
          <DialogHeader className="acct-dialog__header acct-dialog__header--stacked">
            <div className="acct-dialog__lead">
              <span className="acct-glyph" aria-hidden>
                <Phone />
              </span>
              <div className="acct-dialog__heading">
                <DialogTitle>{verified ? 'Change phone number' : 'Add phone number'}</DialogTitle>
                <DialogDescription>
                  {phoneStep === 'number'
                    ? 'We will text a 6-digit code to confirm the number is yours.'
                    : `Enter the code we texted to ${normalized}.`}
                </DialogDescription>
              </div>
            </div>
            <Stepper
              steps={PHONE_STEPS}
              current={phoneStep}
              fill
              aria-label="Phone verification progress"
              data-testid="two-factor-sms-stepper"
            />
          </DialogHeader>
          <div className="acct-dialog__body">
            {error && <Alert variant="error">{error}</Alert>}
            {phoneStep === 'number' ? (
              <div className="acct-field">
                <Label htmlFor="tfa-sms-phone">Mobile number</Label>
                <Input
                  id="tfa-sms-phone"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="+1 415 555 0123"
                  value={phoneInput}
                  onChange={(e) => setPhoneInput(e.target.value)}
                  disabled={busy}
                  autoFocus
                  data-testid="two-factor-sms-phone"
                  onKeyDown={(e) => e.key === 'Enter' && !busy && handleSendCode()}
                />
                <p className="acct-hint">
                  Include the country code. Message and data rates may apply.
                </p>
              </div>
            ) : (
              <div className="acct-field">
                <Label htmlFor="tfa-sms-code">Verification code</Label>
                <Input
                  id="tfa-sms-code"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={CODE_LENGTH}
                  placeholder="000000"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, CODE_LENGTH))}
                  disabled={busy}
                  autoFocus
                  data-testid="two-factor-sms-code"
                  onKeyDown={(e) => e.key === 'Enter' && !busy && handleVerify()}
                />
                {verified && (
                  <p className="acct-hint">
                    Sign-in codes go to your email until you choose text messages again.
                  </p>
                )}
              </div>
            )}
          </div>
          <DialogFooter>
            {phoneStep === 'number' ? (
              <>
                <Button
                  variant="outline"
                  onClick={() => setPhoneOpen(false)}
                  title={busyReason}
                  disabled={busy}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={handleSendCode}
                  disabled={busy || !normalized}
                  title={
                    busy ? BUSY_REASON : !normalized ? 'Enter a phone number first' : undefined
                  }
                  data-testid="two-factor-sms-send"
                >
                  {busy ? 'Sending…' : 'Send code'}
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="outline"
                  onClick={handleSendCode}
                  title={busyReason}
                  disabled={busy}
                >
                  Resend code
                </Button>
                <Button
                  variant="primary"
                  onClick={handleVerify}
                  disabled={busy || code.length !== CODE_LENGTH}
                  title={
                    busy
                      ? BUSY_REASON
                      : code.length !== CODE_LENGTH
                        ? `Enter all ${CODE_LENGTH} digits first`
                        : undefined
                  }
                  data-testid="two-factor-sms-verify"
                >
                  {busy ? 'Verifying…' : 'Verify'}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Choose where codes go */}
      <Dialog
        open={channelOpen}
        onOpenChange={(open) => {
          if (busy) return;
          setChannelOpen(open);
        }}
      >
        <DialogContent size="sm">
          <DialogHeader className="acct-dialog__header">
            <span className="acct-glyph" aria-hidden>
              {targetChannel === 'sms' ? <MessageSquare /> : <Mail />}
            </span>
            <div className="acct-dialog__heading">
              <DialogTitle>
                {targetChannel === 'sms'
                  ? 'Send sign-in codes by text'
                  : 'Send sign-in codes by email'}
              </DialogTitle>
              <DialogDescription>
                {targetChannel === 'sms'
                  ? `Codes will be texted to ${status.phoneNumber} instead of emailed.`
                  : 'Codes will be emailed to your account address instead of texted.'}
              </DialogDescription>
            </div>
          </DialogHeader>
          <div className="acct-dialog__body">
            {error && <Alert variant="error">{error}</Alert>}
            {reauth.passwordless ? (
              reauth.reauth && (
                <TwoFactorReauthNotice reauth={reauth.reauth} busy={busy} onReauth={onReauth} />
              )
            ) : (
              <div className="acct-field">
                <Label htmlFor="tfa-sms-password">Current password</Label>
                <Input
                  id="tfa-sms-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={busy}
                  autoFocus
                  data-testid="two-factor-sms-password"
                  onKeyDown={(e) => e.key === 'Enter' && !busy && handleChannel()}
                />
              </div>
            )}
            {targetChannel === 'sms' && (
              <p className="acct-hint">
                Text messages can be intercepted if someone takes over your mobile number. Your
                authenticator app stays the stronger choice.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setChannelOpen(false)}
              title={busyReason}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handleChannel}
              disabled={busy || reauth.needsReauth}
              title={busy ? BUSY_REASON : reauth.needsReauth ? 'Sign in again first' : undefined}
              data-testid="two-factor-sms-channel-confirm"
            >
              {busy ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
