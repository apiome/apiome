'use client';

/**
 * Status badge strip for the Authoring shell (UXE-1.2).
 *
 * Renders the badges derived by `resolveAuthoringStateBadges` as one live
 * region. Each badge carries an icon and a visible label, and its explanatory
 * sentence is attached as the accessible description, so the state is
 * understandable without color and without hovering.
 */

import * as React from 'react';
import { hasUrgentAuthoringState, type AuthoringStateBadge } from '@lib/authoring/state-badges';
import { cn } from '@lib/utils';
import { authoringBadgeBaseClass, authoringBadgeToneClass } from '../authoringClasses';
import AuthoringIcon from './AuthoringIcon';

/** Props for {@link AuthoringStateBadges}. */
export type AuthoringStateBadgesProps = {
  badges: readonly AuthoringStateBadge[];
  className?: string;
};

/**
 * Render the current shell states.
 *
 * @param props - Badges to render and optional extra classes.
 */
export default function AuthoringStateBadges({ badges, className }: AuthoringStateBadgesProps) {
  // Blocking states interrupt; routine ones are announced when the user
  // reaches them, so a Saving/Saved cycle never talks over the viewer.
  const politeness = hasUrgentAuthoringState(badges) ? 'assertive' : 'polite';

  return (
    <div
      className={cn('flex flex-wrap items-center gap-2', className)}
      role="status"
      aria-live={politeness}
      aria-label="Authoring status"
    >
      {badges.map((badge) => {
        const descriptionId = `authoring-state-${badge.id}-description`;
        return (
          <span
            key={badge.id}
            className={cn(authoringBadgeBaseClass, authoringBadgeToneClass[badge.tone])}
            data-state-id={badge.id}
            aria-describedby={descriptionId}
          >
            <AuthoringIcon name={badge.icon} className="h-3.5 w-3.5 shrink-0" />
            {badge.label}
            <span id={descriptionId} className="sr-only">
              {badge.description}
            </span>
          </span>
        );
      })}
    </div>
  );
}
