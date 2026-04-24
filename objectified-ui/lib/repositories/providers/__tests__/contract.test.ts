import { describe, expect, it, jest } from '@jest/globals';
import { GithubRepositoryProvider } from '../github-provider';
import { GitlabRepositoryProvider } from '../gitlab-provider';
import { RepositoryProviderError } from '../repository-provider';

function jsonResponse(
  body: unknown,
  init?: { status?: number; headers?: Record<string, string> }
): Response {
  const status = init?.status ?? 200;
  const headersMap = new Map<string, string>(
    Object.entries(init?.headers ?? {}).map(([key, value]) => [key.toLowerCase(), value])
  );

  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get: (name: string) => headersMap.get(name.toLowerCase()) ?? null,
    } as Headers,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

async function collect<T>(iterable: AsyncIterable<T>): Promise<T[]> {
  const list: T[] = [];
  for await (const item of iterable) {
    list.push(item);
  }
  return list;
}

function makeGitlabApiMock() {
  return {
    Projects: {
      all: jest.fn(),
      show: jest.fn(),
    },
    Branches: {
      all: jest.fn(),
      show: jest.fn(),
    },
    Repositories: {
      allRepositoryTrees: jest.fn(),
    },
    RepositoryFiles: {
      show: jest.fn(),
    },
    ProjectHooks: {
      add: jest.fn(),
      remove: jest.fn(),
    },
  };
}

describe('RepositoryProvider contract', () => {
  it('implements every contract method for GitHub', async () => {
    const fetchMock = jest
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse([
          {
            id: 1,
            name: 'repo-a',
            full_name: 'acme/repo-a',
            description: 'A',
            private: false,
            default_branch: 'main',
            html_url: 'https://github.com/acme/repo-a',
            updated_at: '2026-01-01T00:00:00Z',
          },
        ])
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: 1,
          name: 'repo-a',
          full_name: 'acme/repo-a',
          description: 'A',
          private: false,
          default_branch: 'main',
          html_url: 'https://github.com/acme/repo-a',
          updated_at: '2026-01-01T00:00:00Z',
        })
      )
      .mockResolvedValueOnce(
        jsonResponse([
          { name: 'main', protected: true, commit: { sha: 'abc123' } },
          { name: 'dev', protected: false, commit: { sha: 'def456' } },
        ])
      )
      .mockResolvedValueOnce(jsonResponse({ sha: 'abc123' }))
      .mockResolvedValueOnce(
        jsonResponse({
          tree: [
            { path: 'docs/readme.md', type: 'blob', sha: 's1', size: 4 },
            { path: 'docs', type: 'tree', sha: 's2', size: 0 },
            { path: 'src/index.ts', type: 'blob', sha: 's3', size: 10 },
          ],
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({
          content: 'Y29udGVudA==',
          sha: 'f1',
          size: 7,
        })
      );

    const provider = new GithubRepositoryProvider(fetchMock);

    const repos = await collect(provider.listRepositories('token-1'));
    const repo = await provider.getRepository('token-1', 'acme', 'repo-a');
    const branches = await collect(provider.listBranches('token-1', { owner: 'acme', name: 'repo-a' }));
    const sha = await provider.getCommitSha('token-1', { owner: 'acme', name: 'repo-a' }, 'main');
    const tree = await collect(provider.walkTree('token-1', { owner: 'acme', name: 'repo-a' }, 'main', 'docs'));
    const file = await provider.readFile('token-1', { owner: 'acme', name: 'repo-a' }, 'main', 'docs/readme.md');

    expect(repos).toHaveLength(1);
    expect(repo.fullName).toBe('acme/repo-a');
    expect(branches.map((b) => b.name)).toEqual(['main', 'dev']);
    expect(sha).toBe('abc123');
    expect(tree.map((entry) => entry.path)).toEqual(['docs/readme.md']);
    expect(file).toEqual({ contentBase64: 'Y29udGVudA==', sha: 'f1', sizeBytes: 7 });
  });

  it('never caches token and forwards it per call', async () => {
    const fetchMock = jest
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          id: 1,
          name: 'repo-a',
          full_name: 'acme/repo-a',
          description: null,
          private: false,
          default_branch: 'main',
          html_url: 'https://github.com/acme/repo-a',
          updated_at: null,
        })
      );
    const provider = new GithubRepositoryProvider(fetchMock);

    await collect(provider.listRepositories('token-A'));
    await provider.getRepository('token-B', 'acme', 'repo-a');

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      headers: expect.objectContaining({ Authorization: 'Bearer token-A' }),
    });
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      headers: expect.objectContaining({ Authorization: 'Bearer token-B' }),
    });
  });

  it('normalizes provider errors to the shared taxonomy', async () => {
    const unauthorized = new GithubRepositoryProvider(
      jest.fn<typeof fetch>().mockResolvedValueOnce(jsonResponse({ message: 'bad token' }, { status: 401 }))
    );
    const notFound = new GithubRepositoryProvider(
      jest.fn<typeof fetch>().mockResolvedValueOnce(jsonResponse({ message: 'missing' }, { status: 404 }))
    );
    const rateLimited = new GithubRepositoryProvider(
      jest.fn<typeof fetch>().mockResolvedValueOnce(
        jsonResponse(
          { message: 'API rate limit exceeded' },
          { status: 403, headers: { 'x-ratelimit-remaining': '0' } }
        )
      )
    );
    const network = new GithubRepositoryProvider(
      jest.fn<typeof fetch>().mockRejectedValueOnce(new TypeError('network down'))
    );
    const unknown = new GithubRepositoryProvider(
      jest.fn<typeof fetch>().mockResolvedValueOnce(jsonResponse({ message: 'boom' }, { status: 500 }))
    );

    await expect(unauthorized.getRepository('t', 'a', 'b')).rejects.toMatchObject<Partial<RepositoryProviderError>>({
      code: 'UNAUTHORIZED',
    });
    await expect(notFound.getRepository('t', 'a', 'b')).rejects.toMatchObject<Partial<RepositoryProviderError>>({
      code: 'NOT_FOUND',
    });
    await expect(rateLimited.getRepository('t', 'a', 'b')).rejects.toMatchObject<Partial<RepositoryProviderError>>({
      code: 'RATE_LIMITED',
    });
    await expect(network.getRepository('t', 'a', 'b')).rejects.toMatchObject<Partial<RepositoryProviderError>>({
      code: 'NETWORK',
    });
    await expect(unknown.getRepository('t', 'a', 'b')).rejects.toMatchObject<Partial<RepositoryProviderError>>({
      code: 'UNKNOWN',
    });
  });
});

