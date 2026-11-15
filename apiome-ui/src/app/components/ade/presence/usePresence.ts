'use client';

/**
 * A tab's presence in a project and its element soft locks — COL-4.1 (#4525).
 *
 * The hook announces the tab with a heartbeat every {@link PRESENCE_HEARTBEAT_MS} (which also
 * renews the locks the tab holds and returns everyone else's), and tells apiome-rest the tab is
 * leaving when it unmounts or the page is hidden for good, so avatars and locks clear at once. A
 * tab that vanishes without saying so simply stops heartbeating and its lease lapses — nothing can
 * stay locked. Locks are advisory: a refused `lock` is reported, never enforced on the editor.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  EMPTY_PRESENCE,
  PRESENCE_HEARTBEAT_MS,
  newSessionId,
  type PresenceAction,
  type PresenceSnapshot,
} from '@lib/presence';

/** What {@link usePresence} returns. */
export interface UsePresence {
  /** The latest snapshot (empty until the first heartbeat answers). */
  snapshot: PresenceSnapshot;
  /** This tab's session id. */
  sessionId: string;
  /** Element keys this tab holds. */
  held: string[];
  /** Mark an element as being edited; resolves with an error message when refused, else null. */
  lock: (elementKey: string) => Promise<string | null>;
  /** Release an element this tab holds. */
  unlock: (elementKey: string) => Promise<void>;
  /** Ask the holder to hand an element over; resolves with an error message or null. */
  requestTakeover: (elementKey: string) => Promise<string | null>;
  /** Take an element over once the grace period has passed; resolves with an error message or null. */
  takeOver: (elementKey: string) => Promise<string | null>;
  /** Element keys this tab lost to a takeover since the last {@link dismissLost}. */
  lost: string[];
  /** Clear the takeover notice. */
  dismissLost: () => void;
}

/**
 * Join a project's presence channel.
 *
 * @param projectId - The project, or empty/null for none (the hook then does nothing).
 * @param view - Which view the tab is on (`project`, `studio`, …).
 * @returns The snapshot and the lock actions.
 */
export function usePresence(projectId: string | null | undefined, view = 'project'): UsePresence {
  const [snapshot, setSnapshot] = useState<PresenceSnapshot>(EMPTY_PRESENCE);
  const [held, setHeld] = useState<string[]>([]);
  const [lost, setLost] = useState<string[]>([]);
  const sessionId = useMemo(() => newSessionId(), []);
  const heldRef = useRef<string[]>([]);
  useEffect(() => {
    heldRef.current = held;
  }, [held]);

  const call = useCallback(
    async (action: PresenceAction, extra: Record<string, unknown> = {}) => {
      const res = await fetch(`/api/projects/${encodeURIComponent(projectId ?? '')}/presence`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, session_id: sessionId, view, ...extra }),
        keepalive: action === 'leave',
      });
      const json = (await res.json().catch(() => null)) as (Partial<PresenceSnapshot> & { success?: boolean; error?: string }) | null;
      return { ok: Boolean(res.ok && json?.success), json };
    },
    [projectId, sessionId, view]
  );

  const apply = useCallback((json: Partial<PresenceSnapshot> | null) => {
    if (!json || !Array.isArray(json.viewers) || !Array.isArray(json.locks)) return;
    const next = json as PresenceSnapshot;
    setSnapshot(next);
    if (next.lost.length) {
      setLost((prev) => Array.from(new Set([...prev, ...next.lost])));
      setHeld((prev) => prev.filter((key) => !next.lost.includes(key)));
    }
  }, []);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    const beat = async () => {
      try {
        const { ok, json } = await call('heartbeat', { held: heldRef.current });
        if (!cancelled && ok) apply(json);
      } catch {
        // A missed beat is retried on the next tick; presence is a nicety, never a blocker.
      }
    };
    void beat();
    const timer = window.setInterval(beat, PRESENCE_HEARTBEAT_MS);
    const leave = () => {
      void call('leave').catch(() => undefined);
    };
    window.addEventListener('pagehide', leave);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener('pagehide', leave);
      leave();
    };
  }, [projectId, call, apply]);

  const act = useCallback(
    async (action: PresenceAction, elementKey: string): Promise<string | null> => {
      if (!projectId) return 'No project is open';
      try {
        const { ok, json } = await call(action, { element_key: elementKey });
        if (!ok) return json?.error ?? 'The request failed';
        apply(json);
        return null;
      } catch {
        return 'The request failed';
      }
    },
    [projectId, call, apply]
  );

  const lock = useCallback(
    async (elementKey: string) => {
      const error = await act('lock', elementKey);
      if (!error) setHeld((prev) => (prev.includes(elementKey) ? prev : [...prev, elementKey]));
      return error;
    },
    [act]
  );
  const unlock = useCallback(
    async (elementKey: string) => {
      setHeld((prev) => prev.filter((key) => key !== elementKey));
      await act('unlock', elementKey);
    },
    [act]
  );
  const requestTakeover = useCallback((elementKey: string) => act('request_takeover', elementKey), [act]);
  const takeOver = useCallback(
    async (elementKey: string) => {
      const error = await act('take_over', elementKey);
      if (!error) setHeld((prev) => (prev.includes(elementKey) ? prev : [...prev, elementKey]));
      return error;
    },
    [act]
  );
  const dismissLost = useCallback(() => setLost([]), []);

  return { snapshot, sessionId, held, lock, unlock, requestTakeover, takeOver, lost, dismissLost };
}
