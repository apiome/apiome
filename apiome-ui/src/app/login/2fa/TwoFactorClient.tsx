'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { ArrowLeft, KeyRound, LifeBuoy, Mail, RefreshCw, Send, ShieldCheck } from 'lucide-react';
import { authClient } from '@lib/auth/auth-client';
import {
  peekTwoFactorMethods,
  takeTwoFactorCallbackUrl,
  takeTwoFactorMethods,
  TWO_FACTOR_DEFAULT_CALLBACK,
  type TwoFactorMethod,
} from '@lib/auth/two-factor-callback';
import { browserNavigate } from '@lib/auth/browser-navigate';
import {
  TRUST_DEVICE_DAYS,
  describeTwoFactorRefusal,
  isCompleteBackupCode,
  normalizeBackupCode,
} from '@lib/auth/two-factor-policy';
import { BrandMark } from '../../components/brand';
import { AuthShell } from '../../components/auth/AuthShell';
import { AuthField } from '../../components/auth/AuthField';
import { BetaBadge } from '../../components/auth/BetaBadge';
import { getAuthErrorCopy } from '../auth-error-copy';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Checkbox } from '../../components/ui/Checkbox';
import { Spinner } from '../../components/ui/Spinner';
import { ICON_SIZE } from '@/app/components/ui/iconSizes';

/**
 * How long the code the second factor asks for is. Both Better Auth methods issue six
 * digits, which is why one field serves both and why submit stays disabled until then.
 */
const CODE_LENGTH = 6;

/** A complete code: six digits and nothing else. */
const COMPLETE_CODE = /^\d{6}$/;

/**
 * Keep only the digits of whatever landed in the box, capped at {@link CODE_LENGTH}.
 *
 * Applied on every change rather than on paste alone, so a pasted `"123 456"`, a code
 * copied with its trailing newline and a mistyped letter all resolve the same way.
 *
 * @param raw What the control now holds.
 * @returns The digits of `raw`, at most six of them.
 */
const sanitizeCode = (raw: string): string => raw.replace(/\D/g, '').slice(0, CODE_LENGTH);

/** Everything that differs between the two second factors, in one table. */
interface MethodCopy {
  /** The tab's label in the method switcher. */
  tab: string;
  /** The card's heading for this method. */
  heading: string;
  /** The `id` of this method's code box — the label points at it. */
  fieldId: string;
  /** The code box's visible name. */
  fieldLabel: string;
  /** Shown when submit is pressed with fewer than six digits, before any request. */
  incomplete: string;
  /** Shown when the API rejects the code and sends no message of its own. */
  rejected: string;
}

const METHOD_COPY: Readonly<Record<TwoFactorMethod, MethodCopy>> = {
  totp: {
    tab: 'Authenticator',
    heading: 'Two-factor authentication',
    fieldId: 'totp-code',
    fieldLabel: 'Authentication code',
    incomplete: 'Enter the 6-digit code from your authenticator app.',
    rejected: 'That code was not accepted. Check your authenticator app and try again.',
  },
  otp: {
    tab: 'Email code',
    heading: 'Check your email',
    fieldId: 'email-otp-code',
    fieldLabel: 'Email code',
    incomplete: 'Enter the 6-digit code from your email.',
    rejected: 'That code was not accepted. Request a new email code and try again.',
  },
};

/**
 * The recovery path's copy (OLO-9.14 #5006). A backup code is not one of the challenge's
 * methods — every enrolled account has a set — so it is not a tab in the switcher but a
 * second face of the card, reached from a link under the form.
 */
const BACKUP_COPY = {
  heading: 'Use a backup code',
  description:
    'Enter one of the backup codes you saved when you turned on two-factor. Each code works once.',
  fieldId: 'backup-code',
  fieldLabel: 'Backup code',
  incomplete: 'Enter a whole backup code — ten characters, like ab12c-de34f.',
  rejected: 'That backup code was not accepted. Each code works once — check it and try another.',
} as const;

/** The description under the heading — the only line that also depends on progress. */
const TOTP_DESCRIPTION =
  'Enter the 6-digit code from Authy, Google Authenticator, or another TOTP app.';
const OTP_DESCRIPTION_BEFORE_SEND =
  'We will email a 6-digit code to the address on your account.';
