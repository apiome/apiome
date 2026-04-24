import { RepositoryProviderError, type RepositoryProvider } from './repository-provider';
import type { BranchInfo, ListReposOpts, RepoDetail, RepoRef, RepoSummary, TreeEntry } from './types';

type FetchFn = typeof fetch;

interface RequestJsonOptions {
  path: string;
  token: string;
  query?: Record<string, string | number | undefined>;
}

export class GithubRepositoryProvider implements RepositoryProvider {
  readonly id = 'github' as const;
  private readonly fetchFn: FetchFn;

  constructor(fetchFn?: FetchFn) {
    this.fetchFn = fetchFn ?? fetch;
  }

  async *listRepositories(token: string, opts?: ListReposOpts): AsyncIterable<RepoSummary> {
    const perPage = opts?.perPage ?? 100;
    let page = opts?.page ?? 1;
    const sort = opts?.sort ?? 'updated';

    while (true) {
      const repositories = await this.requestJson<unknown[]>({
        path: '/user/repos',
        token,
        query: {
          per_page: perPage,
          page,
          sort,
          visibility: opts?.visibility,
        },
      });

      if (!Array.isArray(repositories) || repositories.length === 0) {
        return;
      }

      for (const entry of repositories) {
        if (!entry || typeof entry !== 'object') {
          continue;
        }

        const repo = entry as Record<string, unknown>;
        yield {
          id: String(repo.id ?? ''),
          name: String(repo.name ?? ''),
          fullName: String(repo.full_name ?? ''),
          description: typeof repo.description === 'string' ? repo.description : null,
          isPrivate: Boolean(repo.private),
          defaultBranch: typeof repo.default_branch === 'string' ? repo.default_branch : 'main',
          htmlUrl: String(repo.html_url ?? ''),
          updatedAt: typeof repo.updated_at === 'string' ? repo.updated_at : null,
        };
      }

      if (repositories.length < perPage) {
        return;
      }

      page += 1;
    }
  }

  async getRepository(token: string, owner: string, name: string): Promise<RepoDetail> {
    const repo = await this.requestJson<Record<string, unknown>>({
      path: `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`,
      token,
    });

    return {
      id: String(repo.id ?? ''),
      name: String(repo.name ?? ''),
      fullName: String(repo.full_name ?? `${owner}/${name}`),
      description: typeof repo.description === 'string' ? repo.description : null,
      isPrivate: Boolean(repo.private),
      defaultBranch: typeof repo.default_branch === 'string' ? repo.default_branch : 'main',
      htmlUrl: String(repo.html_url ?? ''),
      updatedAt: typeof repo.updated_at === 'string' ? repo.updated_at : null,
    };
  }

  async *listBranches(token: string, repo: RepoRef): AsyncIterable<BranchInfo> {
    let page = 1;
    const perPage = 100;

    while (true) {
      const response = await this.requestJson<unknown[]>({
        path: `/repos/${encodeURIComponent(repo.owner)}/${encodeURIComponent(repo.name)}/branches`,
        token,
        query: { per_page: perPage, page },
      });

      if (!Array.isArray(response) || response.length === 0) {
        return;
      }

      for (const branch of response) {
        if (!branch || typeof branch !== 'object') {
          continue;
        }

        const raw = branch as Record<string, unknown>;
        const commit = (raw.commit as Record<string, unknown> | undefined) ?? {};
        yield {
          name: String(raw.name ?? ''),
          commitSha: String(commit.sha ?? ''),
          isProtected: Boolean(raw.protected),
        };
      }

      if (response.length < perPage) {
        return;
      }

      page += 1;
    }
  }

  async getCommitSha(token: string, repo: RepoRef, branch: string): Promise<string> {
    const commit = await this.requestJson<Record<string, unknown>>({
      path: `/repos/${encodeURIComponent(repo.owner)}/${encodeURIComponent(repo.name)}/commits/${encodeURIComponent(branch)}`,
      token,
    });
    return String(commit.sha ?? '');
  }

