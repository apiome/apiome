import { randomBytes, timingSafeEqual } from 'node:crypto';

import { Gitlab } from '@gitbeaker/rest';

import { RepositoryProviderError, type RepositoryProvider } from './repository-provider';
import type {
  BranchInfo,
  ListReposOpts,
  RepoDetail,
  RepoRef,
  RepoSummary,
  TreeEntry,
  WebhookTarget,
} from './types';

const GITLAB_MAX_PER_PAGE = 100;

type GitlabApiFactory = (token: string) => GitlabApi;
type SecretGenerator = () => string;

interface GitlabApi {
  Projects: {
    all(options: Record<string, unknown>): Promise<unknown[]>;
    show(projectId: string): Promise<unknown>;
  };
  Branches: {
    all(projectId: string, options: Record<string, unknown>): Promise<unknown[]>;
    show(projectId: string, branch: string): Promise<unknown>;
  };
  Repositories: {
    allRepositoryTrees(projectId: string, options: Record<string, unknown>): Promise<unknown[]>;
  };
  RepositoryFiles: {
    show(projectId: string, filePath: string, ref: string): Promise<unknown>;
  };
  ProjectHooks: {
    add(projectId: string, url: string, options: Record<string, unknown>): Promise<unknown>;
    remove(projectId: string, hookId: number): Promise<void>;
  };
}

export class GitlabRepositoryProvider implements RepositoryProvider {
  readonly id = 'gitlab' as const;

  private readonly apiFactory: GitlabApiFactory;
  private readonly secretGenerator: SecretGenerator;

  constructor(apiFactory?: GitlabApiFactory, secretGenerator?: SecretGenerator) {
    this.apiFactory = apiFactory ?? createDefaultApi;
    this.secretGenerator = secretGenerator ?? createWebhookSecret;
  }

  async *listRepositories(token: string, opts?: ListReposOpts): AsyncIterable<RepoSummary> {
    const api = this.apiFactory(token);
    const perPage = Math.min(opts?.perPage ?? GITLAB_MAX_PER_PAGE, GITLAB_MAX_PER_PAGE);
    const page = opts?.page ?? 1;

    const visibilityFilter = mapGitlabVisibility(opts?.visibility);

    if (page > 1) {
      const repositories = await this.request<unknown[]>(() =>
        api.Projects.all({
          simple: true,
          orderBy: mapGitlabSort(opts?.sort),
          sort: 'desc',
          perPage,
          page,
          ...(visibilityFilter !== undefined && { visibility: visibilityFilter }),
        })
      );
      for (const repo of repositories) {
        const summary = toRepoSummary(repo);
        if (summary) {
          yield summary;
        }
      }
      return;
    }

    let idAfter: number | undefined;
    while (true) {
      const repositories = await this.request<unknown[]>(() =>
        api.Projects.all({
          simple: true,
          pagination: 'keyset',
          orderBy: 'id',
          sort: 'asc',
          perPage,
          idAfter,
          ...(visibilityFilter !== undefined && { visibility: visibilityFilter }),
        })
      );

      if (!Array.isArray(repositories) || repositories.length === 0) {
        return;
      }

      for (const repo of repositories) {
        const summary = toRepoSummary(repo);
        if (!summary) {
          continue;
        }
        yield summary;
      }

      if (repositories.length < perPage) {
        return;
      }

      const lastId = toNumericId(repositories[repositories.length - 1]);
      if (lastId === null) {
        return;
      }
      idAfter = lastId;
    }
  }

  async getRepository(token: string, owner: string, name: string): Promise<RepoDetail> {
    const api = this.apiFactory(token);
    const repository = await this.request<unknown>(() => api.Projects.show(projectPath(owner, name)));
    const summary = toRepoSummary(repository);
    if (summary) {
      return summary;
    }

    return {
      id: '',
      name,
      fullName: `${owner}/${name}`,
      description: null,
      isPrivate: true,
      defaultBranch: 'main',
      htmlUrl: '',
      updatedAt: null,
    };
  }

