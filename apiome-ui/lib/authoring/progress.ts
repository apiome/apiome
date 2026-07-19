/**
 * Named build and deploy phases (UXE-1.3).
 *
 * §27.2 is explicit that progress must name the active phase — "Rendering 482
 * pages", not a nameless spinner. A phase list is therefore data with labels
 * and detail, and the renderer never invents its own wording.
 *
 * The summary produced here is also what an assistive-technology user hears,
 * so it must stay understandable with animation disabled (§27.3).
 */

import type { AuthoringTone } from './tokens';

/** State of one phase in a multi-step operation. */
export type AuthoringPhaseStatus = 'pending' | 'active' | 'complete' | 'failed' | 'skipped';

/** One named phase. */
export type AuthoringProgressPhase = {
  id: string;
  /** Verb phrase naming the work, e.g. `Rendering pages`. */
  label: string;
  /** Live quantity for the active phase, e.g. `482 of 640 pages`. */
  detail?: string;
  status: AuthoringPhaseStatus;
};

const PHASE_STATUS: Record<AuthoringPhaseStatus, { label: string; tone: AuthoringTone; icon: string }> =
  {
    pending: { label: 'Not started', tone: 'neutral', icon: 'Circle' },
    active: { label: 'In progress', tone: 'info', icon: 'LoaderCircle' },
    complete: { label: 'Complete', tone: 'success', icon: 'Check' },
    failed: { label: 'Failed', tone: 'danger', icon: 'X' },
    skipped: { label: 'Skipped', tone: 'neutral', icon: 'MinusCircle' },
  };

/**
 * Describe a phase status.
 *
 * @param status - Phase status.
 * @returns Its label, tone and icon name.
 */
export function describeAuthoringPhaseStatus(status: AuthoringPhaseStatus) {
  return PHASE_STATUS[status];
}

/**
 * The canonical Slate build phases from §27.2.
 *
 * Exported as a template so build views start from the same vocabulary; a
 * caller overrides `detail` and `status` from live data.
 */
export const AUTHORING_BUILD_PHASES: readonly AuthoringProgressPhase[] = [
  { id: 'resolve', label: 'Resolving sources', status: 'pending' },
  { id: 'validate', label: 'Validating contracts', status: 'pending' },
  { id: 'render', label: 'Rendering pages', status: 'pending' },
  { id: 'upload', label: 'Uploading assets', status: 'pending' },
  { id: 'activate', label: 'Activating edge release', status: 'pending' },
] as const;

/** Aggregate view of a phase list. */
export type AuthoringProgressSummary = {
  total: number;
  /** Phases that finished, successfully or by being skipped. */
  finished: number;
  /** Integer percent complete, 0–100. */
  percent: number;
  /** The phase currently running, if any. */
  activePhase?: AuthoringProgressPhase;
  /** The phase that failed, if any. */
  failedPhase?: AuthoringProgressPhase;
  /** True once no phase is pending or active. */
  done: boolean;
  tone: AuthoringTone;
  /** Sentence to announce, e.g. `Step 3 of 5: Rendering pages, 482 of 640 pages.` */
  announcement: string;
};

/**
 * Summarise a phase list.
 *
 * Percent is derived from finished phases rather than from the active one, so
 * the bar never reports progress a phase has not actually made. A failure stops
 * the count where it happened instead of advancing to completion.
 *
 * @param phases - Ordered phases. May be empty.
 * @returns Counts, the active or failed phase, and the sentence to announce.
 */
export function summarizeAuthoringProgress(
  phases: readonly AuthoringProgressPhase[]
): AuthoringProgressSummary {
  const total = phases.length;
  const finished = phases.filter(
    (phase) => phase.status === 'complete' || phase.status === 'skipped'
  ).length;
  const activePhase = phases.find((phase) => phase.status === 'active');
  const failedPhase = phases.find((phase) => phase.status === 'failed');
  // An empty list is not "done" — there was never anything to finish, and
  // reporting completion for it would let a build that produced no phases at
  // all render as a successful one.
  const done =
    total > 0 && !activePhase && !phases.some((phase) => phase.status === 'pending');
  const percent = total === 0 ? 0 : Math.round((finished / total) * 100);

  let tone: AuthoringTone = 'neutral';
  if (failedPhase) tone = 'danger';
  else if (activePhase) tone = 'info';
  else if (done && total > 0) tone = 'success';

  let announcement: string;
  if (total === 0) {
    announcement = 'No phases to report.';
  } else if (failedPhase) {
    const step = phases.indexOf(failedPhase) + 1;
    announcement = `Failed at step ${step} of ${total}: ${failedPhase.label}.${
      failedPhase.detail ? ` ${failedPhase.detail}.` : ''
    }`;
  } else if (activePhase) {
    const step = phases.indexOf(activePhase) + 1;
    announcement = `Step ${step} of ${total}: ${activePhase.label}.${
      activePhase.detail ? ` ${activePhase.detail}.` : ''
    }`;
  } else if (done) {
    announcement = `All ${total} phases complete.`;
  } else {
    announcement = `Not started. ${total} phases queued.`;
  }

  return { total, finished, percent, activePhase, failedPhase, done, tone, announcement };
}