describe('GitLab RepositoryProvider contract', () => {
  it('implements every contract method for GitLab, including webhooks', async () => {
    const api = makeGitlabApiMock();
    api.Projects.all
      .mockResolvedValueOnce([
        {
          id: 1,
          path: 'repo-a',
          path_with_namespace: 'acme/repo-a',
          description: 'A',
          visibility: 'public',
          default_branch: 'main',
          web_url: 'https://gitlab.com/acme/repo-a',
          last_activity_at: '2026-01-01T00:00:00Z',
        },
      ])
      .mockResolvedValueOnce([
        {
          id: 2,
          path: 'repo-b',
          path_with_namespace: 'acme/repo-b',
          description: null,
          visibility: 'private',
          default_branch: 'main',
          web_url: 'https://gitlab.com/acme/repo-b',
          last_activity_at: '2026-01-02T00:00:00Z',
        },
      ])
      .mockResolvedValueOnce([]);
    api.Projects.show.mockResolvedValueOnce({
      id: 1,
      path: 'repo-a',
      path_with_namespace: 'acme/repo-a',
      description: 'A',
      visibility: 'public',
      default_branch: 'main',
      web_url: 'https://gitlab.com/acme/repo-a',
      last_activity_at: '2026-01-01T00:00:00Z',
    });
    api.Branches.all.mockResolvedValueOnce([
      { name: 'main', protected: true, commit: { id: 'abc123' } },
      { name: 'dev', protected: false, commit: { id: 'def456' } },
    ]);
    api.Branches.show.mockResolvedValueOnce({ name: 'main', commit: { id: 'abc123' } });
    api.Repositories.allRepositoryTrees.mockResolvedValueOnce([
      { path: 'docs/readme.md', type: 'blob', id: 's1', size: 4 },
      { path: 'docs', type: 'tree', id: 's2', size: 0 },
      { path: 'src/index.ts', type: 'blob', id: 's3', size: 10 },
    ]);
    api.RepositoryFiles.show.mockResolvedValueOnce({
      content: 'Y29udGVudA==',
      blob_id: 'f1',
      size: 7,
    });
    api.ProjectHooks.add.mockResolvedValueOnce({ id: 42 });
    api.ProjectHooks.remove.mockResolvedValueOnce(undefined);

    const provider = new GitlabRepositoryProvider(() => api, () => 'fixed-secret');

    const repos = await collect(provider.listRepositories('token-1', { perPage: 1 }));
    const repo = await provider.getRepository('token-1', 'acme', 'repo-a');
    const branches = await collect(provider.listBranches('token-1', { owner: 'acme', name: 'repo-a' }));
    const sha = await provider.getCommitSha('token-1', { owner: 'acme', name: 'repo-a' }, 'main');
    const tree = await collect(provider.walkTree('token-1', { owner: 'acme', name: 'repo-a' }, 'main', 'docs'));
    const file = await provider.readFile('token-1', { owner: 'acme', name: 'repo-a' }, 'main', 'docs/readme.md');
    const webhook = await provider.registerWebhook('token-1', { owner: 'acme', name: 'repo-a' }, {
      url: 'https://example.com/hooks/gitlab',
      events: ['push'],
    });
    await provider.removeWebhook('token-1', { owner: 'acme', name: 'repo-a' }, '42');

    const validHeaders = new Headers({ 'x-gitlab-token': 'fixed-secret' });
    const invalidHeaders = new Headers({ 'x-gitlab-token': 'wrong-secret' });

    expect(repos.map((item) => item.fullName)).toEqual(['acme/repo-a', 'acme/repo-b']);
    expect(repo.fullName).toBe('acme/repo-a');
    expect(branches.map((b) => b.name)).toEqual(['main', 'dev']);
    expect(sha).toBe('abc123');
    expect(tree.map((entry) => entry.path)).toEqual(['docs/readme.md']);
    expect(file).toEqual({ contentBase64: 'Y29udGVudA==', sha: 'f1', sizeBytes: 7 });
    expect(webhook).toEqual({ id: '42', secret: 'fixed-secret' });
    expect(provider.verifyWebhookSignature?.('fixed-secret', validHeaders, '')).toBe(true);
    expect(provider.verifyWebhookSignature?.('fixed-secret', invalidHeaders, '')).toBe(false);

    expect(api.Projects.all.mock.calls[0]?.[0]).toMatchObject({
      pagination: 'keyset',
      orderBy: 'id',
      sort: 'asc',
      perPage: 1,
    });
    expect(api.Projects.all.mock.calls[1]?.[0]).toMatchObject({
      idAfter: 1,
    });
  });

  it('never caches token and forwards it per call', async () => {
    const api = makeGitlabApiMock();
    api.Projects.all.mockResolvedValueOnce([]);
    api.Projects.show.mockResolvedValueOnce({
      id: 1,
      path: 'repo-a',
      path_with_namespace: 'acme/repo-a',
      visibility: 'public',
      default_branch: 'main',
      web_url: 'https://gitlab.com/acme/repo-a',
      last_activity_at: null,
    });
    const apiFactory = jest.fn().mockReturnValue(api);

    const provider = new GitlabRepositoryProvider(apiFactory);
    await collect(provider.listRepositories('token-A'));
    await provider.getRepository('token-B', 'acme', 'repo-a');

    expect(apiFactory).toHaveBeenCalledTimes(2);
    expect(apiFactory).toHaveBeenNthCalledWith(1, 'token-A');
    expect(apiFactory).toHaveBeenNthCalledWith(2, 'token-B');
  });

  it('normalizes provider errors to the shared taxonomy', async () => {
    const unauthorizedApi = makeGitlabApiMock();
    unauthorizedApi.Projects.show.mockRejectedValueOnce({ response: { status: 401 } });
    const notFoundApi = makeGitlabApiMock();
    notFoundApi.Projects.show.mockRejectedValueOnce({ response: { status: 404 } });
    const rateLimitedApi = makeGitlabApiMock();
    rateLimitedApi.Projects.show.mockRejectedValueOnce({ response: { status: 429 } });
    const networkApi = makeGitlabApiMock();
    networkApi.Projects.show.mockRejectedValueOnce(new TypeError('network down'));
    const unknownApi = makeGitlabApiMock();
    unknownApi.Projects.show.mockRejectedValueOnce({ response: { status: 500 } });

    await expect(
      new GitlabRepositoryProvider(() => unauthorizedApi).getRepository('t', 'a', 'b')
    ).rejects.toMatchObject<Partial<RepositoryProviderError>>({
      code: 'UNAUTHORIZED',
    });
    await expect(
      new GitlabRepositoryProvider(() => notFoundApi).getRepository('t', 'a', 'b')
    ).rejects.toMatchObject<Partial<RepositoryProviderError>>({
      code: 'NOT_FOUND',
    });
    await expect(
      new GitlabRepositoryProvider(() => rateLimitedApi).getRepository('t', 'a', 'b')
    ).rejects.toMatchObject<Partial<RepositoryProviderError>>({
      code: 'RATE_LIMITED',
    });
    await expect(
      new GitlabRepositoryProvider(() => networkApi).getRepository('t', 'a', 'b')
    ).rejects.toMatchObject<Partial<RepositoryProviderError>>({
      code: 'NETWORK',
    });
    await expect(
      new GitlabRepositoryProvider(() => unknownApi).getRepository('t', 'a', 'b')
    ).rejects.toMatchObject<Partial<RepositoryProviderError>>({
      code: 'UNKNOWN',
    });
  });
});
