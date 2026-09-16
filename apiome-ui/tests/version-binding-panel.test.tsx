/**
 * The Repository tab of the Versions dashboard, rendered (GNC-2.1, #4737).
 *
 * `draft-bindings-model.test.ts` holds the rules and `bindings-css.test.ts` the declarations; this
 * mounts the real `VersionBindingPanel` against mocked BFF routes and pins the ticket's acceptance
 * criteria as a reader meets them:
 *
 *   1. **A draft has at most one active binding** — an already-bound version binds again only as a
 *      replacement, and the row it replaced is still on the screen as history.
 *   2. **Binding authorization verifies repository access** — a credential that cannot read the
 *      repository is refused in words the reader can act on, and nothing is shown as bound.
 *   3. **A ref update creates a sync candidate, not a change** — the panel says what moved and
 *      offers the two decisions, while the binding's own commit stays where it was.
 *   4. **The source digest and the binding history are retained** — both are on the screen.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { VersionBindingPanel } from '../src/app/components/ade/bindings';

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const REV_1 = '11111111-1111-4111-8111-111111111111';
const REV_2 = '22222222-2222-4222-8222-222222222222';
const NOW = Date.parse('2026-09-16T12:00:00Z');
const COMMIT_ONE = '1'.repeat(40);
const COMMIT_TWO = '2'.repeat(40);

const VERSIONS = [
  { id: REV_2, version_id: '2.0.0' },
  { id: REV_1, version_id: '1.0.0', published: true },
];

const REPOSITORIES = [
  { id: 'r1', repository_full_name: 'acme/specs', default_branch: 'trunk' },
  { id: 'r2', repository_full_name: 'acme/orders', default_branch: 'main' },
];

/** The binding the bound fixtures describe. */
const BINDING = {
  id: 'b1',
  version_id: REV_2,
  repository_id: 'r1',
  provider: 'github',
  repo_full_name: 'acme/specs',
  repo_url: 'https://github.com/acme/specs',
  ref: 'trunk',
  path: 'spec/openapi.yaml',
  commit_sha: COMMIT_ONE,
  source_digest: 'sha256:0123456789abcdef',
  synchronized_at: '2026-09-16T10:00:00Z',
  browse_url: `https://github.com/acme/specs/tree/${COMMIT_ONE}/spec/openapi.yaml`,
  active: true,
  created_by_name: 'Ada Lovelace',
  created_at: '2026-09-16T10:00:00Z',
  updated_at: '2026-09-16T10:00:00Z',
  pending_candidate_count: 0,
};

/** One sync candidate, pending. */
const CANDIDATE = {
  id: 'c1',
  binding_id: 'b1',
  ref: 'trunk',
  from_commit_sha: COMMIT_ONE,
  from_digest: 'sha256:0123456789abcdef',
  to_commit_sha: COMMIT_TWO,
  to_digest: null as string | null,
  origin: 'webhook' as const,
  status: 'pending' as const,
  detected_at: '2026-09-16T11:00:00Z',
};

/** A route the fake `fetch` answers. */
interface Route {
  test: RegExp;
  reply: (url: string, init?: RequestInit) => unknown;
  status?: number;
}

/** Every URL requested so far, with the options it was requested with. */
let calls: Array<{ url: string; init?: RequestInit }> = [];

/**
 * Install a `fetch` that answers the panel's routes; the last matching route wins.
 *
 * @param routes - Extra routes, layered over the defaults.
 */
function installFetch(routes: Route[] = []): void {
  calls = [];
  const all: Route[] = [
    { test: /\/api\/repositories$/, reply: () => ({ success: true, repositories: REPOSITORIES }) },
    {
      test: /\/bindings\?/,
      reply: () => ({ success: true, version_id: REV_2, published: false, bound: false, binding: null, released: [] }),
    },
    ...routes,
  ];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    calls.push({ url, init });
    for (const route of [...all].reverse()) {
      if (route.test.test(url)) {
        const status = route.status ?? 200;
        return { ok: status < 400, status, json: async () => route.reply(url, init) } as unknown as Response;
      }
    }
    return {
      ok: false,
      status: 404,
      json: async () => ({ success: false, error: `unrouted ${url}` }),
    } as unknown as Response;
  }) as unknown as typeof fetch;
}

