'use client';

/**
 * Authoring Overview (UXE-1.2 scope).
 *
 * The readiness hero, delivery signals and prioritized work queue belong to
 * UXE-2.1 and need release data that does not exist yet. What this ticket owns
 * is the part of Overview that is about the shell itself: resuming the last
 * session, getting to a usable scope, and reaching the other surfaces.
 *
 * Nothing here reports a metric it cannot read — the roadmap's rule against
 * fabricated activity applies to the placeholder as much as to the finished
 * screen.
 */

import * as React from 'react';
import Link from 'next/link';
import {
  AUTHORING_SURFACES,
  getAuthoringSurface,
  isAuthoringSurfaceEntitled,
} from '@lib/authoring/surfaces';
import { buildAuthoringHref, isAuthoringScopeResolved } from '@lib/authoring/scope';
import { getAuthoringEnvironment } from '@lib/authoring/environments';
import { cn } from '@lib/utils';
import { authoringContentClass, authoringPanelClass } from '../authoringClasses';
import { useAuthoring } from '../AuthoringContext';
import AuthoringContextSearch from './AuthoringContextSearch';
import AuthoringIcon from './AuthoringIcon';

/**
 * Render the Overview surface.
 */
export default function AuthoringOverview() {
  const { scope, projects, selectedVersion, environment, entitledFlags, resume, loading } =
    useAuthoring();
  const [query, setQuery] = React.useState('');

  const scoped = isAuthoringScopeResolved(scope);

  // Resuming only helps when the current URL has no scope of its own — a
  // copied link must always win over a remembered one.
  //
  // The remembered project must also still be one the viewer can see. Requiring
  // a match (rather than falling back to the stored id) means a stale entry is
  // never offered as a live link, and a project id the viewer has no access to
  // is never printed on screen.
  const resumeSurface = resume ? getAuthoringSurface(resume.surfaceId) : undefined;
  const resumeProject = resume
    ? projects.find((project) => project.id === resume.projectId)
    : undefined;
  const showResume = Boolean(resume && resumeSurface && resumeProject && !scope.projectId);
  const resumeHref =
    resume && resumeSurface
      ? buildAuthoringHref(resumeSurface.path, {
          projectId: resume.projectId,
          versionId: resume.versionId,
          environmentId: resume.environmentId,
        })
      : '';

  const destinations = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    return AUTHORING_SURFACES.filter((surface) => surface.id !== 'overview').filter(
      (surface) =>
        !needle ||
        surface.label.toLowerCase().includes(needle) ||
        surface.description.toLowerCase().includes(needle)
    );
  }, [query]);

  return (
    <div className={authoringContentClass}>
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">Authoring</h1>
        <p className="text-sm text-gray-600 dark:text-gray-300">
          Content, portals, releases and insights for the selected project version.
        </p>
      </header>

      {showResume ? (
        <section className={authoringPanelClass} aria-labelledby="authoring-resume-heading">
          <h2
            id="authoring-resume-heading"
            className="text-sm font-semibold text-gray-900 dark:text-white"
          >
            Resume last authoring session
          </h2>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
            {resumeProject!.name} · {getAuthoringEnvironment(resume!.environmentId).label} ·{' '}
            {resumeSurface!.label}
          </p>
          <Link
            href={resumeHref}
            className="mt-4 inline-flex items-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500"
          >
            Continue authoring
          </Link>
        </section>
      ) : null}

      {!scoped ? (
        <section className={authoringPanelClass} aria-labelledby="authoring-setup-heading">
          <h2
            id="authoring-setup-heading"
            className="text-sm font-semibold text-gray-900 dark:text-white"
          >
            Choose what to work on
          </h2>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
            {loading
              ? 'Loading your projects…'
              : projects.length === 0
                ? 'No projects are available to you yet. Create a project in Designer, or ask a tenant admin for access.'
                : 'Pick a project and version in the header above. Every Authoring surface follows that selection, and the URL keeps it so you can share exactly what you are looking at.'}
          </p>
        </section>
      ) : (
        <section className={authoringPanelClass} aria-labelledby="authoring-scope-heading">
          <h2
            id="authoring-scope-heading"
            className="text-sm font-semibold text-gray-900 dark:text-white"
          >
            Working on
          </h2>
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
            {projects.find((project) => project.id === scope.projectId)?.name ?? scope.projectId} ·
            version {selectedVersion?.versionId ?? '—'} · {environment.label}
          </p>
        </section>
      )}

      <section className="flex flex-col gap-4" aria-labelledby="authoring-destinations-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2
            id="authoring-destinations-heading"
            className="text-sm font-semibold text-gray-900 dark:text-white"
          >
            Go to
          </h2>
          <AuthoringContextSearch
            value={query}
            onValueChange={setQuery}
            label="Search Authoring destinations"
            placeholder="Search destinations…"
            className="w-full sm:w-72"
          />
        </div>

        {destinations.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            No destinations match “{query}”.
          </p>
        ) : (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {destinations.map((surface) => {
              const entitled = isAuthoringSurfaceEntitled(surface, entitledFlags);
              const body = (
                <>
                  <span className="flex items-center gap-2 font-medium text-gray-900 dark:text-white">
                    <AuthoringIcon name={surface.icon} className="h-4 w-4 shrink-0" />
                    {surface.label}
                  </span>
                  <span className="mt-1 block text-sm text-gray-600 dark:text-gray-300">
                    {entitled
                      ? surface.description
                      : `Not included in your plan. Ask a tenant admin to enable ${surface.label}.`}
                  </span>
                </>
              );

              return (
                <li key={surface.id}>
                  {entitled ? (
                    <Link
                      href={buildAuthoringHref(surface.path, scope)}
                      className={cn(
                        authoringPanelClass,
                        'block transition-colors hover:border-indigo-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 dark:hover:border-indigo-500/50'
                      )}
                    >
                      {body}
                    </Link>
                  ) : (
                    <div className={cn(authoringPanelClass, 'opacity-60')} aria-disabled="true">
                      {body}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
