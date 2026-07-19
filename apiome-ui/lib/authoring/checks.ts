/**
 * Checks and their summary (UXE-1.3).
 *
 * Publish and rollback surfaces show "checks and policy, not a generic
 * 'Are you sure?' dialog" (§27.2). Both the Release Center and the impact sheet
 * read from this one summary, so a release that reports "2 failed" in a list
 * cannot report something else in the confirmation.
 */

import { mostUrgentAuthoringTone, type AuthoringTone } from './tokens';

/** Outcome of a single check. */
export type AuthoringCheckStatus =
  /** Not started. */
  | 'pending'
  /** In flight. */
  | 'running'
  | 'passed'
  | 'failed'
  /** Deliberately not run, e.g. not applicable to this format. */
  | 'skipped';

/** One check on a release, publish or proposal. */
export type AuthoringCheck = {
  id: string;
  label: string;
  status: AuthoringCheckStatus;
  /** One line of detail, e.g. `3 links unreachable`. */
  detail?: string;
  /**
   * True when a failure must block the action rather than warn about it.
   * A failed advisory check is reported but does not stop a publish.
   */
  blocking: boolean;
  /** Link to logs or evidence for this check. */
  href?: string;
};

/** Tone and icon for each check status. */
const CHECK_STATUS: Record<AuthoringCheckStatus, { label: string; tone: AuthoringTone; icon: string }> =
  {
    pending: { label: 'Pending', tone: 'neutral', icon: 'Circle' },
    running: { label: 'Running', tone: 'info', icon: 'LoaderCircle' },
    passed: { label: 'Passed', tone: 'success', icon: 'Check' },
    failed: { label: 'Failed', tone: 'danger', icon: 'X' },
    skipped: { label: 'Skipped', tone: 'neutral', icon: 'MinusCircle' },
  };

/**
 * Describe a check status.
 *
 * @param status - Check status.
 * @returns Its label, tone and icon name.
 */
export function describeAuthoringCheckStatus(status: AuthoringCheckStatus) {
  return CHECK_STATUS[status];
}

/** Aggregate view of a set of checks. */
export type AuthoringCheckSummary = {
  total: number;
  passed: number;
  failed: number;
  running: number;
  pending: number;
  skipped: number;
  /** True when at least one *blocking* check failed. */
  blocked: boolean;
  /** True while any check is still pending or running. */
  settled: boolean;
  /** Tone of the worst individual check. */
  tone: AuthoringTone;
  /** Short label, e.g. `2 of 7 checks failed`. */
  label: string;
  /** Full sentence for the accessible summary. */
  description: string;
};

/**
 * Summarise a set of checks.
 *
 * The summary never reads calmer than its worst member, and it distinguishes
 * "nothing failed" from "nothing has finished" — a run still in progress must
 * not be mistaken for a clean one.
 *
 * @param checks - Checks to summarise. May be empty.
 * @returns Counts, blocking state and the sentence to announce.
 */
export function summarizeAuthoringChecks(
  checks: readonly AuthoringCheck[]
): AuthoringCheckSummary {
  const count = (status: AuthoringCheckStatus) =>
    checks.filter((check) => check.status === status).length;

  const passed = count('passed');
  const failed = count('failed');
  const running = count('running');
  const pending = count('pending');
  const skipped = count('skipped');
  const total = checks.length;

  const blocked = checks.some((check) => check.blocking && check.status === 'failed');
  const settled = running === 0 && pending === 0;
  const tone = mostUrgentAuthoringTone(
    checks.map((check) => CHECK_STATUS[check.status].tone)
  );

  let label: string;
  let description: string;

  if (total === 0) {
    label = 'No checks';
    description = 'No checks are configured for this action.';
  } else if (!settled) {
    const outstanding = running + pending;
    label = `${outstanding} of ${total} checks running`;
    description = `${outstanding} of ${total} checks have not finished. Results are incomplete.`;
  } else if (failed > 0) {
    label = `${failed} of ${total} checks failed`;
    description = blocked
      ? `${failed} of ${total} checks failed, including a required check. This action is blocked.`
      : `${failed} of ${total} checks failed. None are required, so this action can continue.`;
  } else {
    label = `${passed} of ${total} checks passed`;
    description =
      skipped > 0
        ? `All ${passed} applicable checks passed. ${skipped} were skipped.`
        : `All ${total} checks passed.`;
  }

  return {
    total,
    passed,
    failed,
    running,
    pending,
    skipped,
    blocked,
    settled,
    tone,
    label,
    description,
  };
}
