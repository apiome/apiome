'use client';

/**
 * `useUnsavedChangesGuard` — one dirty-state guard for every form (SUX-2.6, apiome#6753).
 *
 * Every screen that holds an unsaved draft had its own guard, and none of them covered the
 * commonest way to lose work: an in-app link. While `dirty`, this hook:
 *
 * 1. asks the browser to confirm a reload, close or cross-document navigation (`beforeunload`,
 *    through {@link useUnsavedChangesPrompt});
 * 2. intercepts a plain click on any same-origin link that would leave the current route — the
 *    App Router's `<Link>`s included, because the capture-phase listener on `document` runs
 *    before React's — and asks first;
 * 3. intercepts the browser's Back button (see `unsavedChangesNavigation.ts` for the sentinel
 *    entry this relies on) and asks first. Forward cannot leave a dirty screen: pushing the
 *    sentinel clears the forward stack.
 *
 * The question is the shared {@link AlertDialog} with three answers: **Save** (only when
 * `onSave` is given — saves, then leaves; a failed save stays), **Discard** (calls `onDiscard`,
 * then leaves) and **Cancel** (stays; Escape does the same). A clean form never asks.
 *
 * A move the screen makes itself — a `router.push` from a button, switching the item being
 * edited — cannot be seen from outside, so the hook also returns `confirmLeave(proceed)`, which
 * runs `proceed` straight away when clean and after the same question when dirty.
 *
 * The returned `dirty` is the value to hand to `FormFrame`'s footer, so the marker and the
 * guard can never disagree. Render the returned `dialog` once, anywhere in the screen.
 *
 * Only one guard answers at a time: when two dirty guards are mounted together, the one that
 * became dirty last owns the question.
 *
 * @example
 * const guard = useUnsavedChangesGuard({ dirty, onSave: save, onDiscard: reset });
 * return (
 *   <>
 *     <FormFrame dirty={guard.dirty} onSubmit={save}>…</FormFrame>
 *     {guard.dialog}
 *   </>
 * );
 */

import * as React from 'react';
import { useRouter } from 'next/navigation';

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/app/components/ui/AlertDialog';
import { Button } from '@/app/components/ui/Button';
import { useUnsavedChangesPrompt } from './useUnsavedChangesPrompt';
import {
  inAppNavigationTarget,
  isUnsavedGuardSentinel,
  pushUnsavedGuardSentinel,
  removeUnsavedGuardSentinel,
  silentHistoryGo,
} from './unsavedChangesNavigation';

/** Options for {@link useUnsavedChangesGuard}. */
export interface UnsavedChangesGuardOptions {
  /** Whether there is unsaved work. Nothing is registered while this is false. */
  dirty: boolean;
  /**
   * Save the draft. Offered as the dialog's **Save** button only when given. Return (or resolve
   * to) `false`, or throw, to report a failed save: the dialog closes and the screen stays, so the
   * screen's own error is visible.
   */
  onSave?: () => boolean | void | Promise<boolean | void>;
  /** Throw the draft away before leaving (e.g. reset the form). Called on **Discard**. */
  onDiscard?: () => void;
  /** Dialog title. Defaults to "Leave without saving?". */
  title?: string;
  /** Dialog body. Defaults to a sentence naming what is lost. */
  description?: string;
}

/** What {@link useUnsavedChangesGuard} returns. */
export interface UnsavedChangesGuard {
  /** The `dirty` passed in — hand it to `FormFrame`'s `dirty` prop. */
  dirty: boolean;
  /** The confirm dialog. Render it once in the screen. */
  dialog: React.ReactNode;
  /** True while the dialog is asking. */
  asking: boolean;
  /**
   * Guard a move the screen makes itself.
   *
   * @param proceed Runs at once when clean; after Save or Discard when dirty; never on Cancel.
   */
  confirmLeave: (proceed: () => void) => void;
}

/** The move waiting on the user's answer. */
type PendingLeave =
  { kind: 'link'; href: string } | { kind: 'back' } | { kind: 'custom'; proceed: () => void };

/**
 * The dirty guards currently mounted, newest last. Only the last one answers a click or a Back,
 * so two guards on one page never ask twice.
 */
const activeGuards: symbol[] = [];

/**
 * Whether `id` is the guard that should answer right now.
 *
 * @param id A guard's identity.
 * @returns True when it is the most recently activated guard.
 */
function ownsNavigation(id: symbol): boolean {
  return activeGuards[activeGuards.length - 1] === id;
}

const DEFAULT_TITLE = 'Leave without saving?';
const DEFAULT_DESCRIPTION =
  'You have unsaved changes on this page. Save them before you go, or discard them.';

/**
 * Guard a dirty form against every way of leaving it. See the module comment.
 *
 * @param options See {@link UnsavedChangesGuardOptions}.
 * @returns See {@link UnsavedChangesGuard}.
 */
