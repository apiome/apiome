/**
 * The Sources tab's model (REPO-5.7, #2792): `lib/repository-sources.ts`.
 */

import { describe, test, expect } from '@jest/globals';
import {
  ENTITY_ORIGIN_LABEL,
  entityOrigin,
  filterEntities,
  parseRepositorySourcesReply,
  provenanceSummary,
  sourceLabel,
  type EntityProvenance,
} from '../lib/repository-sources';

const prov = (sourceId: string | null, name: string, carried: string | null = null) => ({
  source_id: sourceId,
  repository_id: 'r',
  repository_full_name: name,
  branch: 'main',
  path: 'openapi.yaml',
  blob_sha: null,
  carried_from_version_id: carried,
});

const ENTITIES: EntityProvenance[] = [
  { kind: 'class', key: 'Invoice', source: prov('s-billing', 'acme/billing') },
  { kind: 'class', key: 'Note', source: null },
  { kind: 'class', key: 'User', source: prov('s-users', 'acme/users', 'v1') },
  { kind: 'path', key: '/invoices', source: prov('s-billing', 'acme/billing') },
  { kind: 'path', key: '/users', source: prov('s-users', 'acme/users', 'v1') },
];

describe('entityOrigin', () => {
  test('imported, carried forward, or not from a repository', () => {
    expect(ENTITIES.map(entityOrigin)).toEqual(['imported', 'unattributed', 'carried', 'imported', 'carried']);
    expect(ENTITY_ORIGIN_LABEL.carried).toBe('Carried forward');
  });
});

describe('sourceLabel', () => {
  test('repository · branch:path, falling back to the repository id', () => {
    expect(sourceLabel(prov('s', 'acme/users'))).toBe('acme/users · main:openapi.yaml');
    expect(
      sourceLabel({ repository_full_name: null, repository_id: 'r-1', branch: 'dev', path: 'a.yaml' }),
    ).toBe('r-1 · dev:a.yaml');
  });
});

describe('filterEntities', () => {
  const keys = (filters: Parameters<typeof filterEntities>[1]) => filterEntities(ENTITIES, filters).map((e) => e.key);

  test('no filters keeps everything in order', () => {
    expect(keys({ source: 'all', kind: 'all', query: '' })).toEqual(['Invoice', 'Note', 'User', '/invoices', '/users']);
  });

  test('by kind, by source, and unattributed only', () => {
    expect(keys({ source: 'all', kind: 'path', query: '' })).toEqual(['/invoices', '/users']);
    expect(keys({ source: 's-users', kind: 'all', query: '' })).toEqual(['User', '/users']);
    expect(keys({ source: 'none', kind: 'all', query: '' })).toEqual(['Note']);
  });

  test('search matches the name and the source, case-insensitively', () => {
    expect(keys({ source: 'all', kind: 'all', query: 'INVOICE' })).toEqual(['Invoice', '/invoices']);
    expect(keys({ source: 'all', kind: 'class', query: 'acme/users' })).toEqual(['User']);
  });
});

describe('provenanceSummary', () => {
  test('counts the files and the attributed entities', () => {
    expect(
      provenanceSummary({
        sources: [{} as never, {} as never],
        counts: { classes: 3, paths: 2, attributed: 4, unattributed: 1 },
      }),
    ).toBe('2 repository files contribute. 4 of 5 classes and paths come from a repository.');
    expect(
      provenanceSummary({ sources: [{} as never], counts: { classes: 0, paths: 0, attributed: 0, unattributed: 0 } }),
    ).toBe('1 repository file contributes.');
    expect(
      provenanceSummary({ sources: [], counts: { classes: 1, paths: 0, attributed: 0, unattributed: 1 } }),
    ).toBe('No repository file contributes to this project. 0 of 1 classes and paths come from a repository.');
  });
});

describe('parseRepositorySourcesReply', () => {
  test('accepts a reply and rejects anything else', () => {
    const reply = { project_id: 'p', sources: [], entities: [], counts: { classes: 0, paths: 0, attributed: 0, unattributed: 0 }, version: null };
    expect(parseRepositorySourcesReply(reply)).toBe(reply);
    expect(parseRepositorySourcesReply(null)).toBeNull();
    expect(parseRepositorySourcesReply({ success: false, error: 'x' })).toBeNull();
  });
});
