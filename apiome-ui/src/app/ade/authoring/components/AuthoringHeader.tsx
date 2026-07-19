'use client';

/**
 * Persistent scope header for the Authoring shell (UXE-1.2).
 *
 * Carries the Tenant → Project → Version → Environment selectors, the shell's
 * status badges and the command palette trigger. It is rendered once by the
 * layout, so every surface inherits the same scope controls instead of
 * building its own.
 */

import * as React from 'react';
import { AUTHORING_ENVIRONMENTS } from '@lib/authoring/environments';
import {
  authoringHeaderClass,
  authoringCommandTriggerClass,
  authoringKbdClass,
} from '../authoringClasses';
import { useAuthoring } from '../AuthoringContext';
import AuthoringScopeSelect, { type AuthoringScopeOption } from './AuthoringScopeSelect';
import AuthoringStateBadges from './AuthoringStateBadges';
import { Search } from 'lucide-react';

/** Props for {@link AuthoringHeader}. */
export type AuthoringHeaderProps = {
  /** Opens the command palette. */
  onOpenCommandPalette: () => void;
};

/**
 * Render the scope header.
 *
 * @param props - Callback used by the command trigger.
 */
export default function AuthoringHeader({ onOpenCommandPalette }: AuthoringHeaderProps) {
  const {
    scope,
    projects,
    versions,
    setProjectId,
    setVersionId,
    setEnvironmentId,
    loading,
    stateBadges,
  } = useAuthoring();

  const projectOptions = React.useMemo<AuthoringScopeOption[]>(
    () => projects.map((project) => ({ value: project.id, label: project.name })),
    [projects]
  );

  const versionOptions = React.useMemo<AuthoringScopeOption[]>(
    () =>
      versions.map((version) => ({
        value: version.id,
        label: version.versionId,
        hint: version.description?.trim() || (version.published ? 'Published' : 'Draft'),
      })),
    [versions]
  );

  const environmentOptions = React.useMemo<AuthoringScopeOption[]>(
    () =>
      AUTHORING_ENVIRONMENTS.map((environment) => ({
        value: environment.id,
        label: environment.label,
        hint: environment.description,
      })),
    []
  );

  return (
    <div className={authoringHeaderClass}>
      <AuthoringScopeSelect
        label="Project"
        icon="FolderOpen"
        options={projectOptions}
        value={scope.projectId ?? ''}
        onValueChange={setProjectId}
        placeholder="Select project…"
        emptyMessage={loading ? 'Loading projects…' : 'No projects available'}
      />
      <AuthoringScopeSelect
        label="Version"
        icon="GitBranch"
        options={versionOptions}
        value={scope.versionId ?? ''}
        onValueChange={setVersionId}
        placeholder="Select version…"
        emptyMessage={
          !scope.projectId
            ? 'Select a project first'
            : loading
              ? 'Loading versions…'
              : 'No versions available'
        }
        disabled={!scope.projectId}
      />
      <AuthoringScopeSelect
        label="Environment"
        icon="Globe"
        options={environmentOptions}
        value={scope.environmentId}
        onValueChange={(value) =>
          setEnvironmentId(value as (typeof AUTHORING_ENVIRONMENTS)[number]['id'])
        }
        placeholder="Select environment…"
        emptyMessage="No environments available"
      />

      <button
        type="button"
        onClick={onOpenCommandPalette}
        className={authoringCommandTriggerClass}
        aria-keyshortcuts="Meta+K Control+K"
      >
        <Search className="h-4 w-4" aria-hidden="true" />
        Search or jump to…
        <kbd className={authoringKbdClass}>⌘K</kbd>
      </button>

      <AuthoringStateBadges badges={stateBadges} className="ml-auto" />
    </div>
  );
}
