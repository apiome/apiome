import { toast as sonnerToast } from 'sonner';

import { voiceFailure } from '../../../../lib/copy-voice';

/**
 * toast — the app's toast call, with the DESIGN.md §10 error voice built in (HIVE-10.4, #5340).
 *
 * The same API as sonner's `toast` (it *is* sonner's `toast`, with every helper copied over),
 * except for one thing: `toast.error('Could not create tag')` reaches the screen as
 * "Could not create tag — try again." Passed through untouched: a failure that already
 * names a next action ("Could not sign out. Try again."), a message that explains a rule
 * rather than a failure ("System primitives cannot be edited" — retrying cannot help), and
 * any message that is not a plain string (a React node is the caller's own composition).
 * The judgement is `voiceFailure` in `lib/copy-voice.ts`.
 *
 * Import it instead of sonner's:
 *
 * ```ts
 * import { toast } from '@/app/components/ui/toast';
 * toast.error(err instanceof Error ? err.message : 'Could not create branch');
 * ```
 *
 * `tests/copy-voice-gate.test.ts` fails the build if a component imports `toast` from
 * `sonner` directly, so a new call site cannot bypass the rule by accident.
 */

/** sonner's `toast`, which is both a function and a namespace of helpers. */
type SonnerToast = typeof sonnerToast;

/**
 * Raise an error toast whose message names a next action.
 *
 * @param message What happened. A string reporting a failure gains a next action if it
 *   lacks one; anything else is passed through.
 * @param rest sonner's per-toast options (description, action, id, duration …), if any.
 * @returns The toast id, as sonner returns it.
 */
const error = (
  message: Parameters<SonnerToast['error']>[0],
  ...rest: [data?: Parameters<SonnerToast['error']>[1]]
): ReturnType<SonnerToast['error']> =>
  sonnerToast.error(
    typeof message === 'string' ? voiceFailure(message) : message,
    // Forwarded verbatim, so a call without options reaches sonner without one.
    ...rest
  );

/**
 * The app toast: sonner's callable `toast`, its helpers, and the voiced {@link error}.
 */
export const toast: SonnerToast = Object.assign(
  (...args: Parameters<SonnerToast>) => sonnerToast(...args),
  sonnerToast,
  { error }
);
