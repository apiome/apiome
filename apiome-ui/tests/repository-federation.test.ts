/**
 * Multi-repository federation (V2-REPO-8.2, #2806): the planner's federation-off mode, the
 * merge-history report the import sends to apiome-rest, and the switch's database read.
 */

import { describe, expect, jest, test } from '@jest/globals';

jest.mock('../lib/rest-auth', () => ({
  createRestAuthHeaders: jest.fn((user: { user_id?: string }) => ({
    'Content-Type': 'application/json',
    Authorization: `Bearer for-${user.user_id}`,
  })),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { loadProjectFederation, type Queryable } from '../lib/db/repository-merge';
import {
  MAX_REPORTED_CONFLICTS,
  buildFederationReport,
  federationStatusFor,
  postFederationMerge,
  type FederationMergeReport,
} from '../lib/federation-merge-report';
import {
  planRepositoryMerge,
  type MergeSource,
  type ParentEntity,
  type RepositoryMergePlan,
} from '../lib/repository-merge';

const users: MergeSource = {
  sourceId: 'src-users',
  repositoryId: 'repo-users',
  repositoryFullName: 'acme/users',
  branch: 'main',
  path: 'openapi.yaml',
  precedence: 1,
};
const billing: MergeSource = {
  sourceId: 'src-billing',
  repositoryId: 'repo-billing',
  repositoryFullName: 'acme/billing',
  branch: 'main',
  path: 'spec.yaml',
  precedence: 2,
};
const PARENT: ParentEntity[] = [
  { kind: 'class', key: 'User', source: users },
  { kind: 'path', key: '/users', source: users },
  { kind: 'class', key: 'Invoice', source: billing },
  { kind: 'class', key: 'Note', source: null },
];

describe('planRepositoryMerge with the federation switch', () => {
  test('on (the default) merges as REPO-5.7 does', () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['Invoice'],
      incomingPaths: [],
      parentEntities: PARENT,
    });
    expect(plan.mode).toBe('multi-source');
    expect(plan.dropped).toEqual([]);
    expect(plan.carried.map((e) => e.key)).toEqual(['User', '/users', 'Note']);
  });

  test('off replaces the surface and lists what is dropped', () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['Invoice', 'User'],
      incomingPaths: [],
      parentEntities: PARENT,
      federation: false,
    });
    expect(plan.mode).toBe('single-source');
    expect(plan.conflicts).toEqual([]); // no merge, so no collision
    expect(plan.carried).toEqual([]);
    expect(plan.sources).toEqual([billing]);
    expect(plan.dropped.map((e) => `${e.kind}:${e.key}`)).toEqual(['class:User', 'path:/users', 'class:Note']);
  });

  test('off on a single-file project drops nothing', () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['Invoice'],
      incomingPaths: [],
      parentEntities: [{ kind: 'class', key: 'Invoice', source: billing }],
      federation: false,
    });
    expect(plan.dropped).toEqual([]);
  });
});

describe('federationStatusFor', () => {
  const plan = (fields: object) =>
    ({
      mode: 'single-source',
      conflicts: [],
      carried: [],
      superseded: [],
      removed: [],
      sources: [],
      dropped: [],
      ...fields,
    }) as unknown as RepositoryMergePlan;

  test('maps each plan to what is recorded', () => {
    expect(federationStatusFor(plan({ conflicts: [{}] }), { committed: false })).toBe('conflicted');
    expect(federationStatusFor(plan({ mode: 'multi-source' }), { committed: false })).toBeNull();
    expect(federationStatusFor(plan({ mode: 'multi-source' }), { committed: true })).toBe('merged');
    expect(federationStatusFor(plan({ dropped: [{}] }), { committed: true })).toBe('replaced');
    expect(federationStatusFor(plan({}), { committed: true })).toBeNull();
  });
});

