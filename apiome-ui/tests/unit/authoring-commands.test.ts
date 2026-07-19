/**
 * Authoring command palette model (UXE-1.2).
 */

import {
  buildAuthoringCommands,
  filterAuthoringCommands,
  groupAuthoringCommands,
  type AuthoringCommandInput,
} from '../../lib/authoring/commands';
import type { AuthoringUrlScope } from '../../lib/authoring/scope';

const SCOPE: AuthoringUrlScope = {
  projectId: 'proj-1',
  versionId: 'ver-1',
  environmentId: 'preview',
};

const PROJECTS = [
  { id: 'proj-1', name: 'Payments API' },
  { id: 'proj-2', name: 'Billing API' },
];

const VERSIONS = [
  { id: 'ver-1', versionId: '1.0.0', description: 'First cut', published: false },
  { id: 'ver-2', versionId: '2.0.0', description: null, published: true },
];

/**
 * Build commands from the standard fixture.
 *
 * @param overrides - Fields to change.
 */
function build(overrides: Partial<AuthoringCommandInput> = {}) {
  return buildAuthoringCommands({
    scope: SCOPE,
    projects: PROJECTS,
    versions: VERSIONS,
    entitledFlags: new Set(['scribe', 'slate', 'hosted']),
    ...overrides,
  });
}

describe('buildAuthoringCommands', () => {
  it('offers every surface, project, version and environment', () => {
    const commands = build();
    expect(commands.filter((c) => c.group === 'Go to')).toHaveLength(5);
    expect(commands.filter((c) => c.group === 'Project')).toHaveLength(2);
    expect(commands.filter((c) => c.group === 'Version')).toHaveLength(2);
    expect(commands.filter((c) => c.group === 'Environment')).toHaveLength(2);
  });

  it('carries the current scope into every navigation command', () => {
    const scribe = build().find((c) => c.id === 'surface:scribe')!;
    expect(scribe.action).toEqual({
      kind: 'navigate',
      href: '/ade/authoring/scribe?projectId=proj-1&versionId=ver-1',
    });
  });

  it('marks the active surface, project, version and lane', () => {
    const commands = build({ activeSurfaceId: 'overview' });
    const active = commands.filter((c) => c.active).map((c) => c.id);
    expect(active).toEqual([
      'surface:overview',
      'project:proj-1',
      'version:ver-1',
      'environment:preview',
    ]);
  });

  it('lists an unentitled surface with an explanation instead of hiding it', () => {
    const commands = build({ entitledFlags: new Set() });
    const scribe = commands.find((c) => c.id === 'surface:scribe')!;
    expect(scribe.label).toBe('Scribe');
    expect(scribe.unavailableReason).toMatch(/plan does not include/i);
  });

  it('leaves entitled surfaces runnable', () => {
    expect(build().find((c) => c.id === 'surface:slate')!.unavailableReason).toBeUndefined();
  });

  it('describes a version by its publish state when it has no description', () => {
    const commands = build();
    expect(commands.find((c) => c.id === 'version:ver-2')!.description).toBe('Published');
    expect(commands.find((c) => c.id === 'version:ver-1')!.description).toBe('First cut');
  });

  it('gives every command a unique id', () => {
    const ids = build().map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('filterAuthoringCommands', () => {
  it('returns everything for an empty query, so the palette opens browsable', () => {
    const commands = build();
    expect(filterAuthoringCommands(commands, '')).toHaveLength(commands.length);
    expect(filterAuthoringCommands(commands, '   ')).toHaveLength(commands.length);
  });

  it('matches labels case-insensitively', () => {
    const results = filterAuthoringCommands(build(), 'SCRIBE');
    expect(results[0]?.id).toBe('surface:scribe');
  });

  it('ranks a label prefix above a description-only match', () => {
    const results = filterAuthoringCommands(build(), 'releases');
    expect(results[0]?.id).toBe('surface:releases');
  });

  it('requires every term to match, so more words narrow the list', () => {
    const results = filterAuthoringCommands(build(), 'payments billing');
    expect(results).toHaveLength(0);
  });

  it('matches on keywords that are not displayed', () => {
    const results = filterAuthoringCommands(build(), 'published');
    expect(results.map((c) => c.id)).toContain('version:ver-2');
  });

  it('returns nothing for a query that matches nothing', () => {
    expect(filterAuthoringCommands(build(), 'zzzzz')).toHaveLength(0);
  });
});

describe('groupAuthoringCommands', () => {
  it('groups in canonical order', () => {
    expect(groupAuthoringCommands(build()).map((entry) => entry.group)).toEqual([
      'Go to',
      'Project',
      'Version',
      'Environment',
    ]);
  });

  it('drops groups that have no matches', () => {
    const filtered = filterAuthoringCommands(build(), 'payments');
    expect(groupAuthoringCommands(filtered).map((entry) => entry.group)).toEqual(['Project']);
  });
});