  async *listBranches(token: string, repo: RepoRef): AsyncIterable<BranchInfo> {
    const api = this.apiFactory(token);
    const perPage = GITLAB_MAX_PER_PAGE;
    let page = 1;

    while (true) {
      const branches = await this.request<unknown[]>(() =>
        api.Branches.all(projectPath(repo.owner, repo.name), { perPage, page })
      );
      if (!Array.isArray(branches) || branches.length === 0) {
        return;
      }

      for (const branch of branches) {
        if (!branch || typeof branch !== 'object') {
          continue;
        }
        const raw = branch as Record<string, unknown>;
        const commit = toRecord(raw.commit);
        yield {
          name: String(raw.name ?? ''),
          commitSha: String(commit?.id ?? ''),
          isProtected: Boolean(raw.protected),
        };
      }

      if (branches.length < perPage) {
        return;
      }
      page += 1;
    }
  }

  async getCommitSha(token: string, repo: RepoRef, branch: string): Promise<string> {
    const api = this.apiFactory(token);
    const branchData = await this.request<unknown>(() =>
      api.Branches.show(projectPath(repo.owner, repo.name), branch)
    );
    const record = toRecord(branchData);
    const commit = toRecord(record?.commit);
    return String(commit?.id ?? '');
  }

  async *walkTree(token: string, repo: RepoRef, branch: string, subpath?: string): AsyncIterable<TreeEntry> {
    const api = this.apiFactory(token);
    const normalizedSubpath = normalizeSubpath(subpath);
    const perPage = GITLAB_MAX_PER_PAGE;
    let page = 1;

    while (true) {
      const tree = await this.request<unknown[]>(() =>
        api.Repositories.allRepositoryTrees(projectPath(repo.owner, repo.name), {
          ref: branch,
          recursive: true,
          path: normalizedSubpath || undefined,
          perPage,
          page,
        })
      );
      if (!Array.isArray(tree) || tree.length === 0) {
        return;
      }

      for (const node of tree) {
        const entry = toTreeEntry(node);
        if (!entry) {
          continue;
        }
        if (normalizedSubpath && !entry.path.startsWith(`${normalizedSubpath}/`)) {
          continue;
        }
        yield entry;
      }

      if (tree.length < perPage) {
        return;
      }
      page += 1;
    }
  }

  async readFile(
    token: string,
    repo: RepoRef,
    branch: string,
    path: string
  ): Promise<{ contentBase64: string; sha: string; sizeBytes: number }> {
    const api = this.apiFactory(token);
    const file = await this.request<unknown>(() =>
      api.RepositoryFiles.show(projectPath(repo.owner, repo.name), normalizeFilePath(path), branch)
    );
    const record = toRecord(file);
    const content = typeof record?.content === 'string' ? record.content.replaceAll('\n', '') : '';
    return {
      contentBase64: content,
      sha: String(record?.blob_id ?? ''),
      sizeBytes: Number(record?.size ?? 0),
    };
  }

  async registerWebhook(token: string, repo: RepoRef, target: WebhookTarget): Promise<{ id: string; secret: string }> {
    const api = this.apiFactory(token);
    const secret = this.secretGenerator();
    const options = toHookOptions(target.events, secret);
    const hook = await this.request<unknown>(() =>
      api.ProjectHooks.add(projectPath(repo.owner, repo.name), target.url, options)
    );
    const record = toRecord(hook);
    return { id: String(record?.id ?? ''), secret };
  }

  async removeWebhook(token: string, repo: RepoRef, id: string): Promise<void> {
    const api = this.apiFactory(token);
    const hookId = Number(id);
    if (!Number.isFinite(hookId)) {
      throw new RepositoryProviderError('UNKNOWN', 'GitLab webhook id is invalid');
    }
    await this.request(() => api.ProjectHooks.remove(projectPath(repo.owner, repo.name), hookId));
  }

  verifyWebhookSignature(secret: string, headers: Headers): boolean {
    const provided = headers.get('x-gitlab-token');
    if (!provided) {
      return false;
    }

    const expectedBuffer = Buffer.from(secret);
    const providedBuffer = Buffer.from(provided);
    if (expectedBuffer.length !== providedBuffer.length) {
      return false;
    }

    return timingSafeEqual(expectedBuffer, providedBuffer);
  }

  private async request<T>(fn: () => Promise<T>): Promise<T> {
    try {
      return await fn();
    } catch (error) {
      throw normalizeGitlabError(error);
    }
  }
}

function createDefaultApi(token: string): GitlabApi {
  return new Gitlab({ token }) as unknown as GitlabApi;
}

function createWebhookSecret(): string {
  return randomBytes(24).toString('hex');
}

