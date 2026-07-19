/**
 * Command palette model for the Authoring shell (UXE-1.2).
 *
 * Builds the searchable set of routes, scope switches and actions offered by
 * `Cmd/Ctrl+K`. Kept free of React so the command set — the part with the
 * entitlement and scope rules in it — is unit-testable on its own.
 */

import { buildAuthoringHref, type AuthoringUrlScope } from './scope';
import { AUTHORING_ENVIRONMENTS, type AuthoringEnvironmentId } from './environments';
import {
  AUTHORING_SURFACES,
  isAuthoringSurfaceEntitled,
  type AuthoringSurfaceId,
} from './surfaces';

/** Section a command is listed under. */
export type AuthoringCommandGroup = 'Go to' | 'Project' | 'Version' | 'Environment';

/** What activating a command does. */
export type AuthoringCommandAction =
  | { kind: 'navigate'; href: string }
  | { kind: 'select-project'; projectId: string }
  | { kind: 'select-version'; versionId: string }
  | { kind: 'select-environment'; environmentId: AuthoringEnvironmentId };

/** One entry in the command palette. */
export type AuthoringCommand = {
  /** Stable id, unique across the whole command set. */
  id: string;
  label: string;
  /** Secondary line, e.g. what the destination contains. */
  description?: string;
  group: AuthoringCommandGroup;
  /** Lucide icon name, resolved on the client. */
  icon?: string;
  /**
   * Extra words matched by search but not displayed, e.g. a version's id when
   * the label shows its description.
   */
  keywords?: string[];
  /** True when this command names what is already selected. */
  active?: boolean;
  /**
   * Set when the command cannot be run. The palette still lists it and shows
   * this sentence, so the viewer learns how to get access rather than finding
   * an entry that silently does nothing.
   */
  unavailableReason?: string;
  action: AuthoringCommandAction;
};

/** A project the session can see. */
export type AuthoringProjectOption = {
  id: string;
  name: string;
};

/** A version revision within the selected project. */
export type AuthoringVersionOption = {
  /** Revision record id — what scope stores. */
  id: string;
  /** Human version label, e.g. `1.4.0`. */
  versionId: string;
  description?: string | null;
  published: boolean;
};

/** Everything needed to build the command set. */
export type AuthoringCommandInput = {
  scope: AuthoringUrlScope;
  projects: readonly AuthoringProjectOption[];
  versions: readonly AuthoringVersionOption[];
  entitledFlags: ReadonlySet<string>;
  /** Surface currently displayed, so it can be marked active. */
  activeSurfaceId?: AuthoringSurfaceId;
};

/**
 * Build every command available in the current context.
 *
 * Surface commands are always listed. An unentitled surface keeps its label
 * and carries `unavailableReason` instead of an href, matching the suite
 * dropdown's rule (UXE-1.1) that access is explained rather than hidden.
 *
 * @param input - Current scope, data and entitlements.
 * @returns Ordered commands, grouped by section.
 */
export function buildAuthoringCommands(input: AuthoringCommandInput): AuthoringCommand[] {
  const { scope, projects, versions, entitledFlags, activeSurfaceId } = input;
  const commands: AuthoringCommand[] = [];

  for (const surface of AUTHORING_SURFACES) {
    const entitled = isAuthoringSurfaceEntitled(surface, entitledFlags);
    commands.push({
      id: `surface:${surface.id}`,
      label: surface.label,
      description: surface.description,
      group: 'Go to',
      icon: surface.icon,
      keywords: ['authoring', surface.id],
      active: surface.id === activeSurfaceId,
      unavailableReason: entitled
        ? undefined
        : 'Your plan does not include this area. Ask a tenant admin to enable it.',
      // Scope travels with the navigation so the destination opens on the
      // same project, version and lane the viewer is already looking at.
      action: {
        kind: 'navigate',
        href: buildAuthoringHref(surface.path, scope),
      },
    });
  }

  for (const project of projects) {
    commands.push({
      id: `project:${project.id}`,
      label: project.name,
      description: 'Switch project',
      group: 'Project',
      icon: 'FolderOpen',
      active: project.id === scope.projectId,
      action: { kind: 'select-project', projectId: project.id },
    });
  }

  for (const version of versions) {
    commands.push({
      id: `version:${version.id}`,
      label: version.versionId,
      description: version.description?.trim() || (version.published ? 'Published' : 'Draft'),
      group: 'Version',
      icon: 'GitBranch',
      keywords: [version.published ? 'published' : 'draft'],
      active: version.id === scope.versionId,
      action: { kind: 'select-version', versionId: version.id },
    });
  }

  for (const environment of AUTHORING_ENVIRONMENTS) {
    commands.push({
      id: `environment:${environment.id}`,
      label: environment.label,
      description: environment.description,
      group: 'Environment',
      icon: 'Globe',
      active: environment.id === scope.environmentId,
      action: { kind: 'select-environment', environmentId: environment.id },
    });
  }

  return commands;
}

/**
 * Normalize text for matching: lowercase, collapsed whitespace.
 *
 * @param value - Raw text.
 */
function normalize(value: string): string {
  return value.toLowerCase().replace(/\s+/g, ' ').trim();
}

/**
 * Score one command against a query.
 *
 * Ranking favors, in order: a label prefix match, a label substring, then a
 * match anywhere in the description or keywords. Every term must match
 * something, so typing more words narrows rather than widens the list.
 *
 * @param command - Command to score.
 * @param terms - Normalized query terms.
 * @returns A score, or `0` when the command does not match.
 */
function scoreCommand(command: AuthoringCommand, terms: readonly string[]): number {
  const label = normalize(command.label);
  const haystack = normalize(
    [command.label, command.description ?? '', command.group, ...(command.keywords ?? [])].join(' ')
  );

  let score = 0;
  for (const term of terms) {
    if (label.startsWith(term)) score += 3;
    else if (label.includes(term)) score += 2;
    else if (haystack.includes(term)) score += 1;
    else return 0;
  }
  return score;
}

/**
 * Filter and rank commands for a query.
 *
 * An empty query returns everything in declaration order, so the palette opens
 * as a browsable menu rather than a blank prompt.
 *
 * @param commands - Commands to search.
 * @param query - Raw text typed by the viewer.
 * @returns Matching commands, best match first. Ties keep declaration order.
 */
export function filterAuthoringCommands(
  commands: readonly AuthoringCommand[],
  query: string
): AuthoringCommand[] {
  const terms = normalize(query).split(' ').filter(Boolean);
  if (terms.length === 0) return [...commands];

  return commands
    .map((command, index) => ({
      command,
      index,
      score: scoreCommand(command, terms),
    }))
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((entry) => entry.command);
}

/**
 * Split commands into their sections, preserving group and item order.
 *
 * @param commands - Commands to group, typically already filtered.
 * @returns Non-empty groups in canonical order.
 */
export function groupAuthoringCommands(
  commands: readonly AuthoringCommand[]
): Array<{ group: AuthoringCommandGroup; commands: AuthoringCommand[] }> {
  const order: AuthoringCommandGroup[] = ['Go to', 'Project', 'Version', 'Environment'];
  return order
    .map((group) => ({
      group,
      commands: commands.filter((command) => command.group === group),
    }))
    .filter((entry) => entry.commands.length > 0);
}
