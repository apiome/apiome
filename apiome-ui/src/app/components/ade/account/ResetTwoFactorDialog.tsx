'use client';

import * as React from 'react';
import { ShieldOff } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Spinner } from '@/app/components/ui/Spinner';
import { Textarea } from '@/app/components/ui/Textarea';
import {
  RESET_REASON_MAX_LENGTH,
  RESET_REASON_MIN_LENGTH,
  isValidResetReason,
  matchesResetConfirmation,
  type TwoFactorResetOutcome,
} from '@lib/auth/two-factor-reset';

/** The person whose two-factor is being reset. */
export interface ResetTwoFactorTarget {
  /** Their user id. */
  userId: string;
  /** Their email address — what the reader types to confirm. */
  email: string;
  /** Their display name, when they have one. */
  name?: string | null;
}

/** Props for {@link ResetTwoFactorDialog}. */
export interface ResetTwoFactorDialogProps {
  /** Whether the dialog is showing. */
  open: boolean;
  /** Called with `false` when it is dismissed. */
  onOpenChange: (open: boolean) => void;
  /** Who is being reset; `null` while the dialog is closed. */
  target: ResetTwoFactorTarget | null;
  /**
   * The route that performs the reset for this caller: the admin console's
   * (`/api/admin/users/{id}/two-factor/reset`) or a workspace owner's
   * (`/api/access/members/{id}/two-factor/reset`).
   *
   * @param userId The target's user id.
   * @returns The URL to POST to.
   */
  endpoint: (userId: string) => string;
  /** Called once the reset has gone through, with what it cleared. */
  onReset?: (outcome: TwoFactorResetOutcome, target: ResetTwoFactorTarget) => void;
}

/**
 * The sentence shown after a reset, which changes with whether the user could be told by email.
 *
 * @param outcome What the reset cleared.
 * @param target Who was reset.
 * @returns What happened, and what the reader may still have to do.
 */
export function describeResetOutcome(
  outcome: TwoFactorResetOutcome,
  target: ResetTwoFactorTarget
): string {
  const done = `Two-factor was reset for ${target.email} and they were signed out everywhere.`;
  return outcome.emailSent
    ? `${done} They have been emailed.`
    : `${done} No email was sent, because this installation cannot send email — let them know yourself.`;
}

/**
 * Reset someone's two-factor — the confirmation an administrator fills in (TFA-1.2, #5656).
 *
 * Used by the admin console and by the member drawer; the only thing that differs between them is
 * the route that performs the reset, which is why it is a prop.
 *
 * The dialog asks for two things, and both are also enforced by apiome-rest:
 *
 * - a **reason**, which goes into the audit trail and is never shown to the user;
 * - the user's **email address typed out**, so the reset cannot be confirmed by reflex — the
 *   point of a typed confirmation is that it names who this is about to happen to.
 *
 * After a reset the dialog stays open on the result rather than closing, because the result
 * carries an instruction the reader must not miss: whether the user was emailed, or has to be
 * told another way.
 *
 * @param props See {@link ResetTwoFactorDialogProps}.
 * @returns The dialog.
 */
export function ResetTwoFactorDialog({
  open,
  onOpenChange,
  target,
  endpoint,
  onReset,
}: ResetTwoFactorDialogProps) {
  const [reason, setReason] = React.useState('');
  const [confirm, setConfirm] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const [outcome, setOutcome] = React.useState<TwoFactorResetOutcome | null>(null);

  // Each opening is a new decision: nothing typed for one person carries over to the next.
  React.useEffect(() => {
    if (open) {
      setReason('');
      setConfirm('');
      setError('');
      setOutcome(null);
      setBusy(false);
    }
  }, [open, target?.userId]);

  const ready =
    Boolean(target) && isValidResetReason(reason) && matchesResetConfirmation(confirm, target?.email);

  /** Send the reset and show what came back. */
  const submit = async () => {
    if (!target || !ready || busy) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch(endpoint(target.userId), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason.trim(), confirm: confirm.trim() }),
      });
      const json = (await response.json().catch(() => null)) as
        | { success?: boolean; data?: TwoFactorResetOutcome; error?: string }
        | null;
      if (!response.ok || !json?.success || !json.data) {
        setError(json?.error || 'The two-factor reset could not be completed. Try again.');
        return;
      }
      setOutcome(json.data);
      onReset?.(json.data, target);
    } catch {
      setError('The two-factor reset could not be completed. Check your connection and try again.');
    } finally {
      setBusy(false);
    }
  };

  const who = target?.name?.trim() || target?.email || 'this user';

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent size="sm" role="alertdialog" data-testid="reset-two-factor-dialog">
        <DialogHeader className="acct-dialog__header">
          <span className="acct-glyph acct-glyph--danger" aria-hidden>
            <ShieldOff />
          </span>
          <div className="acct-dialog__heading">
            <DialogTitle>Reset two-factor for {who}?</DialogTitle>
            <DialogDescription>
              Their authenticator and backup codes stop working, their trusted devices are
              forgotten and they are signed out everywhere. They sign in with their first factor
              only until they set two-factor up again.
            </DialogDescription>
          </div>
        </DialogHeader>

        <div className="acct-dialog__body">
          {error && <Alert variant="error">{error}</Alert>}

          {outcome && target ? (
            <Alert variant={outcome.emailSent ? 'ok' : 'warn'} data-testid="reset-two-factor-result">
              {describeResetOutcome(outcome, target)}
            </Alert>
          ) : (
            <>
              <div className="acct-field">
                <Label htmlFor="reset-two-factor-reason">Reason</Label>
                <Textarea
                  id="reset-two-factor-reason"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  maxLength={RESET_REASON_MAX_LENGTH}
                  rows={3}
                  disabled={busy}
                  aria-describedby="reset-two-factor-reason-hint"
                  data-testid="reset-two-factor-reason"
                />
                <p className="acct-hint" id="reset-two-factor-reason-hint">
                  At least {RESET_REASON_MIN_LENGTH} characters. Kept in the audit trail; the user
                  does not see it.
                </p>
              </div>
              <div className="acct-field">
                <Label htmlFor="reset-two-factor-confirm">
                  Type <span className="mono">{target?.email}</span> to confirm
                </Label>
                <Input
                  id="reset-two-factor-confirm"
                  type="text"
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={confirm}
                  onChange={(event) => setConfirm(event.target.value)}
                  disabled={busy}
                  data-testid="reset-two-factor-confirm"
                  onKeyDown={(event) => event.key === 'Enter' && void submit()}
                />
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          {outcome ? (
            <Button variant="primary" onClick={() => onOpenChange(false)} data-testid="reset-two-factor-done">
              Done
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={() => void submit()}
                disabled={busy || !ready}
                data-testid="reset-two-factor-submit"
              >
                {busy && <Spinner size="sm" aria-hidden />}
                {busy ? 'Resetting…' : 'Reset two-factor'}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