/** A bound-status reply. */
function boundStatus(overrides: Record<string, unknown> = {}) {
  return {
    success: true,
    version_id: REV_2,
    version_label: '2.0.0',
    published: false,
    bound: true,
    binding: { binding: BINDING, pending: [], history: [] },
    released: [],
    ...overrides,
  };
}

/**
 * Mount the panel and wait for its first read.
 *
 * @returns The rendered result.
 */
async function renderPanel() {
  const result = render(<VersionBindingPanel projectId={PROJECT_ID} versions={VERSIONS} now={NOW} />);
  await screen.findByTestId('version-binding-panel');
  await waitFor(() => expect(calls.some((call) => call.url.includes('/bindings?'))).toBe(true));
  return result;
}

/** The URLs asked for so far. */
function urls(): string[] {
  return calls.map((call) => call.url);
}

beforeEach(() => {
  installFetch();
});

describe('reading where a version stands', () => {
  it('reads the first draft, not a published version', async () => {
    await renderPanel();
    await waitFor(() =>
      expect(urls()).toContain(`/api/projects/${PROJECT_ID}/bindings?version=${REV_2}`)
    );
    expect((screen.getByTestId('binding-version-select') as HTMLSelectElement).value).toBe(REV_2);
  });

  it('says plainly when a version is not bound', async () => {
    await renderPanel();
    expect(await screen.findByText('This version is not bound to a branch')).toBeInTheDocument();
    expect(screen.queryByTestId('binding-card')).not.toBeInTheDocument();
  });

  it('shows the ref, the path, the commit and the source digest of a bound draft', async () => {
    installFetch([{ test: /\/bindings\?/, reply: () => boundStatus() }]);
    await renderPanel();

    const card = await screen.findByTestId('binding-card');
    expect(within(card).getByText('acme/specs @ trunk · spec/openapi.yaml')).toBeInTheDocument();
    expect(screen.getByTestId('binding-commit')).toHaveTextContent('1111111');
    expect(screen.getByText('sha256:0123456789abcdef')).toBeInTheDocument();
    expect(within(card).getByText('In sync')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: /Browse source/ })).toHaveAttribute(
      'href',
      BINDING.browse_url
    );
  });

  it('re-reads when the reader picks another version', async () => {
    await renderPanel();
    fireEvent.change(screen.getByTestId('binding-version-select'), { target: { value: REV_1 } });
    await waitFor(() =>
      expect(urls()).toContain(`/api/projects/${PROJECT_ID}/bindings?version=${REV_1}`)
    );
  });

  it('says so when the project has no versions at all', () => {
    render(<VersionBindingPanel projectId={PROJECT_ID} versions={[]} now={NOW} />);
    expect(screen.getByText('This project has no versions yet')).toBeInTheDocument();
    expect(screen.queryByTestId('binding-version-select')).not.toBeInTheDocument();
  });

  it('will not offer to bind a published version', async () => {
    installFetch([
      {
        test: /\/bindings\?/,
        reply: () => ({ success: true, version_id: REV_1, published: true, bound: false, binding: null, released: [] }),
      },
    ]);
    await renderPanel();
    expect(await screen.findByText('A published version cannot be bound to a branch.')).toBeInTheDocument();
    expect(screen.queryByTestId('binding-form')).not.toBeInTheDocument();
  });
});

