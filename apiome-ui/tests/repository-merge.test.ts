/**
 * Multi-repository merge rules (REPO-5.7, #2792): `lib/repository-merge.ts`.
 */

import { describe, test, expect } from '@jest/globals';
import {
  MAX_LISTED_CONFLICTS,
  RepositoryMergeConflictError,
  describeMergePlan,
  formatMergeConflictMessage,
  formatMergeSource,
  isSameSource,
  planRepositoryMerge,
  type MergeSource,
  type ParentEntity,
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
  path: 'spec/openapi.yaml',
  precedence: 2,
};
const orders: MergeSource = {
  sourceId: null,
  repositoryId: 'repo-orders',
  repositoryFullName: 'acme/orders',
  branch: 'main',
  path: 'openapi.json',
  precedence: null,
};

const cls = (key: string, source: MergeSource | null): ParentEntity => ({ kind: 'class', key, source });
const path = (key: string, source: MergeSource | null): ParentEntity => ({ kind: 'path', key, source });

describe('planRepositoryMerge — single-source mode', () => {
  test('a first version has nothing to carry', () => {
    const plan = planRepositoryMerge({
      incoming: users,
      incomingClasses: ['User'],
      incomingPaths: ['/users'],
      parentEntities: [],
    });
    expect(plan.mode).toBe('single-source');
    expect(plan.conflicts).toEqual([]);
    expect(plan.carried).toEqual([]);
    expect(plan.sources).toEqual([users]);
  });

  test('re-importing the only source keeps the pre-REPO-5.7 behaviour (nothing carried)', () => {
    const plan = planRepositoryMerge({
      incoming: users,
      incomingClasses: ['User'],
      incomingPaths: [],
      parentEntities: [cls('User', users), cls('Legacy', users), cls('Hand', null)],
    });
    expect(plan.mode).toBe('single-source');
    expect(plan.carried).toEqual([]);
    expect(plan.removed).toEqual([]);
  });

  test('a parent with only unattributed content is single-source', () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['Invoice'],
      incomingPaths: [],
      parentEntities: [cls('Thing', null)],
    });
    expect(plan.mode).toBe('single-source');
  });
});