const OTP_DESCRIPTION_AFTER_SEND = 'Enter the 6-digit code we emailed you.';

interface TwoFactorClientProps {
  /** Validated by the page (resolveCallbackUrl) before being passed in. */
  callbackUrl?: string;
  error?: string;
  /**
   * The methods this challenge offers, when the server named them in the URL — the provider
   * sign-in path (TFA-1.1 #5655). Already reduced to the known methods by the page. Absent after
   * a password sign-in, which stores them in `sessionStorage` instead.
   */
  methods?: TwoFactorMethod[];
}

/**
 * Second-factor verification after password sign-in (OLO-9.13 #5014 + OLO-9.50 #5070,
 * re-skinned by HIVE-4.2 #5296).
 *
 * Authority: `docs/mockups/auth/two-factor.html`, `docs/mockups/DESIGN.md` §2 and §7.
 *
 * Nothing about the flow moved. It still honours `twoFactorMethods` from the challenge —
 * TOTP (`verifyTotp`), email OTP (`sendOtp` / `verifyOtp`), or a switcher when both are
 * offered — still reads and clears the same two `sessionStorage` keys, and still carries
 * every error string it carried before. What changed is that the screen is now drawn from
 * the Hive token layer instead of a page-local stylesheet of named colours: the aurora
 * blobs, the tiled BETA watermark and the glass card are gone, so the second step follows
 * the reader's theme, density and font-scale preference like the rest of the app.
 *
 * The frame is `components/auth/AuthShell` in its centred shape (no brand panel), shared
 * with `/login` — see the "AUTH SURFACES" section of `globals.css` for the skin.
 *
 * The method switcher is a real `role="tablist"`, driven by Radix rather than by hand,
 * because the two methods are two *panes*: arrow keys move between them and select as they
 * move, and the group keeps a single Tab stop. The card's own strip is drawn as the
 * segmented well of DESIGN.md §7 (`.auth-methods`) rather than the app's underline tabs,
 * which the mockup calls for explicitly — an underline strip inside a 27 rem card reads as
 * a page's primary sections rather than as one field's choice.
 */
