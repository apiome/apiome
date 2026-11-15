/**
 * Project presence and element soft locks — COL-4.1 (#4525): the shapes apiome-rest answers with and
 * the pure rules the avatars and lock notices are drawn from.
 *
 * Locks are advisory: they inform and ask, they never deny a write. Everything here is a pure
 * function of a snapshot, so the components stay thin and the rules are unit-tested.
 */

/** One person with the project open (their tabs collapsed into one avatar). */
export interface PresenceViewer {
  user_id: string;
  name: string;
  views: string[];
  sessions: number;
}

/** A pending request to take a lock over. */
export interface PresenceTakeover {
  user_id: string | null;
  name: string | null;
  requested_at: string;
  can_force_after: string;
}

/** A live advisory lock on one element. */
export interface PresenceLock {
  element_key: string;
  holder_user_id: string;
  holder_name: string;
  holder_session_id: string;
  acquired_at: string;
  expires_at: string;
  takeover: PresenceTakeover | null;
}

/** What apiome-rest answers every presence call with. */
export interface PresenceSnapshot {
  viewers: PresenceViewer[];
  locks: PresenceLock[];
  /** Keys this tab claimed to hold that another tab now holds — the takeover notice. */
  lost: string[];
  server_time: string;
  ttl_seconds: number;
}

/** The lock actions the BFF route accepts. */
export type PresenceAction = 'heartbeat' | 'leave' | 'lock' | 'unlock' | 'request_takeover' | 'take_over';

/** An empty snapshot, for before the first heartbeat answers. */
export const EMPTY_PRESENCE: PresenceSnapshot = {
  viewers: [],
  locks: [],
  lost: [],
  server_time: '',
  ttl_seconds: 45,
};

/** Milliseconds between heartbeats; comfortably more than twice per `ttl_seconds` (45 s). */
export const PRESENCE_HEARTBEAT_MS = 15_000;

/** Avatars drawn before the rest collapse into a "+N" chip. */
export const PRESENCE_MAX_AVATARS = 4;

/**
 * Initials for an avatar.
 *
 * @param name - A display name.
 * @returns Up to two upper-case letters; `?` for an empty name.
 */
export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const letters = parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0];
  return letters.toUpperCase();
}

/**
 * Split the viewers into the avatars to draw and the count that overflow, putting the caller last
 * (an avatar for oneself is noise when others are present) and excluding them from the count.
 *
 * @param viewers - The snapshot's viewers.
 * @param selfUserId - The signed-in user, or null.
 * @returns The shown viewers (others only) and how many more there are.
 */
export function avatarsToShow(
  viewers: readonly PresenceViewer[],
  selfUserId: string | null
): { shown: PresenceViewer[]; overflow: number } {
  const others = viewers.filter((v) => v.user_id !== selfUserId);
  return { shown: others.slice(0, PRESENCE_MAX_AVATARS), overflow: Math.max(0, others.length - PRESENCE_MAX_AVATARS) };
}

/**
 * The live lock on an element.
 *
 * @param snapshot - The latest snapshot.
 * @param elementKey - `<kind>:<id>`.
 * @returns The lock, or undefined when nobody holds the element.
 */
export function lockOn(snapshot: PresenceSnapshot, elementKey: string): PresenceLock | undefined {
  return snapshot.locks.find((lock) => lock.element_key === elementKey);
}

/** How a lock reads to one tab. */
export type LockStanding = 'free' | 'mine' | 'theirs';

/**
 * Whether an element is free, held by this tab, or held by someone else's tab.
 *
 * @param snapshot - The latest snapshot.
 * @param elementKey - `<kind>:<id>`.
 * @param sessionId - This tab's session id.
 * @returns `free`, `mine`, or `theirs`.
 */
export function lockStanding(snapshot: PresenceSnapshot, elementKey: string, sessionId: string): LockStanding {
  const lock = lockOn(snapshot, elementKey);
  if (!lock) return 'free';
  return lock.holder_session_id === sessionId ? 'mine' : 'theirs';
}

/**
 * Whether the caller's own takeover request has waited out its grace period.
 *
 * @param lock - The lock.
 * @param selfUserId - The signed-in user.
 * @param now - The current time in ms.
 * @returns True when the caller asked and the holder has had the grace period to release.
 */
export function canForceTakeover(lock: PresenceLock, selfUserId: string | null, now: number): boolean {
  if (!lock.takeover || lock.takeover.user_id !== selfUserId) return false;
  return Date.parse(lock.takeover.can_force_after) <= now;
}

/**
 * The sentence a lock adornment shows others.
 *
 * @param lock - The lock.
 * @returns e.g. `Bob is editing this`, plus the request state when one is pending.
 */
export function lockSentence(lock: PresenceLock): string {
  if (lock.takeover) return `${lock.holder_name} is editing this — ${lock.takeover.name ?? 'someone'} asked to take over`;
  return `${lock.holder_name} is editing this`;
}

/**
 * A fresh tab session id (8–64 URL-safe characters, as apiome-rest requires).
 *
 * @returns A random id.
 */
export function newSessionId(): string {
  const cryptoRef = typeof globalThis.crypto !== 'undefined' ? globalThis.crypto : undefined;
  if (cryptoRef && typeof cryptoRef.randomUUID === 'function') return cryptoRef.randomUUID();
  return `tab-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}
