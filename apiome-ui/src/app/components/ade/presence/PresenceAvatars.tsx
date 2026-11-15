'use client';

/**
 * Who is viewing this project — COL-4.1 (#4525).
 *
 * A row of initial avatars for the other people with the project open; the caller is not drawn.
 * Avatars appear and disappear as members open and close the project (the hook's heartbeat).
 */

import * as React from 'react';
import { avatarsToShow, initialsOf, type PresenceSnapshot } from '@lib/presence';

/** Props of {@link PresenceAvatars}. */
export interface PresenceAvatarsProps {
  /** The latest snapshot. */
  snapshot: PresenceSnapshot;
  /** The signed-in user's id, left out of the row. */
  selfUserId: string | null;
}

/**
 * Draw the viewers' avatars, or nothing when nobody else is here.
 *
 * @param props - See {@link PresenceAvatarsProps}.
 * @returns The avatar list, or null.
 */
export function PresenceAvatars({ snapshot, selfUserId }: PresenceAvatarsProps) {
  const { shown, overflow } = avatarsToShow(snapshot.viewers, selfUserId);
  if (shown.length === 0) return null;
  const total = shown.length + overflow;
  return (
    <ul className="presence-avatars" aria-label={`${total} other ${total === 1 ? 'person' : 'people'} viewing this project`}>
      {shown.map((viewer) => (
        <li
          key={viewer.user_id}
          className="presence-avatar"
          title={viewer.views.length ? `${viewer.name} — ${viewer.views.join(', ')}` : viewer.name}
        >
          <span aria-hidden="true">{initialsOf(viewer.name)}</span>
          <span className="sr-only">{viewer.name}</span>
        </li>
      ))}
      {overflow > 0 ? (
        <li className="presence-avatar presence-avatar--more">
          <span aria-hidden="true">+{overflow}</span>
          <span className="sr-only">and {overflow} more</span>
        </li>
      ) : null}
    </ul>
  );
}