  async *walkTree(token: string, repo: RepoRef, branch: string, subpath?: string): AsyncIterable<TreeEntry> {
    const normalizedSubpath = normalizeSubpath(subpath);
    const response = await this.requestJson<Record<string, unknown>>({
      path: `/repos/${encodeURIComponent(repo.owner)}/${encodeURIComponent(repo.name)}/git/trees/${encodeURIComponent(branch)}`,
      token,
      query: { recursive: 1 },
    });
    const tree = response.tree;

    if (!Array.isArray(tree)) {
      return;
    }

    for (const item of tree) {
      if (!item || typeof item !== 'object') {
        continue;
      }

      const raw = item as Record<string, unknown>;
      const rawPath = String(raw.path ?? '');
      if (!rawPath) {
        continue;
      }

      if (normalizedSubpath && !rawPath.startsWith(normalizedSubpath)) {
        continue;
      }

      const type = mapTreeType(raw.type);
      if (!type) {
        continue;
      }

      yield {
        path: rawPath,
        type,
        sha: String(raw.sha ?? ''),
        sizeBytes: Number(raw.size ?? 0),
      };
    }
  }

  async readFile(
    token: string,
    repo: RepoRef,
    branch: string,
    path: string
  ): Promise<{ contentBase64: string; sha: string; sizeBytes: number }> {
    const content = await this.requestJson<Record<string, unknown>>({
      path: `/repos/${encodeURIComponent(repo.owner)}/${encodeURIComponent(repo.name)}/contents/${path
        .split('/')
        .map((segment) => encodeURIComponent(segment))
        .join('/')}`,
      token,
      query: { ref: branch },
    });

    const rawContent = typeof content.content === 'string' ? content.content : '';
    return {
      contentBase64: rawContent.replace(/\n/g, ''),
      sha: String(content.sha ?? ''),
      sizeBytes: Number(content.size ?? 0),
    };
  }

  private async requestJson<T>({ path, token, query }: RequestJsonOptions): Promise<T> {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined) {
        searchParams.set(key, String(value));
      }
    }
    const suffix = searchParams.size > 0 ? `?${searchParams.toString()}` : '';
    const url = `https://api.github.com${path}${suffix}`;

    let response: Response;
    try {
      response = await this.fetchFn(url, {
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
        },
      });
    } catch (error) {
      throw new RepositoryProviderError('NETWORK', 'Failed to reach GitHub API', undefined, { cause: error });
    }

    if (!response.ok) {
      const body = await response.text();
      throw normalizeError(response.status, body, response.headers);
    }

    return (await response.json()) as T;
  }
}

function normalizeSubpath(subpath?: string): string {
  if (!subpath) {
    return '';
  }
  const trimmed = subpath.replace(/^\/+/, '').replace(/\/+$/, '');
  if (!trimmed) {
    return '';
  }
  return `${trimmed}/`;
}

function mapTreeType(value: unknown): TreeEntry['type'] | null {
  switch (value) {
    case 'blob':
      return 'file';
    case 'tree':
      return 'dir';
    case 'symlink':
      return 'symlink';
    case 'commit':
      return 'submodule';
    default:
      return null;
  }
}

function normalizeError(status: number, body: string, headers: Headers): RepositoryProviderError {
  if (status === 401) {
    return new RepositoryProviderError('UNAUTHORIZED', 'Unauthorized GitHub token', status);
  }
  if (status === 404) {
    return new RepositoryProviderError('NOT_FOUND', 'GitHub resource not found', status);
  }
  if (status === 429 || isRateLimited(status, body, headers)) {
    return new RepositoryProviderError('RATE_LIMITED', 'GitHub API rate limit exceeded', status);
  }
  return new RepositoryProviderError('UNKNOWN', 'Unexpected GitHub API error', status);
}

function isRateLimited(status: number, body: string, headers: Headers): boolean {
  if (status !== 403) {
    return false;
  }

  const remaining = headers.get('x-ratelimit-remaining');
  if (remaining === '0') {
    return true;
  }

  return body.toLowerCase().includes('rate limit');
}
