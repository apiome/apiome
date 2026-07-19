/**
 * Impact sheets for publish, rollback and destructive actions (UXE-1.3).
 *
 * §27.2: "Publish and rollback use impact sheets with checks and policy, not
 * generic 'Are you sure?' dialogs. Destructive cache/security actions include
 * scope previews."
 *
 * The difference between the two is enforced here rather than left to each
 * caller's discretion: an impact sheet cannot be constructed without stating
 * what will change, and a high-severity sheet cannot be confirmed until the
 * operator has actually seen and acknowledged it.
 */

import { summarizeAuthoringChecks, type AuthoringCheck } from './checks';
import { mostUrgentAuthoringTone, type AuthoringTone } from './tokens';

/** The action an impact sheet confirms. */
export type AuthoringImpactAction = 'publish' | 'promote' | 'rollback' | 'purge' | 'delete';

/** How hard an action is to undo. Drives the confirmation the sheet demands. */
export type AuthoringImpactSeverity =
  /** Reversible without data loss, e.g. promoting a built release. */
  | 'routine'
  /** Reversible, but visible to end users while it lasts. */
  | 'notable'
  /** Not reversible, or reversible only with loss. */
  | 'irreversible';

/** One consequence of taking the action. */
export type AuthoringImpactEffect = {
  id: string;
  /** What changes, e.g. `docs.example.com`. */
  label: string;
  /** How it changes, e.g. `Serves release r-4821 instead of r-4820`. */
  detail: string;
  tone: AuthoringTone;
  /** Countable scope, e.g. `482 pages`. Shown as the scope preview. */
  scope?: string;
};

/** Everything shown before an operator commits to an action. */
export type AuthoringImpactSheet = {
  action: AuthoringImpactAction;
  severity: AuthoringImpactSeverity;
  /** What is being acted on, e.g. `Release r-4821`. */
  target: string;
  /** Environment the action lands in. */
  environment: string;
  effects: readonly AuthoringImpactEffect[];
  checks: readonly AuthoringCheck[];
  /** Policy sentence that applies, e.g. `Production requires two approvals.` */
  policy?: string;
  /**
   * Exact text the operator must type for an irreversible action.
   * Ignored for other severities — friction is proportional to consequence.
   */
  confirmationPhrase?: string;
};

/** Verb phrasing per action, so the primary button never reads "OK". */
const ACTION_LABELS: Record<AuthoringImpactAction, { title: string; confirm: string }> = {
  publish: { title: 'Publish', confirm: 'Publish' },
  promote: { title: 'Promote to production', confirm: 'Promote' },
  rollback: { title: 'Roll back', confirm: 'Roll back' },
  purge: { title: 'Purge cache', confirm: 'Purge' },
  delete: { title: 'Delete', confirm: 'Delete' },
};

/**
 * Title and confirm-button wording for an action.
 *
 * @param action - The action being confirmed.
 * @returns Sheet title and primary button label.
 */
export function describeAuthoringImpactAction(action: AuthoringImpactAction) {
  return ACTION_LABELS[action];
}

/** Why an impact sheet cannot currently be confirmed. */
export type AuthoringImpactBlock =
  | { reason: 'checks-failed'; message: string }
  | { reason: 'checks-running'; message: string }
  | { reason: 'phrase-required'; message: string }
  | { reason: 'acknowledgement-required'; message: string };

/** Whether the sheet can be confirmed, and why not. */
export type AuthoringImpactGate = {
  canConfirm: boolean;
  /** Present when `canConfirm` is false. */
  block?: AuthoringImpactBlock;
  /** Worst tone across the effects and checks, for the sheet header. */
  tone: AuthoringTone;
};

/** What the operator has done in the sheet so far. */
export type AuthoringImpactAcknowledgement = {
  /** True when an explicit "I understand" control is checked. */
  acknowledged: boolean;
  /** Text typed into the confirmation field, if the sheet demands one. */
  typedPhrase?: string;
};

/**
 * Decide whether an impact sheet may be confirmed.
 *
 * The gates escalate with consequence. Blocking check failures stop everything.
 * Unfinished checks stop everything too — confirming against incomplete
 * evidence is the failure mode the sheet exists to prevent. A `notable` action
 * needs an explicit acknowledgement, and an `irreversible` one needs the target
 * typed out, which is the only friction that reliably interrupts muscle memory.
 *
 * @param sheet - The sheet being confirmed.
 * @param ack - What the operator has acknowledged.
 * @returns Whether confirmation is allowed, the blocking reason, and the tone.
 */
export function gateAuthoringImpact(
  sheet: AuthoringImpactSheet,
  ack: AuthoringImpactAcknowledgement
): AuthoringImpactGate {
  const checkSummary = summarizeAuthoringChecks(sheet.checks);
  const tone = mostUrgentAuthoringTone([
    checkSummary.tone,
    ...sheet.effects.map((effect) => effect.tone),
  ]);

  if (checkSummary.blocked) {
    return {
      canConfirm: false,
      tone,
      block: { reason: 'checks-failed', message: checkSummary.description },
    };
  }

  if (!checkSummary.settled) {
    return {
      canConfirm: false,
      tone,
      block: { reason: 'checks-running', message: checkSummary.description },
    };
  }

  if (sheet.severity === 'irreversible') {
    const expected = sheet.confirmationPhrase ?? sheet.target;
    if ((ack.typedPhrase ?? '').trim() !== expected) {
      return {
        canConfirm: false,
        tone,
        block: {
          reason: 'phrase-required',
          message: `Type ${expected} to confirm this cannot be undone.`,
        },
      };
    }
    return { canConfirm: true, tone };
  }

  if (sheet.severity === 'notable' && !ack.acknowledged) {
    return {
      canConfirm: false,
      tone,
      block: {
        reason: 'acknowledgement-required',
        message: 'Confirm you have reviewed the impact below.',
      },
    };
  }

  return { canConfirm: true, tone };
}

/**
 * Summarise an impact sheet in one sentence.
 *
 * Announced when the sheet opens, so the consequence is heard before the
 * controls are reached rather than discovered by tabbing through them.
 *
 * @param sheet - The sheet being opened.
 * @returns A sentence naming the action, target, environment and scope.
 */
export function summarizeAuthoringImpact(sheet: AuthoringImpactSheet): string {
  const { title } = describeAuthoringImpactAction(sheet.action);
  const scopes = sheet.effects
    .map((effect) => effect.scope)
    .filter((scope): scope is string => Boolean(scope));

  const scopeText = scopes.length > 0 ? ` Affects ${scopes.join(', ')}.` : '';
  const severityText =
    sheet.severity === 'irreversible' ? ' This cannot be undone.' : '';

  return `${title} ${sheet.target} in ${sheet.environment}.${scopeText}${severityText}`;
}
