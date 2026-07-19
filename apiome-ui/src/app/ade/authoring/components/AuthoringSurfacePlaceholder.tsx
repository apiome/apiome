'use client';

/**
 * Placeholder for an Authoring surface whose screens have not shipped (UXE-1.2).
 *
 * The shell exists before the surfaces do. Rendering a placeholder *inside* the
 * shell — rather than leaving the route absent — is what lets scope, navigation
 * and the palette be exercised across all five destinations now, and keeps the
 * suite dropdown from linking to a 404.
 *
 * It states which ticket delivers the surface, and explains an entitlement gap
 * when that is the actual reason the viewer cannot use it.
 */

import * as React from 'react';
import { isAuthoringSurfaceEntitled, type AuthoringSurface } from '@lib/authoring/surfaces';
import { authoringContentClass, authoringPanelClass } from '../authoringClasses';
import { useAuthoring } from '../AuthoringContext';
import AuthoringIcon from './AuthoringIcon';

/** Props for {@link AuthoringSurfacePlaceholder}. */
export type AuthoringSurfacePlaceholderProps = {
  surface: AuthoringSurface;
};

/**
 * Render the "not built yet" state for a surface.
 *
 * @param props - The surface being stood in for.
 */
export default function AuthoringSurfacePlaceholder({ surface }: AuthoringSurfacePlaceholderProps) {
  const { scope, entitledFlags, selectedVersion, environment } = useAuthoring();
  const entitled = isAuthoringSurfaceEntitled(surface, entitledFlags);

  return (
    <div className={authoringContentClass}>
      <section className={authoringPanelClass} aria-labelledby="authoring-placeholder-heading">
        <div className="flex items-start gap-4">
          <span
            className="rounded-lg bg-indigo-50 p-3 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-300"
            aria-hidden="true"
          >
            <AuthoringIcon name={surface.icon} className="h-6 w-6" />
          </span>
          <div className="flex flex-col gap-2">
            <h1
              id="authoring-placeholder-heading"
              className="text-xl font-semibold text-gray-900 dark:text-white"
            >
              {surface.label}
            </h1>
            <p className="text-sm text-gray-600 dark:text-gray-300">{surface.description}</p>

            {entitled ? (
              <p className="text-sm text-gray-600 dark:text-gray-300">
                This workspace is not built yet. It arrives in{' '}
                <span className="font-medium">{surface.plannedIn ?? 'a later release'}</span>. Your
                project, version and environment selection is kept, so it will open on the same
                scope you have now.
              </p>
            ) : (
              <p className="text-sm text-gray-600 dark:text-gray-300">
                Your plan does not include {surface.label}. Ask a tenant admin to enable it.
              </p>
            )}
          </div>
        </div>
      </section>

      <section className={authoringPanelClass} aria-labelledby="authoring-scope-heading">
        <h2
          id="authoring-scope-heading"
          className="text-sm font-semibold text-gray-900 dark:text-white"
        >
          Current scope
        </h2>
        <dl className="mt-3 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Project</dt>
            <dd className="font-medium text-gray-900 dark:text-white">
              {scope.projectId ? scope.projectId : 'Not selected'}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Version</dt>
            <dd className="font-medium text-gray-900 dark:text-white">
              {selectedVersion?.versionId ?? 'Not selected'}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Environment</dt>
            <dd className="font-medium text-gray-900 dark:text-white">{environment.label}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
