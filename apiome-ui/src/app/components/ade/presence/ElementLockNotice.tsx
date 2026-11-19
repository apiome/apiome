'use client';

/**
 * The lock adornment for one element — COL-4.1 (#4525).
 *
 * Shown beside an element's editor. It reads the snapshot and says, in order of importance:
 * *you lost this to a takeover* (the previous holder's notice); *someone asked to take this over*
 * (the holder's prompt, with **Keep editing** / **Hand over**); *someone is editing this* (with
 * **Ask to take over**, then **Take over** once the grace period has passed). Nothing here blocks
 * the editor — locks are advisory.
 */

import * as React from 'react';
import { Lock } from 'lucide-react';
import { Button } from '@/app/components/ui/Button';
import { canForceTakeover, lockOn, lockSentence, lockStanding, type PresenceSnapshot } from '@lib/presence';

/** Props of {@link ElementLockNotice}. */
export interface ElementLockNoticeProps {
  /** The latest snapshot. */
  snapshot: PresenceSnapshot;
  /** `<kind>:<id>` of the element. */
  elementKey: string;
  /** This tab's session id. */
  sessionId: string;
  /** The signed-in user's id. */
  selfUserId: string | null;
  /** Keys this tab lost to a takeover. */
  lost: readonly string[];
  /** The current time in ms, from the caller's clock state (keeps this component pure). */
  now: number;
  onRequestTakeover: (elementKey: string) => void;
  onTakeOver: (elementKey: string) => void;
  /** Release the lock (the holder's *Hand over*). */
  onRelease: (elementKey: string) => void;
  /** Dismiss the lost notice. */
  onDismissLost: () => void;
}

/**
 * Draw the lock state of one element, or nothing when it is free and nothing was lost.
 *
 * @param props - See {@link ElementLockNoticeProps}.
 * @returns The notice, or null.
 */
export function ElementLockNotice(props: ElementLockNoticeProps) {
  const { snapshot, elementKey, sessionId, selfUserId, lost, onRequestTakeover, onTakeOver, onRelease, onDismissLost } = props;
  const { now } = props;
  const lock = lockOn(snapshot, elementKey);
  const standing = lockStanding(snapshot, elementKey, sessionId);

  if (lost.includes(elementKey)) {
    return (
      <div className="presence-lock presence-lock--lost" role="status">
        <Lock className="presence-lock__glyph" aria-hidden="true" />
        <span className="presence-lock__text">
          {lock ? `${lock.holder_name} took over this element.` : 'Your lock on this element ended.'} Your unsaved changes are
          still in the editor — copy them before you continue.
        </span>
        <Button type="button" variant="ghost" size="sm" onClick={onDismissLost}>
          Dismiss
        </Button>
      </div>
    );
  }
  if (!lock || standing === 'free') return null;

  if (standing === 'mine') {
    if (!lock.takeover) return null;
    return (
      <div className="presence-lock presence-lock--ask" role="alert">
        <Lock className="presence-lock__glyph" aria-hidden="true" />
        <span className="presence-lock__text">{lock.takeover.name ?? 'Someone'} asked to take over this element.</span>
        <Button type="button" variant="soft" size="sm" onClick={() => onRelease(elementKey)}>
          Hand over
        </Button>
      </div>
    );
  }

  const mine = lock.takeover?.user_id === selfUserId;
  return (
    <div className="presence-lock" role="status">
      <Lock className="presence-lock__glyph" aria-hidden="true" />
      <span className="presence-lock__text">{lockSentence(lock)}</span>
      {mine ? (
        <Button
          type="button"
          variant="soft"
          size="sm"
          disabled={!canForceTakeover(lock, selfUserId, now)} title={!canForceTakeover(lock, selfUserId, now) ? 'Available once the holder has had time to answer your request' : undefined}
          onClick={() => onTakeOver(elementKey)}
        >
          Take over
        </Button>
      ) : lock.takeover ? null : (
        <Button type="button" variant="soft" size="sm" onClick={() => onRequestTakeover(elementKey)}>
          Ask to take over
        </Button>
      )}
    </div>
  );
}