describe('buildFederationReport', () => {
  test('a conflict carries both sides, the incoming definition only', () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['User'],
      incomingPaths: ['/users'],
      parentEntities: PARENT,
    });
    const report = buildFederationReport({
      status: 'conflicted',
      plan,
      incoming: billing,
      versionId: 'should-not-be-sent',
      parentVersionId: 'ver-1',
      pathsCarried: 0,
      incomingDefinition: (kind, key) => (kind === 'class' ? { title: key } : null),
    });
    expect(report.versionId).toBeUndefined();
    expect(report.parentVersionId).toBe('ver-1');
    expect(report.conflictCount).toBe(2);
    expect(report.conflicts[0]).toEqual({
      kind: 'class',
      key: 'User',
      sources: [
        { role: 'existing', repositoryFullName: 'acme/users', branch: 'main', path: 'openapi.yaml' },
        { role: 'incoming', repositoryFullName: 'acme/billing', branch: 'main', path: 'spec.yaml', definition: { title: 'User' } },
      ],
    });
    expect(report.conflicts[1].sources[1].definition).toBeNull();
  });

  test('caps the conflicts it carries but keeps the count', () => {
    const many: ParentEntity[] = Array.from({ length: MAX_REPORTED_CONFLICTS + 5 }, (_, i) => ({
      kind: 'class',
      key: `C${String(i).padStart(3, '0')}`,
      source: users,
    }));
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: many.map((e) => e.key),
      incomingPaths: [],
      parentEntities: many,
    });
    const report = buildFederationReport({
      status: 'conflicted',
      plan,
      incoming: billing,
      pathsCarried: 0,
      incomingDefinition: () => null,
    });
    expect(report.conflicts).toHaveLength(MAX_REPORTED_CONFLICTS);
    expect(report.conflictCount).toBe(MAX_REPORTED_CONFLICTS + 5);
  });

  test('a merge reports the sources and what was carried', () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['Invoice'],
      incomingPaths: [],
      parentEntities: PARENT,
    });
    const report = buildFederationReport({
      status: 'merged',
      plan,
      incoming: billing,
      versionId: 'ver-2',
      parentVersionId: 'ver-1',
      pathsCarried: 1,
      incomingDefinition: () => null,
    });
    expect(report).toMatchObject({
      status: 'merged',
      versionId: 'ver-2',
      sourceCount: 2,
      classesCarried: 2,
      pathsCarried: 1,
      removedCount: 0,
      sources: [
        { repositoryFullName: 'acme/users', branch: 'main', path: 'openapi.yaml', precedence: 1 },
        { repositoryFullName: 'acme/billing', branch: 'main', path: 'spec.yaml', precedence: 2 },
      ],
    });
  });
});

describe('postFederationMerge', () => {
  const caller = { userId: 'user-1', tenantId: 'tenant-1', tenantSlug: 'ac me' };
  const report = { status: 'merged' } as unknown as FederationMergeReport;

  test('posts as the importing user to the project route', async () => {
    const fetchImpl = jest.fn(async () => ({ ok: true, status: 201 })) as unknown as typeof fetch;
    expect(await postFederationMerge(caller, 'proj-1', report, fetchImpl)).toBeNull();
    const [url, init] = (fetchImpl as unknown as jest.Mock).mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://rest.test/v1/tenants/ac%20me/projects/proj-1/federation-merges');
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer for-user-1');
    expect(JSON.parse(String(init.body))).toEqual({ status: 'merged' });
  });

  test('never throws', async () => {
    const refused = jest.fn(async () => ({ ok: false, status: 403 })) as unknown as typeof fetch;
    expect(await postFederationMerge(caller, 'p', report, refused)).toBe('apiome-rest answered 403');
    const down = jest.fn(async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    expect(await postFederationMerge(caller, 'p', report, down)).toBe('ECONNREFUSED');
  });
});

describe('loadProjectFederation', () => {
  const q = (rows: Array<Record<string, unknown>>): Queryable & { sql: string[] } => {
    const sql: string[] = [];
    return { sql, query: async (text: string) => (sql.push(text), { rows }) };
  };

  test('reads the switch without erroring on a missing column', async () => {
    const off = q([{ federation: false }]);
    expect(await loadProjectFederation(off, 'proj-1')).toBe(false);
    expect(off.sql[0]).toContain("to_jsonb(p) -> 'repository_federation'");
    expect(await loadProjectFederation(q([{ federation: null }]), 'proj-1')).toBe(true);
    expect(await loadProjectFederation(q([]), 'proj-1')).toBe(true);
    const none = q([]);
    expect(await loadProjectFederation(none, null)).toBe(true);
    expect(none.sql).toEqual([]);
  });
});