describe('planRepositoryMerge — multi-source mode', () => {
  test('carries the other file, replaces its own, and records both sources in precedence order', () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['Invoice'],
      incomingPaths: ['/invoices'],
      parentEntities: [
        cls('User', users),
        path('/users', users),
        cls('Invoice', billing),
        cls('OldInvoice', billing),
        path('/invoices', billing),
      ],
    });
    expect(plan.mode).toBe('multi-source');
    expect(plan.conflicts).toEqual([]);
    expect(plan.carried).toEqual([
      { kind: 'class', key: 'User', source: users },
      { kind: 'path', key: '/users', source: users },
    ]);
    expect(plan.removed).toEqual([{ kind: 'class', key: 'OldInvoice', source: billing }]);
    expect(plan.sources.map((s) => s.repositoryFullName)).toEqual(['acme/users', 'acme/billing']);
  });

  test('the same class from two files is a conflict naming both', () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['User', 'Invoice'],
      incomingPaths: ['/health'],
      parentEntities: [cls('User', users), path('/health', users), path('/users', users)],
    });
    expect(plan.conflicts).toEqual([
      { kind: 'class', key: 'User', existing: users, incoming: billing },
      { kind: 'path', key: '/health', existing: users, incoming: billing },
    ]);
    expect(plan.carried).toEqual([{ kind: 'path', key: '/users', source: users }]);
  });

  test('two files of one repository are different sources', () => {
    const otherFile: MergeSource = { ...users, sourceId: 'src-users-2', path: 'admin.yaml', precedence: 3 };
    expect(isSameSource(users, otherFile)).toBe(false);
    const plan = planRepositoryMerge({
      incoming: otherFile,
      incomingClasses: ['User'],
      incomingPaths: [],
      parentEntities: [cls('User', users)],
    });
    expect(plan.conflicts).toHaveLength(1);
  });

  test('the same file on another branch is a different source', () => {
    expect(isSameSource(users, { ...users, branch: 'develop' })).toBe(false);
  });

  test('unattributed content is carried, and superseded when the incoming file defines it', () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['Shared'],
      incomingPaths: [],
      parentEntities: [cls('User', users), cls('Shared', null), cls('Note', null)],
    });
    expect(plan.conflicts).toEqual([]);
    expect(plan.superseded).toEqual([{ kind: 'class', key: 'Shared', source: null }]);
    expect(plan.carried).toEqual([
      { kind: 'class', key: 'User', source: users },
      { kind: 'class', key: 'Note', source: null },
    ]);
  });

  test('carried entities are ordered by precedence, never-contributed sources last, then kind and key', () => {
    const plan = planRepositoryMerge({
      incoming: orders,
      incomingClasses: [],
      incomingPaths: [],
      parentEntities: [
        path('/b', billing),
        cls('Zed', users),
        cls('Bill', billing),
        cls('Alpha', users),
        cls('Loose', null),
      ],
    });
    expect(plan.carried.map((e) => `${e.source?.repositoryFullName ?? '-'}:${e.kind}:${e.key}`)).toEqual([
      'acme/users:class:Alpha',
      'acme/users:class:Zed',
      'acme/billing:class:Bill',
      'acme/billing:path:/b',
      '-:class:Loose',
    ]);
    expect(plan.sources.map((s) => s.repositoryFullName)).toEqual(['acme/users', 'acme/billing', 'acme/orders']);
  });

  test('the plan does not depend on the order of the parent entities', () => {
    const entities = [cls('User', users), path('/users', users), cls('Invoice', billing), path('/x', null)];
    const a = planRepositoryMerge({ incoming: orders, incomingClasses: [], incomingPaths: [], parentEntities: entities });
    const b = planRepositoryMerge({
      incoming: orders,
      incomingClasses: [],
      incomingPaths: [],
      parentEntities: [...entities].reverse(),
    });
    expect(b).toEqual(a);
  });

  test('a class and a path may share a key', () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: ['/odd'],
      incomingPaths: [],
      parentEntities: [path('/odd', users)],
    });
    expect(plan.conflicts).toEqual([]);
    expect(plan.carried).toEqual([{ kind: 'path', key: '/odd', source: users }]);
  });
});

describe('messages', () => {
  test('formatMergeSource', () => {
    expect(formatMergeSource(users)).toBe('acme/users (main:openapi.yaml)');
  });

  test('the conflict message names the project, every collision and the fix', () => {
    const message = formatMergeConflictMessage(
      [{ kind: 'class', key: 'User', existing: users, incoming: billing }],
      'Shop',
    );
    expect(message).toBe(
      'Repository merge conflict in project "Shop": 1 definition collides. ' +
        'class "User" is defined by acme/users (main:openapi.yaml) and acme/billing (main:spec/openapi.yaml). ' +
        'Each class and path must come from one repository: rename or remove the duplicate in one of the files, then import again.',
    );
  });

  test('a long conflict list is summarized', () => {
    const conflicts = Array.from({ length: MAX_LISTED_CONFLICTS + 3 }, (_, i) => ({
      kind: 'path' as const,
      key: `/p${i}`,
      existing: users,
      incoming: billing,
    }));
    const message = formatMergeConflictMessage(conflicts);
    expect(message).toContain(`${MAX_LISTED_CONFLICTS + 3} definitions collide.`);
    expect(message).toContain('…and 3 more.');
    expect(message).not.toContain('/p12"');
  });

  test('RepositoryMergeConflictError carries the conflicts', () => {
    const conflicts = [{ kind: 'path' as const, key: '/health', existing: users, incoming: billing }];
    const error = new RepositoryMergeConflictError(conflicts, 'Shop');
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe('RepositoryMergeConflictError');
    expect(error.conflicts).toBe(conflicts);
    expect(error.message).toContain('path "/health"');
  });

  test('describeMergePlan counts carried classes and paths', () => {
    const plan = planRepositoryMerge({
      incoming: billing,
      incomingClasses: [],
      incomingPaths: [],
      parentEntities: [cls('User', users), path('/users', users), path('/me', users)],
    });
    expect(describeMergePlan(plan)).toBe(
      'Merging 2 repository files: carrying forward 1 class and 2 paths from other files.',
    );
  });
});