export function useUnsavedChangesGuard(options: UnsavedChangesGuardOptions): UnsavedChangesGuard {
  const { dirty, onSave, title = DEFAULT_TITLE, description = DEFAULT_DESCRIPTION } = options;
  const router = useRouter();

  const [pending, setPending] = React.useState<PendingLeave | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [id] = React.useState(() => Symbol('unsaved-changes-guard'));

  // Latest callbacks, read at answer time, so a screen need not memoise them.
  const optionsRef = React.useRef(options);
  React.useEffect(() => {
    optionsRef.current = options;
  });
  // Set while the guard itself is leaving: its own history moves must not be re-intercepted, and
  // cleanup must not remove the sentinel underneath them.
  const leavingRef = React.useRef(false);

  useUnsavedChangesPrompt(dirty);

  React.useEffect(() => {
    if (!dirty) return undefined;
    leavingRef.current = false;
    activeGuards.push(id);
    pushUnsavedGuardSentinel();

    const onClick = (event: MouseEvent) => {
      if (!ownsNavigation(id)) return;
      const href = inAppNavigationTarget(event);
      if (!href) return;
      event.preventDefault();
      event.stopPropagation();
      setPending({ kind: 'link', href });
    };

    const onPopState = (event: PopStateEvent) => {
      if (leavingRef.current || !ownsNavigation(id)) return;
      if (isUnsavedGuardSentinel(event.state)) return;
      // Back from the sentinel lands on the original copy of this page: nothing visible has
      // changed yet, so hide the traversal from the router and ask.
      event.stopImmediatePropagation();
      setPending({ kind: 'back' });
    };

    document.addEventListener('click', onClick, true);
    window.addEventListener('popstate', onPopState, true);
    return () => {
      document.removeEventListener('click', onClick, true);
      window.removeEventListener('popstate', onPopState, true);
      const index = activeGuards.indexOf(id);
      if (index >= 0) activeGuards.splice(index, 1);
      if (!leavingRef.current && activeGuards.length === 0) void removeUnsavedGuardSentinel();
    };
  }, [dirty, id]);

  // A form that became clean while asking (saved elsewhere) has nothing left to ask about.
  React.useEffect(() => {
    if (!dirty && pending && !saving) {
      const move = pending;
      setPending(null);
      if (move.kind === 'custom') move.proceed();
    }
  }, [dirty, pending, saving]);

  /**
   * Carry out the move that was asked about.
   *
   * @param move The pending move.
   */
  const leave = React.useCallback(
    async (move: PendingLeave) => {
      if (move.kind === 'back') {
        // Still on the original entry: one more step back is where the user was going.
        window.history.back();
        return;
      }
      if (move.kind === 'custom') {
        move.proceed();
        return;
      }
      await removeUnsavedGuardSentinel();
      router.push(move.href);
    },
    [router]
  );

  /** Cancel: stay, and put the sentinel back when Back was what asked. */
  const cancel = React.useCallback(() => {
    if (saving || !pending) return;
    if (pending.kind === 'back') void silentHistoryGo(1);
    setPending(null);
  }, [pending, saving]);

  /** Discard: drop the draft, then leave. */
  const discard = React.useCallback(() => {
    if (!pending || saving) return;
    const move = pending;
    // A move the screen makes itself keeps the screen mounted, so only real departures mark it.
    leavingRef.current = move.kind !== 'custom';
    setPending(null);
    optionsRef.current.onDiscard?.();
    void leave(move);
  }, [leave, pending, saving]);

  /** Save: save, then leave — or stay when the save fails. */
  const save = React.useCallback(async () => {
    const saveDraft = optionsRef.current.onSave;
    if (!pending || saving || !saveDraft) return;
    const move = pending;
    leavingRef.current = move.kind !== 'custom';
    setSaving(true);
    let saved = false;
    try {
      saved = (await saveDraft()) !== false;
    } catch {
      saved = false;
    }
    setSaving(false);
    setPending(null);
    if (!saved) {
      leavingRef.current = false;
      if (move.kind === 'back') void silentHistoryGo(1);
      return;
    }
    void leave(move);
  }, [leave, pending, saving]);

  const confirmLeave = React.useCallback(
    (proceed: () => void) => {
      if (!dirty) {
        proceed();
        return;
      }
      setPending({ kind: 'custom', proceed });
    },
    [dirty]
  );

  const dialog = (
    <AlertDialog open={pending !== null} onOpenChange={(open) => (open ? undefined : cancel())}>
      <AlertDialogContent data-testid="unsaved-changes-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={saving} data-testid="unsaved-changes-cancel">
            Cancel
          </AlertDialogCancel>
          <Button
            type="button"
            variant={onSave ? 'outline' : 'danger'}
            disabled={saving}
            onClick={discard}
            data-testid="unsaved-changes-discard"
          >
            Discard
          </Button>
          {onSave ? (
            <Button
              type="button"
              variant="primary"
              disabled={saving}
              onClick={() => void save()}
              data-testid="unsaved-changes-save"
            >
              {saving ? 'Saving…' : 'Save'}
            </Button>
          ) : null}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );

  return { dirty, dialog, asking: pending !== null, confirmLeave };
}
