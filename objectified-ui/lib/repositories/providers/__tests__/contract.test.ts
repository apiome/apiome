import { describe, expect, it, jest } from '@jest/globals';
import { GithubRepositoryProvider } from '../github-provider';
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
