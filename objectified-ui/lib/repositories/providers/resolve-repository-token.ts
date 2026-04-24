'use server';

const connectionPool = require('../../db/db');

type RepositoryTokenErrorCode =
  | 'TOKEN_REVOKED'
  | 'TOKEN_EXPIRED_NO_REFRESH'
  | 'LINKED_ACCOUNT_REMOVED'
  | 'INSUFFICIENT_SCOPE';

interface UserContext {
  tenantId: string;
  userId: string;
}

interface LinkedAccountTokenRow {
  linked_account_id: string;
  scopes: string[] | null;
  project_id: string | null;
  provider: string;
  user_id: string;
  access_token: string | null;
  refresh_token: string | null;
  token_expires_at: Date | string | null;
}

interface RefreshedTokenBundle {
  accessToken: string;
  refreshToken?: string | null;
  expiresAt: Date | null;
}

interface TokenRefresherInput {
  refreshToken: string;
  provider: string;
  linkedAccountId: string;
  userContext: UserContext;
}

type TokenRefresher = (input: TokenRefresherInput) => Promise<RefreshedTokenBundle>;

interface ResolveRepositoryTokenDeps {
  query: (sql: string, params: unknown[]) => Promise<{ rowCount: number | null; rows: Record<string, unknown>[] }>;
  now: () => Date;
  refreshers: Partial<Record<string, TokenRefresher>>;
}

export interface ScopedRepositoryToken {
  repositoryId: string;
  linkedAccountId: string;
  provider: string;
  accessToken: string;
  expiresAt: Date | null;
}

export class RepositoryTokenResolutionError extends Error {
  readonly code: RepositoryTokenErrorCode;

  constructor(code: RepositoryTokenErrorCode, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = 'RepositoryTokenResolutionError';
    this.code = code;
  }
}

