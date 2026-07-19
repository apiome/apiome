'use client';

/**
 * Secondary navigation for the Authoring shell (UXE-1.2).
 *
 * Every destination link carries the current scope, so moving between surfaces
 * keeps the same project, version and environment — the behavior that lets a
 * viewer follow a signal from Overview into Releases without re-selecting
 * anything.
 */

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  AUTHORING_SURFACES,
  isAuthoringSurfaceActive,
  isAuthoringSurfaceEntitled,
} from '@lib/authoring/surfaces';
import { buildAuthoringHref } from '@lib/authoring/scope';
import { cn } from '@lib/utils';
import {
  authoringNavClass,
  authoringNavItemActiveClass,
  authoringNavItemClass,
  authoringNavItemLockedClass,
} from '../authoringClasses';
import { useAuthoring } from '../AuthoringContext';
import AuthoringIcon from './AuthoringIcon';

/**
 * Render the Authoring destination bar.
 */
export default function AuthoringSecondaryNav() {
  const pathname = usePathname();
  const { scope, entitledFlags } = useAuthoring();

  return (
    <nav className={authoringNavClass} aria-label="Authoring sections">
      {AUTHORING_SURFACES.map((surface) => {
        const active = isAuthoringSurfaceActive(surface, pathname);
        const entitled = isAuthoringSurfaceEntitled(surface, entitledFlags);

        const content = (
          <>
            <AuthoringIcon name={surface.icon} className="h-4 w-4 shrink-0" />
            {surface.label}
          </>
        );

        /*
         * An unentitled destination is announced and explained but never
         * linked, so no unreachable URL is offered (UXE-1.1).
         *
         * The explanation is a real (visually hidden) element bound with
         * `aria-describedby`, not a `title`. A tooltip needs a pointer to
         * reveal it and is announced inconsistently, so a keyboard or
         * screen-reader user would get no explanation at all.
         */
        if (!entitled) {
          const explanationId = `authoring-nav-${surface.id}-locked`;
          return (
            <span
              key={surface.id}
              className={cn(authoringNavItemClass, authoringNavItemLockedClass)}
              role="link"
              aria-disabled="true"
              // Kept in the tab order so the explanation is actually reachable.
              tabIndex={0}
              aria-describedby={explanationId}
            >
              {content}
              <span id={explanationId} className="sr-only">
                {surface.label} is not included in your plan. Ask a tenant admin to enable it.
              </span>
            </span>
          );
        }

        return (
          <Link
            key={surface.id}
            href={buildAuthoringHref(surface.path, scope)}
            className={cn(authoringNavItemClass, active && authoringNavItemActiveClass)}
            aria-current={active ? 'page' : undefined}
          >
            {content}
          </Link>
        );
      })}
    </nav>
  );
}