describe('binding a draft', () => {
  it('sends the repository, branch and path the reader chose', async () => {
    installFetch([
      { test: /\/bindings\?/, reply: (_url, init) => (init?.method === 'POST' ? { success: true } : undefined) },
      {
        test: /\/bindings\?/,
        reply: (_url, init) =>
          init?.method === 'POST'
            ? { success: true, binding: BINDING, pending: [], history: [] }
            : { success: true, version_id: REV_2, published: false, bound: false, binding: null, released: [] },
      },
    ]);
    await renderPanel();
    await screen.findByTestId('binding-form');

    fireEvent.change(await screen.findByTestId('binding-repository-select'), { target: { value: 'r1' } });
    fireEvent.change(screen.getByTestId('binding-ref-input'), { target: { value: 'release/2' } });
    fireEvent.change(screen.getByTestId('binding-path-input'), { target: { value: 'spec' } });
    fireEvent.click(screen.getByTestId('binding-submit'));

    await waitFor(() => {
      const post = calls.find((call) => call.init?.method === 'POST');
      expect(post).toBeDefined();
      expect(JSON.parse(String(post?.init?.body))).toEqual({
        repository_id: 'r1',
        ref: 'release/2',
        path: 'spec',
        replace: false,
      });
    });
  });

  it('cannot be submitted before a repository is chosen', async () => {
    await renderPanel();
    expect(await screen.findByTestId('binding-submit')).toBeDisabled();
  });

  it('binds an already-bound draft only as a replacement', async () => {
    installFetch([{ test: /\/bindings\?/, reply: () => boundStatus() }]);
    await renderPanel();
    await screen.findByTestId('binding-card');

    expect(screen.getByText('Bind somewhere else')).toBeInTheDocument();
    fireEvent.change(await screen.findByTestId('binding-repository-select'), { target: { value: 'r2' } });
    fireEvent.click(screen.getByTestId('binding-submit'));

    await waitFor(() => {
      const post = calls.find((call) => call.init?.method === 'POST');
      expect(JSON.parse(String(post?.init?.body))).toMatchObject({ replace: true });
    });
  });

  it('says what to do when the stored credential cannot read the repository', async () => {
    installFetch([
      {
        test: /\/bindings\?/,
        reply: (_url, init) =>
          init?.method === 'POST'
            ? { success: false, code: 'binding-repository-forbidden', error: 'no access' }
            : { success: true, version_id: REV_2, published: false, bound: false, binding: null, released: [] },
        status: 200,
      },
    ]);
    await renderPanel();
    fireEvent.change(await screen.findByTestId('binding-repository-select'), { target: { value: 'r1' } });
    fireEvent.click(screen.getByTestId('binding-submit'));

    const error = await screen.findByTestId('binding-error');
    expect(error).toHaveTextContent('The stored credential cannot read that repository');
    expect(screen.queryByTestId('binding-card')).not.toBeInTheDocument();
  });

  it('shows the bindings this version had before', async () => {
    installFetch([
      {
        test: /\/bindings\?/,
        reply: () =>
          boundStatus({
            released: [
              {
                ...BINDING,
                id: 'b0',
                ref: 'main',
                active: false,
                release_reason: 'replaced',
                released_at: '2026-09-15T10:00:00Z',
              },
            ],
          }),
      },
    ]);
    await renderPanel();

    const history = await screen.findByTestId('binding-released');
    expect(within(history).getByText('acme/specs @ main · spec/openapi.yaml')).toBeInTheDocument();
    expect(within(history).getByText('Released')).toBeInTheDocument();
  });
});

