import { describe, expect, it, jest } from '@jest/globals';

import {
  createResolveRepositoryTokenResolver,
  RepositoryTokenResolutionError,
} from '../resolve-repository-token';

type QueryResult = { rowCount: number; rows: Record<string, unknown>[] };

function makeQueryStub(handlers: Array<(sql: string, params: unknown[]) => QueryResult>): jest.MockedFunction<
  (sql: string, params: unknown[]) => Promise<QueryResult>
> {
  let index = 0;
  return jest.fn(async (sql: string, params: unknown[]) => {
    const handler = handlers[index];
    if (!handler) {
      throw new Error(`Unexpected query #${index + 1}: ${sql}`);
    }
    index += 1;
    return handler(sql, params);
  });
}

describe('resolveRepositoryToken', () => {
  it('returns in-memory token for active linked account and writes success audit without token payload', async () => {
    const query = makeQueryStub([
      () => ({
        rowCount: 1,
        rows: [
          {
            linked_account_id: 'linked-1',
            scopes: ['repo', 'read:org'],
            project_id: 'project-1',
            provider: 'github',
            user_id: 'user-1',
            access_token: 'access-live',
            refresh_token: null,
            token_expires_at: '2030-01-01T00:00:00.000Z',
          },
        ],
      }),
      (sql, params) => {
        expect(sql).toContain('INSERT INTO odb.workflow_audit');
        const detail = JSON.parse(String(params[5]));
        expect(detail).toEqual({
          repository_id: 'repo-1',
          linked_account_id: 'linked-1',
          provider: 'github',
          result: 'success',
        });
        expect(JSON.stringify(detail)).not.toContain('access-live');
        return { rowCount: 1, rows: [] };
      },
    ]);

    const resolveRepositoryToken = createResolveRepositoryTokenResolver({
      query,
      now: () => new Date('2026-04-23T00:00:00.000Z'),
      refreshers: {},
    });

    const resolved = await resolveRepositoryToken('repo-1', { tenantId: 'tenant-1', userId: 'user-1' }, ['repo']);

    expect(resolved).toMatchObject({
      repositoryId: 'repo-1',
      linkedAccountId: 'linked-1',
      provider: 'github',
      accessToken: 'access-live',
    });
  });

  it('refreshes expired token when provider refresher exists and persists new token values', async () => {
    const query = makeQueryStub([
      () => ({
        rowCount: 1,
        rows: [
          {
            linked_account_id: 'linked-2',
            scopes: ['repo'],
            project_id: null,
            provider: 'custom',
            user_id: 'user-2',
            access_token: 'old-token',
            refresh_token: 'refresh-2',
            token_expires_at: '2025-01-01T00:00:00.000Z',
          },
        ],
      }),
      (sql, params) => {
        expect(sql).toContain('UPDATE odb.external_auth_providers');
        expect(params).toEqual([
          'new-token',
          'new-refresh',
          new Date('2026-06-01T00:00:00.000Z'),
          'linked-2',
        ]);
        return { rowCount: 1, rows: [] };
      },
      (sql, params) => {
        expect(sql).toContain('INSERT INTO odb.workflow_audit');
        const detail = JSON.parse(String(params[5]));
        expect(detail.result).toBe('success');
        expect(JSON.stringify(detail)).not.toContain('new-token');
        return { rowCount: 1, rows: [] };
      },
    ]);

    const resolveRepositoryToken = createResolveRepositoryTokenResolver({
      query,
      now: () => new Date('2026-04-23T00:00:00.000Z'),
      refreshers: {
        custom: async () => ({
          accessToken: 'new-token',
          refreshToken: 'new-refresh',
          expiresAt: new Date('2026-06-01T00:00:00.000Z'),
        }),
      },
    });

    const resolved = await resolveRepositoryToken('repo-2', { tenantId: 'tenant-2', userId: 'user-2' });

    expect(resolved.accessToken).toBe('new-token');
    expect(resolved.expiresAt?.toISOString()).toBe('2026-06-01T00:00:00.000Z');
  });

  it('raises typed errors and writes failure audit without token payloads', async () => {
    const query = makeQueryStub([
      () => ({
        rowCount: 1,
        rows: [
          {
            linked_account_id: 'linked-3',
            scopes: ['repo'],
            project_id: 'project-3',
            provider: 'github',
            user_id: 'user-3',
            access_token: 'expired-token',
            refresh_token: null,
            token_expires_at: '2020-01-01T00:00:00.000Z',
          },
        ],
      }),
      (sql, params) => {
        expect(sql).toContain('INSERT INTO odb.workflow_audit');
        const detail = JSON.parse(String(params[5]));
        expect(detail).toEqual({
          repository_id: 'repo-3',
          linked_account_id: 'linked-3',
          provider: 'github',
          result: 'failure',
        });
        expect(JSON.stringify(detail)).not.toContain('expired-token');
        return { rowCount: 1, rows: [] };
      },
    ]);

    const resolveRepositoryToken = createResolveRepositoryTokenResolver({
      query,
      now: () => new Date('2026-04-23T00:00:00.000Z'),
      refreshers: {},
    });

    await expect(
      resolveRepositoryToken('repo-3', { tenantId: 'tenant-3', userId: 'user-3' })
    ).rejects.toMatchObject<Partial<RepositoryTokenResolutionError>>({
      code: 'TOKEN_EXPIRED_NO_REFRESH',
    });
  });
});