const TwoFactorClient: React.FC<TwoFactorClientProps> = ({
  callbackUrl = TWO_FACTOR_DEFAULT_CALLBACK,
  error,
  methods: offeredMethods,
}) => {
  // What the server named for this challenge wins over what an earlier, abandoned sign-in may
  // have left in `sessionStorage`.
  const methods = useMemo(
    () => (offeredMethods && offeredMethods.length > 0 ? offeredMethods : peekTwoFactorMethods()),
    [offeredMethods]
  );
  const [activeMethod, setActiveMethod] = useState<TwoFactorMethod>(() =>
    methods.includes('totp') ? 'totp' : methods[0] ?? 'totp'
  );
  const [code, setCode] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSendingOtp, setIsSendingOtp] = useState(false);
  const [otpSent, setOtpSent] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  /**
   * Whether the code box may still take focus on mount.
   *
   * The box is autofocused on arrival, which is what the reader wants: they have the code
   * in front of them already. It must not happen a second time, though — the switcher
   * selects as the arrow keys move, so a freshly mounted panel that grabbed focus would
   * strand the reader in the field they were trying to move past.
   */
  const [autoFocusCode, setAutoFocusCode] = useState(true);
  /** Whether the card is showing the backup-code form instead of the challenge's methods. */
  const [useBackupCode, setUseBackupCode] = useState(false);
  const [backupCode, setBackupCode] = useState('');
  /** Whether a successful verification should also mark this browser as trusted. */
  const [trustDevice, setTrustDevice] = useState(false);
  /**
   * Set once no code can succeed here — the factor is locked, or the challenge is spent or
   * expired. The form is disabled so the reader is not invited to keep feeding a counter.
   */
  const [blocked, setBlocked] = useState(false);

  const queryError = getAuthErrorCopy(error);
  const showMethodSwitcher = methods.includes('totp') && methods.includes('otp');
  const copy = METHOD_COPY[activeMethod];
  const bannerText = localError ?? queryError?.text;

  /** The challenge is spent: drop what was stored for it and leave for the callback. */
  const finishSuccess = () => {
    takeTwoFactorMethods();
    const destination = takeTwoFactorCallbackUrl(callbackUrl);
    browserNavigate(destination);
  };

  /**
   * Show a refused verification, and close the form when nothing further can succeed.
   *
   * @param refusal The `error` the client call answered with.
   * @param fallback The sentence for a refusal the server did not explain.
   */
  const showRefusal = (
    refusal: { code?: string | null; message?: string | null } | null | undefined,
    fallback: string
  ) => {
    const described = describeTwoFactorRefusal(refusal, fallback);
    setLocalError(described.text);
    if (described.terminal) setBlocked(true);
    setIsSubmitting(false);
  };

  /**
   * Redeem a backup code in place of the second factor (OLO-9.14 #5006).
   *
   * The server consumes the code on success, so it cannot be used again, and counts a wrong
   * one toward the same lockout as a wrong authenticator code.
   *
   * @param e The form's submit event.
   */
  const handleBackupSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const normalized = normalizeBackupCode(backupCode);
    if (!isCompleteBackupCode(normalized)) {
      setLocalError(BACKUP_COPY.incomplete);
      return;
    }
    setIsSubmitting(true);
    setLocalError(null);
    try {
      const res = await authClient.twoFactor.verifyBackupCode({ code: normalized, trustDevice });
      if (res?.error) {
        showRefusal(res.error, BACKUP_COPY.rejected);
        return;
      }
      finishSuccess();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'Verification failed. Please try again.');
      setIsSubmitting(false);
    }
  };

  /**
   * Move between the challenge's methods and the backup-code form.
   *
   * Whatever was typed and whatever was wrong belongs to the form being left, so both go.
   *
   * @param next `true` to show the backup-code form.
   */
  const toggleBackupCode = (next: boolean) => {
    setUseBackupCode(next);
    setCode('');
    setBackupCode('');
    setLocalError(null);
    setAutoFocusCode(true);
  };

  /**
   * Verify the code in the box with whichever method is showing.
   *
   * Both methods answer the same shape, so the only thing that differs is which client
   * call is made and which sentence is shown when the API rejects the code without one of
   * its own.
   *
   * @param e The form's submit event.
   */
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = sanitizeCode(code);
    if (!COMPLETE_CODE.test(trimmed)) {
      setLocalError(copy.incomplete);
      return;
    }
    setIsSubmitting(true);
    setLocalError(null);
    try {
      const res =
        activeMethod === 'otp'
          ? await authClient.twoFactor.verifyOtp({ code: trimmed, trustDevice })
          : await authClient.twoFactor.verifyTotp({ code: trimmed, trustDevice });
      if (res?.error) {
        showRefusal(res.error, copy.rejected);
        return;
      }
      finishSuccess();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'Verification failed. Please try again.');
      setIsSubmitting(false);
    }
  };

  /** Ask Better Auth to mail a fresh code. Also the "resend" path — same request. */
  const handleSendOtp = async () => {
    setIsSendingOtp(true);
    setLocalError(null);
    try {
      const res = await authClient.twoFactor.sendOtp({});
      if (res?.error) {
        setLocalError(res.error.message || 'Could not send the email code. Try again.');
        return;
      }
      setOtpSent(true);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'Could not send the email code.');
    } finally {
      setIsSendingOtp(false);
    }
  };

  /**
   * Show a different second factor.
   *
   * The half-typed code and any error belong to the method that was showing, so both go:
   * an authenticator code is not an email code, and the sentence about one would be read
   * as being about the other.
   *
   * @param method The method the reader moved to.
   */
  const selectMethod = (method: string) => {
    if (method !== 'totp' && method !== 'otp') return;
    setActiveMethod(method);
    setCode('');
    setLocalError(null);
    setAutoFocusCode(false);
  };

  const description = useBackupCode
    ? BACKUP_COPY.description
    : activeMethod === 'otp'
      ? otpSent
        ? OTP_DESCRIPTION_AFTER_SEND
        : OTP_DESCRIPTION_BEFORE_SEND
      : TOTP_DESCRIPTION;

  /**
   * The "Trust this device" tick box, shared by every form on the card (OLO-9.14 #5006).
   *
   * Unticked by default: trusting a browser is the reader's decision, and the wrong default on
   * a shared computer would skip the second factor for whoever sits down next.
   *
   * @returns The labelled tick box.
   */
  const renderTrustDevice = () => (
    <label className="auth-check" htmlFor="two-factor-trust-device">
      <Checkbox
        id="two-factor-trust-device"
        checked={trustDevice}
        onCheckedChange={(checked) => setTrustDevice(checked === true)}
        disabled={isSubmitting || blocked}
        data-testid="two-factor-trust-device"
      />
      <span>
        Trust this device for {TRUST_DEVICE_DAYS} days
        <span className="auth-check__hint">Skip this step when you sign in from this browser.</span>
      </span>
    </label>
  );

  /**
   * The card body for the recovery path: one backup-code box, the tick box, and submit.
   *
   * @returns The form.
   */
  const renderBackupForm = () => (
    <form onSubmit={handleBackupSubmit} className="mt-5 flex flex-col gap-4" noValidate>
      <AuthField
        className="auth-backup-code"
        id={BACKUP_COPY.fieldId}
        label={BACKUP_COPY.fieldLabel}
        icon={<LifeBuoy size={ICON_SIZE.dense} aria-hidden="true" />}
        hint="Ten letters and digits · capitals matter"
        name="backupCode"
        type="text"
        autoComplete="off"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        autoFocus={autoFocusCode}
        placeholder="xxxxx-xxxxx"
        value={backupCode}
        onChange={(e) => setBackupCode(normalizeBackupCode(e.target.value))}
        disabled={isSubmitting || blocked}
        invalid={Boolean(localError)}
        data-testid="two-factor-backup-code"
      />

      {renderTrustDevice()}

      <Button
        type="submit"
        variant="primary"
        size="lg"
        className="w-full"
        disabled={isSubmitting || blocked || !isCompleteBackupCode(backupCode)}
        data-testid="two-factor-backup-submit"
      >
        {isSubmitting && <Spinner size="sm" tone="light" aria-hidden="true" />}
        {isSubmitting ? 'Verifying…' : 'Verify and continue'}
      </Button>
    </form>
  );

  /**
   * The card body for one method: the send button (email only), the code box, and submit.
   *
   * Written once and called for each method rather than spelled out twice, so the two
   * paths cannot drift on the parts the ticket requires of both — digits only, six of
   * them, `one-time-code`, and a submit that stays disabled until the code is complete.
   *
   * @param method Which second factor this form verifies.
   * @returns The form.
   */
  const renderForm = (method: TwoFactorMethod) => {
    const form = METHOD_COPY[method];
    const isComplete = code.length === CODE_LENGTH;

    return (
      <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4" noValidate>
        {method === 'otp' && (
          <Button
            type="button"
            variant="outline"
            size="lg"
            className="w-full"
            onClick={handleSendOtp}
            disabled={isSendingOtp || isSubmitting || blocked}
            data-testid="two-factor-send-otp"
          >
            {isSendingOtp ? (
              <Spinner size="sm" aria-hidden="true" />
            ) : otpSent ? (
              <RefreshCw aria-hidden="true" />
            ) : (
              <Send aria-hidden="true" />
            )}
            {isSendingOtp ? 'Sending…' : otpSent ? 'Resend email code' : 'Send email code'}
          </Button>
        )}

        <AuthField
          className="auth-code"
          id={form.fieldId}
          label={form.fieldLabel}
          icon={
            method === 'otp' ? (
              <Mail size={ICON_SIZE.dense} aria-hidden="true" />
            ) : (
              <KeyRound size={ICON_SIZE.dense} aria-hidden="true" />
            )
          }
          hint={`Digits only · the button enables once ${CODE_LENGTH} digits are entered`}
          name="code"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          autoFocus={autoFocusCode}
          maxLength={CODE_LENGTH}
          pattern="\d{6}"
          placeholder="000000"
          value={code}
          onChange={(e) => setCode(sanitizeCode(e.target.value))}
          disabled={isSubmitting || blocked}
          invalid={Boolean(localError)}
          data-testid={method === 'otp' ? 'two-factor-otp-code' : 'two-factor-totp-code'}
        />

        {renderTrustDevice()}

        <Button
          type="submit"
          variant="primary"
          size="lg"
          className="w-full"
          disabled={isSubmitting || blocked || !isComplete}
          data-testid={method === 'otp' ? 'two-factor-otp-submit' : 'two-factor-submit'}
        >
          {isSubmitting && <Spinner size="sm" tone="light" aria-hidden="true" />}
          {isSubmitting ? 'Verifying…' : 'Verify and continue'}
        </Button>
      </form>
    );
  };

  return (
    <AuthShell>
      {/* The mark sits above the card rather than inside it: this page has no brand panel,
          so it is the only thing naming the product the reader is signing in to. */}
      <div className="auth-brandbar">
        <BrandMark variant="lockup" size={36} className="auth-brand__lockup" priority />
        <BetaBadge />
      </div>

      <Card data-testid="two-factor-card" className="auth-card">
        <span className="auth-icon" aria-hidden="true">
          {useBackupCode ? <LifeBuoy /> : activeMethod === 'otp' ? <Mail /> : <ShieldCheck />}
        </span>
        <h1 className="auth-title mt-4">{useBackupCode ? BACKUP_COPY.heading : copy.heading}</h1>
        <p className="auth-sub mt-1">{description}</p>

        {/* One banner for both sources: the local "that is not six digits" sentence and the
            `?error=` copy the redirect carries. `role="alert"` so a screen reader is
            interrupted — a rejected code is the reader's next problem, not a note. */}
        {bannerText && (
          <Alert
            variant="danger"
            role="alert"
            data-testid="two-factor-error"
            className="mt-4"
          >
            {bannerText}
          </Alert>
        )}

        {/* The email code has been sent, which nothing else on the card announces: the
            description changes, and a changed paragraph is not read out. */}
        {!useBackupCode && activeMethod === 'otp' && otpSent && !bannerText && (
          <Alert
            variant="ok"
            role="status"
            aria-live="polite"
            data-testid="two-factor-otp-sent"
            className="mt-4"
          >
            Email code sent. Check your inbox.
          </Alert>
        )}

        {useBackupCode ? (
          renderBackupForm()
        ) : showMethodSwitcher ? (
          <TabsPrimitive.Root value={activeMethod} onValueChange={selectMethod}>
            <TabsPrimitive.List
              className="auth-methods mt-5"
              aria-label="Verification method"
              data-testid="two-factor-method-switcher"
            >
              {(['totp', 'otp'] as const).map((method) => (
                <TabsPrimitive.Trigger
                  key={method}
                  value={method}
                  className="auth-methods__tab"
                  data-testid={`two-factor-method-${method}`}
                >
                  {method === 'otp' ? (
                    <Mail aria-hidden="true" />
                  ) : (
                    <ShieldCheck aria-hidden="true" />
                  )}
                  {METHOD_COPY[method].tab}
                </TabsPrimitive.Trigger>
              ))}
            </TabsPrimitive.List>
            <TabsPrimitive.Content value="totp">{renderForm('totp')}</TabsPrimitive.Content>
            <TabsPrimitive.Content value="otp">{renderForm('otp')}</TabsPrimitive.Content>
          </TabsPrimitive.Root>
        ) : (
          renderForm(activeMethod)
        )}

        {/* The recovery path. A button, not a link: it changes what the card shows and goes
            nowhere. Hidden once the screen is closed — a backup code would be refused too. */}
        {!blocked && (
          <div className="auth-sub mt-5 text-center">
            <button
              type="button"
              className="auth-link font-medium"
              onClick={() => toggleBackupCode(!useBackupCode)}
              disabled={isSubmitting}
              data-testid="two-factor-toggle-backup"
            >
              {useBackupCode ? 'Use a verification code instead' : 'Lost your device? Use a backup code'}
            </button>
          </div>
        )}

        <div className="auth-sub mt-6 text-center">
          <Link
            href={`/login?callbackUrl=${encodeURIComponent(callbackUrl)}`}
            className="auth-link inline-flex items-center gap-1.5 font-medium"
          >
            <ArrowLeft className="size-[var(--icon-button)]" aria-hidden="true" />
            Back to sign in
          </Link>
        </div>
      </Card>
    </AuthShell>
  );
};

export default TwoFactorClient;
