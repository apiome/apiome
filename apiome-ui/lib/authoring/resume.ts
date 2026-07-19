/**
 * Resume behavior for the Authoring shell (UXE-1.2).
 *
 * Remembers the last surface and scope a viewer worked in, per tenant, so
 * entering Authoring with no scope in the URL lands them back where they were
 * instead of on an empty picker.
 *
 * Entries are stored per tenant and validated on read. A stored scope is a
 * *hint*, never an authorization: the shell still resolves the projects the
 * session can see, so a stale entry pointing at a project the viewer lost
 * access to simply fails to match and is ignored.
 */

import {
  DEFAULT_AUTHORING_ENVIRONMENT_ID,
  isAuthoringEnvironmentId,
  type AuthoringEnvironmentId,
} from './environments';
import { getAuthoringSurface, type AuthoringSurfaceId } from './surfaces';

/** Storage key prefix; the tenant id is appended. */
const STORAGE_KEY_PREFIX = 'authoring.resume';

/** A remembered Authoring session. */
export type AuthoringResumeEntry = {
  surfaceId: AuthoringSurfaceId;
  projectId: string;
  versionId: string;
  environmentId: AuthoringEnvironmentId;
  /** Epoch milliseconds when the entry was written. */
  updatedAt: number;
};

/**
 * Build the per-tenant storage key.
 *
 * @param tenantId - Tenant the entry belongs to.
 */
function storageKey(tenantId: string): string {
  return `${STORAGE_KEY_PREFIX}.${tenantId}`;
}

/**
 * True when `value` is a usable entry.
 *
 * Unknown surfaces and environments are rejected rather than coerced, because
 * a downgraded build should forget an entry it cannot honor instead of
 * silently sending the viewer somewhere else.
 *
 * @param value - Parsed storage payload.
 */
function isResumeEntry(value: unknown): value is AuthoringResumeEntry {
  if (!value || typeof value !== 'object') return false;
  const entry = value as Partial<AuthoringResumeEntry>;
  return (
    typeof entry.surfaceId === 'string' &&
    Boolean(getAuthoringSurface(entry.surfaceId)) &&
    typeof entry.projectId === 'string' &&
    entry.projectId.length > 0 &&
    typeof entry.versionId === 'string' &&
    entry.versionId.length > 0 &&
    isAuthoringEnvironmentId(entry.environmentId) &&
    typeof entry.updatedAt === 'number' &&
    Number.isFinite(entry.updatedAt)
  );
}

/**
 * Read the remembered session for a tenant.
 *
 * @param tenantId - Tenant to read for; `null` on a tenant-less session.
 * @returns The entry, or `null` when absent, unreadable or invalid.
 */
export function readAuthoringResume(tenantId: string | null): AuthoringResumeEntry | null {
  if (!tenantId || typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(storageKey(tenantId));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isResumeEntry(parsed) ? parsed : null;
  } catch {
    // Private-mode storage denials and corrupt payloads both mean "no resume".
    return null;
  }
}

/**
 * Remember a session for a tenant.
 *
 * Incomplete scopes are not stored: resuming into a project with no version
 * would land on the same empty picker the feature exists to avoid.
 *
 * @param tenantId - Tenant the entry belongs to.
 * @param entry - Session to remember, without its timestamp.
 * @param now - Epoch milliseconds to stamp; injectable for tests.
 * @returns The stored entry, or `null` when nothing was stored.
 */
export function writeAuthoringResume(
  tenantId: string | null,
  entry: Omit<AuthoringResumeEntry, 'updatedAt'>,
  now: number = Date.now()
): AuthoringResumeEntry | null {
  if (!tenantId || typeof window === 'undefined') return null;
  const candidate: AuthoringResumeEntry = { ...entry, updatedAt: now };
  if (!isResumeEntry(candidate)) return null;
  try {
    window.localStorage.setItem(storageKey(tenantId), JSON.stringify(candidate));
    return candidate;
  } catch {
    // Storage is a convenience here; failing to persist must not break the shell.
    return null;
  }
}

/**
 * Forget the remembered session for a tenant.
 *
 * @param tenantId - Tenant to clear.
 */
export function clearAuthoringResume(tenantId: string | null): void {
  if (!tenantId || typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(storageKey(tenantId));
  } catch {
    /* ignore */
  }
}

/**
 * Default environment for a resume entry that predates the lane it names.
 *
 * @returns The default lane id.
 */
export function defaultResumeEnvironment(): AuthoringEnvironmentId {
  return DEFAULT_AUTHORING_ENVIRONMENT_ID;
}