describe('when the branch moves', () => {
  const withCandidate = () =>
    boundStatus({
      binding: {
        binding: { ...BINDING, pending_candidate_count: 1 },
        pending: [CANDIDATE],
        history: [],
      },
    });

  it('says what moved and leaves the binding where it was', async () => {
    installFetch([{ test: /\/bindings\?/, reply: () => withCandidate() }]);
    await renderPanel();

    const pending = await screen.findByTestId('binding-pending');
    expect(within(pending).getByText('a push moved trunk from 1111111 to 2222222')).toBeInTheDocument();
    // The draft has not changed: the binding still names the commit it was bound at.
    expect(screen.getByTestId('binding-commit')).toHaveTextContent('1111111');
    expect(screen.getByText('Update available')).toBeInTheDocument();
  });

  it('does not claim the content is unchanged for a commit nobody has read', async () => {
    installFetch([{ test: /\/bindings\?/, reply: () => withCandidate() }]);
    await renderPanel();
    expect(await screen.findByTestId('binding-candidate-content')).toHaveTextContent(
      'The files at that commit have not been read yet'
    );
  });

  it('offers the two decisions and sends the one chosen', async () => {
    installFetch([{ test: /\/bindings\?/, reply: () => withCandidate() }, { test: /\/candidates\//, reply: () => ({ success: true, binding: BINDING, pending: [], history: [] }) }]);
    await renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Dismiss' }));
    await waitFor(() => {
      const post = calls.find((call) => call.url.includes('/candidates/'));
      expect(post?.url).toContain(`/candidates/c1?version=${REV_2}`);
      expect(JSON.parse(String(post?.init?.body))).toEqual({ status: 'dismissed' });
    });
  });

  it('asks the provider where the branch is now', async () => {
    installFetch([
      { test: /\/bindings\?/, reply: () => boundStatus() },
      { test: /\/bindings\/check\?/, reply: () => ({ success: true, binding: BINDING, pending: [CANDIDATE], history: [] }) },
    ]);
    await renderPanel();

    fireEvent.click(await screen.findByTestId('binding-check'));
    await waitFor(() =>
      expect(urls()).toContain(`/api/projects/${PROJECT_ID}/bindings/check?version=${REV_2}`)
    );
    expect(await screen.findByTestId('binding-notice')).toBeInTheDocument();
  });

  it('says so plainly when the branch has not moved', async () => {
    installFetch([
      { test: /\/bindings\?/, reply: () => boundStatus() },
      {
        test: /\/bindings\/check\?/,
        reply: () => ({ success: false, code: 'binding-unchanged', error: 'unchanged' }),
      },
    ]);
    await renderPanel();

    fireEvent.click(await screen.findByTestId('binding-check'));
    expect(await screen.findByTestId('binding-error')).toHaveTextContent(
      'The branch is still at the commit this draft is bound to.'
    );
  });

  it('keeps settled updates on the screen', async () => {
    installFetch([
      {
        test: /\/bindings\?/,
        reply: () =>
          boundStatus({
            binding: {
              binding: BINDING,
              pending: [],
              history: [
                {
                  ...CANDIDATE,
                  status: 'dismissed',
                  resolved_at: '2026-09-16T11:30:00Z',
                  resolved_by_name: 'Ada Lovelace',
                  resolution_note: 'not ours to take',
                },
              ],
            },
          }),
      },
    ]);
    await renderPanel();

    const history = await screen.findByTestId('binding-history');
    expect(within(history).getByText('Dismissed')).toBeInTheDocument();
    expect(within(history).getByText('not ours to take')).toBeInTheDocument();
  });
});

describe('releasing', () => {
  it('releases the binding and keeps the row as history', async () => {
    let released = false;
    installFetch([
      {
        test: /\/bindings\?/,
        reply: (_url, init) => {
          if (init?.method === 'DELETE') {
            released = true;
            return { success: true, id: 'b1', active: false };
          }
          return released
            ? boundStatus({
                bound: false,
                binding: null,
                released: [{ ...BINDING, active: false, release_reason: 'unbound', released_at: '2026-09-16T11:45:00Z' }],
              })
            : boundStatus();
        },
      },
    ]);
    await renderPanel();

    fireEvent.click(await screen.findByTestId('binding-release'));
    expect(await screen.findByTestId('binding-released')).toBeInTheDocument();
    expect(screen.queryByTestId('binding-card')).not.toBeInTheDocument();
  });
});
