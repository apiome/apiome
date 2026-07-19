/**
 * Delivery environments for the Authoring shell (UXE-1.2).
 *
 * The managed release model that will own real environments ships with the
 * Release Center (UXE-2.4). Until then this module declares the fixed lane set
 * the shell scopes to, so the selector is real, persistable and keyboard
 * complete without inventing release data it cannot yet read.
 */

/** Identifier of a delivery environment lane. */
export type AuthoringEnvironmentId = 'preview' | 'production';

/** One selectable delivery environment lane. */
export type AuthoringEnvironment = {
  id: AuthoringEnvironmentId;
  /** Short label shown in the selector. */
  label: string;
  /** One line explaining what the lane contains. */
  description: string;
  /**
   * True when content scoped to this lane must not be edited in place.
   * Production is served from an immutable, already-promoted release.
   */
  readOnly: boolean;
};

/** Ordered lanes, least to most privileged. */
export const AUTHORING_ENVIRONMENTS: readonly AuthoringEnvironment[] = [
  {
    id: 'preview',
    label: 'Preview',
    description: 'Draft content and preview deployments.',
    readOnly: false,
  },
  {
    id: 'production',
    label: 'Production',
    description: 'The release currently serving production traffic.',
    readOnly: true,
  },
] as const;

/** Lane selected when a URL carries no environment. */
export const DEFAULT_AUTHORING_ENVIRONMENT_ID: AuthoringEnvironmentId = 'preview';

/**
 * Narrow an arbitrary string to a known lane id.
 *
 * @param value - Candidate id, typically read from a URL.
 * @returns True when `value` names a declared lane.
 */
export function isAuthoringEnvironmentId(value: unknown): value is AuthoringEnvironmentId {
  return (
    typeof value === 'string' &&
    AUTHORING_ENVIRONMENTS.some((environment) => environment.id === value)
  );
}

/**
 * Look up a lane, falling back to the default for unknown or stale ids so a
 * copied URL from a future build degrades instead of erroring.
 *
 * @param id - Candidate lane id.
 * @returns The matching lane, or the default lane.
 */
export function getAuthoringEnvironment(id: unknown): AuthoringEnvironment {
  const match = AUTHORING_ENVIRONMENTS.find((environment) => environment.id === id);
  if (match) return match;
  return AUTHORING_ENVIRONMENTS.find(
    (environment) => environment.id === DEFAULT_AUTHORING_ENVIRONMENT_ID
  )!;
}
