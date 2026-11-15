/**
 * The presence rule set (COL-4.1, #4525) — `lib/presence.ts`.
 */

import {
  PRESENCE_MAX_AVATARS,
  avatarsToShow,
  canForceTakeover,
  initialsOf,
  lockOn,
  lockSentence,
  lockStanding,
  newSessionId,
  type PresenceLock,
  type PresenceSnapshot,
  type PresenceViewer,
} from '../lib/presence';

const viewer = (id: string, name: string): PresenceViewer => ({ user_id: id, name, views: ['project'], sessions: 1 });
const lock = (over: Partial<PresenceLock> = {}): PresenceLock => ({
  element_key: 'class:1',
  holder_user_id: 'bob',
  holder_name: 'Bob Brown',
  holder_session_id: 'tab-bob',
  acquired_at: '2026-11-14T00:00:00Z',
  expires_at: '2026-11-14T00:01:00Z',
  takeover: null,
  ...over,
});
const snapshot = (locks: PresenceLock[] = []): PresenceSnapshot => ({
  viewers: [],
  locks,
  lost: [],
  server_time: '',
  ttl_seconds: 45,
});

describe('initialsOf', () => {
  it('uses first and last initials, or two letters of one name', () => {
    expect(initialsOf('Alice Anders')).toBe('AA');
    expect(initialsOf('Ada Maria Lovelace')).toBe('AL');
    expect(initialsOf('prince')).toBe('PR');
    expect(initialsOf('   ')).toBe('?');
  });
});

describe('avatarsToShow', () => {
  it('leaves the caller out and collapses the overflow', () => {
    const viewers = ['me', 'a', 'b', 'c', 'd', 'e', 'f'].map((id) => viewer(id, id));
    const { shown, overflow } = avatarsToShow(viewers, 'me');
    expect(shown).toHaveLength(PRESENCE_MAX_AVATARS);
    expect(shown.some((v) => v.user_id === 'me')).toBe(false);
    expect(overflow).toBe(2);
  });
  it('is empty when the caller is alone', () => {
    expect(avatarsToShow([viewer('me', 'Me')], 'me')).toEqual({ shown: [], overflow: 0 });
  });
});

describe('lock standing', () => {
  it('is free, mine, or theirs', () => {
    const snap = snapshot([lock()]);
    expect(lockOn(snap, 'class:1')?.holder_name).toBe('Bob Brown');
    expect(lockStanding(snap, 'class:2', 'tab-alice')).toBe('free');
    expect(lockStanding(snap, 'class:1', 'tab-bob')).toBe('mine');
    expect(lockStanding(snap, 'class:1', 'tab-alice')).toBe('theirs');
  });
});

describe('takeover', () => {
  const asked = lock({
    takeover: { user_id: 'alice', name: 'Alice', requested_at: '2026-11-14T00:00:00Z', can_force_after: '2026-11-14T00:00:15Z' },
  });
  it('may be forced only by the requester, after the grace period', () => {
    const before = Date.parse('2026-11-14T00:00:10Z');
    const after = Date.parse('2026-11-14T00:00:20Z');
    expect(canForceTakeover(asked, 'alice', before)).toBe(false);
    expect(canForceTakeover(asked, 'alice', after)).toBe(true);
    expect(canForceTakeover(asked, 'carol', after)).toBe(false);
    expect(canForceTakeover(lock(), 'alice', after)).toBe(false);
  });
  it('reads as a sentence naming the holder and the asker', () => {
    expect(lockSentence(lock())).toBe('Bob Brown is editing this');
    expect(lockSentence(asked)).toBe('Bob Brown is editing this — Alice asked to take over');
  });
});

describe('newSessionId', () => {
  it('is 8-64 URL-safe characters and unique', () => {
    const a = newSessionId();
    expect(a).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(newSessionId()).not.toBe(a);
  });
});