function toRepoSummary(value: unknown): RepoSummary | null {
  const record = toRecord(value);
  if (!record) {
    return null;
  }
  const namespacePath = String(record.path_with_namespace ?? '');
  const segments = namespacePath.split('/').filter((segment) => segment.length > 0);
  const fallbackName = segments[segments.length - 1] ?? '';
  const name = String(record.path ?? fallbackName);
  return {
    id: String(record.id ?? ''),
    name,
    fullName: namespacePath,
    description: typeof record.description === 'string' ? record.description : null,
    isPrivate: String(record.visibility ?? 'private') !== 'public',
    defaultBranch: typeof record.default_branch === 'string' ? record.default_branch : 'main',
    htmlUrl: String(record.web_url ?? ''),
    updatedAt: typeof record.last_activity_at === 'string' ? record.last_activity_at : null,
  };
}

function toTreeEntry(value: unknown): TreeEntry | null {
  const record = toRecord(value);
  if (!record || typeof record.path !== 'string' || record.path.length === 0) {
    return null;
  }
  const type = mapTreeType(record.type);
  if (!type) {
    return null;
  }
  return {
    path: record.path,
    type,
    sha: String(record.id ?? ''),
    sizeBytes: Number(record.size ?? 0),
  };
}

function mapTreeType(value: unknown): TreeEntry['type'] | null {
  switch (value) {
    case 'blob':
      return 'file';
    case 'tree':
      return 'dir';
    case 'commit':
      return 'submodule';
    default:
      return null;
  }
}

function toRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  return value as Record<string, unknown>;
}

function toNumericId(value: unknown): number | null {
  const record = toRecord(value);
  if (!record) {
    return null;
  }
  const parsed = Number(record.id);
  return Number.isFinite(parsed) ? parsed : null;
}

function projectPath(owner: string, name: string): string {
  return encodeURIComponent(`${owner}/${name}`);
}

function normalizeSubpath(subpath?: string): string {
  if (!subpath) {
    return '';
  }
  return subpath.replace(/^\/+|\/+$/g, '');
}

function normalizeFilePath(path: string): string {
  return path.replace(/^\/+|\/+$/g, '');
}

function mapGitlabVisibility(visibility?: ListReposOpts['visibility']): string | undefined {
  if (visibility === 'public') {
    return 'public';
  }
  if (visibility === 'private') {
    return 'private';
  }
  return undefined;
}

function mapGitlabSort(sort?: ListReposOpts['sort']): string {
  if (sort === 'created') {
    return 'created_at';
  }
  if (sort === 'updated') {
    return 'last_activity_at';
  }
  if (sort === 'full_name') {
    return 'name';
  }
  return 'last_activity_at';
}

function toHookOptions(events: string[], secret: string): Record<string, unknown> {
  const options: Record<string, unknown> = { token: secret, enableSslVerification: true };
  if (events.length === 0) {
    options.push_events = true;
    return options;
  }

  for (const event of events) {
    const normalized = `${event.toLowerCase().replace(/[^a-z0-9]+/g, '_')}_events`;
    options[normalized] = true;
  }
  return options;
}

function normalizeGitlabError(error: unknown): RepositoryProviderError {
  const status = extractStatus(error);
  if (status === 401) {
    return new RepositoryProviderError('UNAUTHORIZED', 'Unauthorized GitLab token', status, { cause: error });
  }
  if (status === 404) {
    return new RepositoryProviderError('NOT_FOUND', 'GitLab resource not found', status, { cause: error });
  }
  if (status === 429) {
    return new RepositoryProviderError('RATE_LIMITED', 'GitLab API rate limit exceeded', status, { cause: error });
  }
  if (status !== undefined) {
    return new RepositoryProviderError('UNKNOWN', 'Unexpected GitLab API error', status, { cause: error });
  }
  return new RepositoryProviderError('NETWORK', 'Failed to reach GitLab API', undefined, { cause: error });
}

function extractStatus(error: unknown): number | undefined {
  const first = toRecord(error);
  if (typeof first?.status === 'number') {
    return first.status;
  }

  const response = toRecord(first?.response);
  if (typeof response?.status === 'number') {
    return response.status;
  }

  const cause = toRecord(first?.cause);
  if (typeof cause?.status === 'number') {
    return cause.status;
  }

  return undefined;
}
