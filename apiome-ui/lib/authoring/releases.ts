/**
 * Release states and the promote/rollback contract (UXE-1.3).
 *
 * §28.3 enumerates the release lifecycle and its one non-obvious rule:
 * **promotion changes routing to an already built artifact; it does not
 * rebuild.** Encoding that here means the Release Center (UXE-2.4) and any
 * other surface that shows a release cannot invent a different lifecycle.
 */

import type { AuthoringTone } from './tokens';

/** Lifecycle state of an immutable release. */
export type AuthoringReleaseStatus =
  | 'queued'
  | 'building'
  /** Built and verified; can be promoted. */
  | 'ready'
  /** Built, but held for human approval. */
  | 'review'
  /** Currently serving traffic in its environment. */
  | 'active'
  /** Was active; replaced by a newer release. */
  | 'superseded'
  | 'failed'
  /** Was active; deliberately reverted away from. */
  | 'rolled-back';

/** Deployment lane a release belongs to. */
export type AuthoringReleaseEnvironment = 'preview' | 'production';

/** How a release status is presented. */
export type AuthoringReleaseDescriptor = {
  status: AuthoringReleaseStatus;
  label: string;
  /** Sentence explaining the state and what can be done next. */
  description: string;
  tone: AuthoringTone;
  icon: string;
  /** True when the release is still changing and the row should poll. */
  transient: boolean;
};

const RELEASES: Record<AuthoringReleaseStatus, AuthoringReleaseDescriptor> = {
  queued: {
    status: 'queued',
    label: 'Queued',
    description: 'Waiting for a build worker. Nothing has been rendered yet.',
    tone: 'neutral',
    icon: 'Clock',
    transient: true,
  },
  building: {
    status: 'building',
    label: 'Building',
    description: 'Rendering and uploading the release artifact.',
    tone: 'info',
    icon: 'LoaderCircle',
    transient: true,
  },
  ready: {
    status: 'ready',
    label: 'Ready',
    description: 'Built and checked. It can be promoted without rebuilding.',
    tone: 'success',
    icon: 'CircleCheck',
    transient: false,
  },
  review: {
    status: 'review',
    label: 'Awaiting review',
    description: 'Built, but policy requires an approval before it can be promoted.',
    tone: 'warning',
    icon: 'UserCheck',
    transient: false,
  },
  active: {
    status: 'active',
    label: 'Active',
    description: 'Serving traffic in this environment.',
    tone: 'success',
    icon: 'Rocket',
    transient: false,
  },
  superseded: {
    status: 'superseded',
    label: 'Superseded',
    description: 'A newer release replaced it. The artifact is retained and can be rolled back to.',
    tone: 'neutral',
    icon: 'History',
    transient: false,
  },
  failed: {
    status: 'failed',
    label: 'Failed',
    description: 'The build did not complete. Logs and the failing phase are available.',
    tone: 'danger',
    icon: 'TriangleAlert',
    transient: false,
  },
  'rolled-back': {
    status: 'rolled-back',
    label: 'Rolled back',
    description: 'Traffic was moved away from this release. It can be promoted again.',
    tone: 'warning',
    icon: 'Undo2',
    transient: false,
  },
};

/**
 * Describe a release status.
 *
 * @param status - Release status.
 * @returns Its label, explanation, tone, icon and whether it is still moving.
 */
export function describeAuthoringRelease(
  status: AuthoringReleaseStatus
): AuthoringReleaseDescriptor {
  return RELEASES[status];
}

/**
 * True when a release can be promoted to production.
 *
 * Promotion is a routing change over an existing artifact, so it requires a
 * built one: queued, building and failed releases have nothing to route to.
 * `review` is excluded because approval is the gate, and an already `active`
 * release has nowhere to be promoted.
 *
 * @param status - Release status.
 */
export function canPromoteAuthoringRelease(status: AuthoringReleaseStatus): boolean {
  return status === 'ready' || status === 'superseded' || status === 'rolled-back';
}

/**
 * True when traffic can be rolled back away from a release.
 *
 * Only the release currently serving traffic can be rolled back; every other
 * state is either not serving or has already been moved away from.
 *
 * @param status - Release status.
 */
export function canRollbackAuthoringRelease(status: AuthoringReleaseStatus): boolean {
  return status === 'active';
}

/**
 * True when a release row should keep polling for a status change.
 *
 * @param status - Release status.
 */
export function isAuthoringReleaseTransient(status: AuthoringReleaseStatus): boolean {
  return RELEASES[status].transient;
}