function parseTimestamp(value: Date | string | null): Date | null {
  if (value === null) {
    return null;
  }
  if (value instanceof Date) {
    return value;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function toLinkedAccountTokenRow(value: Record<string, unknown> | null): LinkedAccountTokenRow | null {
  if (!value) {
    return null;
  }
  const scopes = Array.isArray(value.scopes)
    ? value.scopes.filter((scope): scope is string => typeof scope === 'string')
    : null;
  return {
    linked_account_id: typeof value.linked_account_id === 'string' ? value.linked_account_id : '',
    scopes,
    project_id: typeof value.project_id === 'string' ? value.project_id : null,
    provider: typeof value.provider === 'string' ? value.provider : '',
    user_id: typeof value.user_id === 'string' ? value.user_id : '',
    access_token: typeof value.access_token === 'string' ? value.access_token : null,
    refresh_token: typeof value.refresh_token === 'string' ? value.refresh_token : null,
    token_expires_at:
      value.token_expires_at instanceof Date || typeof value.token_expires_at === 'string'
        ? value.token_expires_at
        : null,
  };
}

function hasAllScopes(requiredScopes: string[], grantedScopes: string[] | null): boolean {
  if (requiredScopes.length === 0) {
    return true;
  }
  if (!Array.isArray(grantedScopes)) {
    return false;
  }
  const granted = new Set(grantedScopes);
  return requiredScopes.every((scope) => granted.has(scope));
}

async function insertTokenAudit(
  deps: ResolveRepositoryTokenDeps,
  args: {
    tenantId: string;
    projectId: string | null;
    actorId: string;
    repositoryId: string;
    linkedAccountId: string | null;
    provider: string | null;
    result: 'success' | 'failure';
  }
): Promise<void> {
  const detail = {
    repository_id: args.repositoryId,
    linked_account_id: args.linkedAccountId,
    provider: args.provider,
    result: args.result,
  };

  await deps.query(
    `INSERT INTO odb.workflow_audit (
      tenant_id, project_id, version_id, action, outcome, actor_id, detail
    ) VALUES ($1, $2, NULL, $3, $4, $5, $6::jsonb)`,
    [args.tenantId, args.projectId, 'repository.token_resolved', args.result, args.actorId, JSON.stringify(detail)]
  );
}

export function createResolveRepositoryTokenResolver(partialDeps?: Partial<ResolveRepositoryTokenDeps>) {
  const deps: ResolveRepositoryTokenDeps = {
    query: partialDeps?.query ?? ((sql: string, params: unknown[]) => connectionPool.query(sql, params)),
    now: partialDeps?.now ?? (() => new Date()),
    refreshers: partialDeps?.refreshers ?? {},
  };

  return async function resolveRepositoryToken(
    repositoryId: string,
    userContext: UserContext,
    requiredScopes: string[] = []
  ): Promise<ScopedRepositoryToken> {
    let linkedAccountId: string | null = null;
    let provider: string | null = null;
    let projectId: string | null = null;

    try {
      const linkedAccountResult = await deps.query(
        `SELECT rcr.linked_account_id, rcr.scopes, r.project_id,
                eap.provider, eap.user_id, eap.access_token, eap.refresh_token, eap.token_expires_at
         FROM odb.repository_credential_ref rcr
         JOIN odb.repository r ON r.id = rcr.repository_id
         LEFT JOIN odb.external_auth_providers eap ON eap.id = rcr.linked_account_id
         WHERE rcr.repository_id = $1
           AND r.tenant_id = $2
           AND eap.user_id = $3
         ORDER BY rcr.linked_account_id
         LIMIT 1`,
        [repositoryId, userContext.tenantId, userContext.userId]
      );

      const row = toLinkedAccountTokenRow(linkedAccountResult.rows[0] ?? null);
      linkedAccountId = row?.linked_account_id ?? null;

      if (!row || !row.linked_account_id || !row.provider) {
        throw new RepositoryTokenResolutionError(
          'LINKED_ACCOUNT_REMOVED',
          'Repository linked account reference was removed.'
        );
      }

      provider = row.provider;
      projectId = row.project_id;

      if (row.user_id !== userContext.userId) {
        throw new RepositoryTokenResolutionError(
          'LINKED_ACCOUNT_REMOVED',
          'Linked account no longer belongs to the active user.'
        );
      }

      if (!hasAllScopes(requiredScopes, row.scopes)) {
        throw new RepositoryTokenResolutionError(
          'INSUFFICIENT_SCOPE',
          'Linked account token does not include required repository scopes.'
        );
      }

      const expiresAt = parseTimestamp(row.token_expires_at);
      const now = deps.now();
      const isExpired = expiresAt !== null && expiresAt.getTime() <= now.getTime();

      let accessToken = row.access_token;
      let nextExpiresAt = expiresAt;

      if (isExpired) {
        if (!row.refresh_token) {
          throw new RepositoryTokenResolutionError(
            'TOKEN_EXPIRED_NO_REFRESH',
            'Linked account token expired and no refresh token is available.'
          );
        }

        const refresher = deps.refreshers[row.provider];
        if (!refresher) {
          throw new RepositoryTokenResolutionError(
            'TOKEN_EXPIRED_NO_REFRESH',
            `Provider "${row.provider}" does not support token refresh in this environment.`
          );
        }

        let refreshed: RefreshedTokenBundle;
        try {
          refreshed = await refresher({
            refreshToken: row.refresh_token,
            provider: row.provider,
            linkedAccountId: row.linked_account_id,
            userContext,
          });
        } catch (error) {
          throw new RepositoryTokenResolutionError(
            'TOKEN_REVOKED',
            'Linked account refresh token was rejected by the provider.',
            { cause: error }
          );
        }

        accessToken = refreshed.accessToken;
        nextExpiresAt = refreshed.expiresAt;
        const refreshToken = refreshed.refreshToken ?? row.refresh_token;

        const updateResult = await deps.query(
          `UPDATE odb.external_auth_providers
           SET access_token = $1,
               refresh_token = $2,
               token_expires_at = $3
           WHERE id = $4`,
          [accessToken, refreshToken, nextExpiresAt, row.linked_account_id]
        );
        if ((updateResult.rowCount ?? 0) === 0) {
          throw new RepositoryTokenResolutionError(
            'LINKED_ACCOUNT_REMOVED',
            'Linked account was removed while refreshing token.'
          );
        }
      }

      if (!accessToken) {
        throw new RepositoryTokenResolutionError(
          'TOKEN_REVOKED',
          'Linked account token is missing or was revoked.'
        );
      }

      await insertTokenAudit(deps, {
        tenantId: userContext.tenantId,
        projectId,
        actorId: userContext.userId,
        repositoryId,
        linkedAccountId,
        provider,
        result: 'success',
      });

      return {
        repositoryId,
        linkedAccountId: row.linked_account_id,
        provider: row.provider,
        accessToken,
        expiresAt: nextExpiresAt,
      };
    } catch (error) {
      await insertTokenAudit(deps, {
        tenantId: userContext.tenantId,
        projectId,
        actorId: userContext.userId,
        repositoryId,
        linkedAccountId,
        provider,
        result: 'failure',
      }).catch(() => undefined);

      if (error instanceof RepositoryTokenResolutionError) {
        throw error;
      }
      throw new RepositoryTokenResolutionError(
        'TOKEN_REVOKED',
        'Token resolution failed due to an unexpected repository credential error.',
        { cause: error }
      );
    }
  };
}

export const resolveRepositoryToken = createResolveRepositoryTokenResolver();
