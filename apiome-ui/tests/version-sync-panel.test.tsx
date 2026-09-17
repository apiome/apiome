/**
 * The Synchronization section of the Repository tab, rendered (GNC-2.3, #4739).
 *
 * `spec-sync-model.test.ts` holds the rules and `spec-sync-css.test.ts` the declarations; this
 * mounts the real `VersionSyncPanel` against mocked BFF routes and pins the ticket's acceptance
 * criteria as a reader meets them:
 *
 *   1. **Overlapping changes become explicit conflicts** — each on screen with all three values
 *      and a link to the line of the repository file it lives at.
 *   2. **Non-overlapping changes apply deterministically** — they are listed as what *would*
 *      apply, in the order apiome-rest sent them.
 *   3. **An active draft or review decision is never overwritten** — the section says so in words,
 *      it warns when the draft has moved on since the merge, and it surfaces the guard a recorded
 *      review decision puts on the result.
 *   4. **Merge results record base, Git and draft digests** — all three are on the screen.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { VersionSyncPanel } from '../src/app/components/ade/bindings';

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const VERSION_ID = '22222222-2222-4222-8222-222222222222';
const NOW = Date.parse('2026-09-16T12:00:00Z');
const COMMIT_BASE = '1'.repeat(40);
const COMMIT_NEXT = '2'.repeat(40);

const SYNC_URL = `/api/projects/${PROJECT_ID}/bindings/sync?version=${VERSION_ID}`;

/** A merge result with two applied changes and no collisions. */
const PLAN = {
  id: 'p1',
  binding_id: 'b1',
  version_id: VERSION_ID,
  candidate_id: 'c1',
  base_commit_sha: COMMIT_BASE,
  base_digest: 'sha256:aaaabbbbcccc',
  git_commit_sha: COMMIT_NEXT,
  git_digest: 'sha256:ddddeeeeffff',
  draft_digest: 'sha256:1234567890ab',
  plan_fingerprint: 'sha256:planplanplan',
  status: 'mergeable' as const,
  auto_applied_count: 2,
  local_count: 1,
  agreed_count: 0,
  conflict_count: 0,
  unresolved_count: 0,
  changes: [
    {
      pointer: '/info/description',
      kind: 'addition' as const,
      scope: 'document',
      group: 'info',
      label: 'Added /info/description',
      after: 'Pets as a service',
      source_file: 'spec/openapi.yaml',
      source_line: 3,
    },
    {
      pointer: '/paths/~1pets/get/summary',
      kind: 'update' as const,
      scope: 'operation',
      group: 'GET /pets',
      label: 'Changed operation GET /pets at /paths/~1pets/get/summary',
      before: 'List pets',
      after: 'List every pet',
      source_file: 'spec/openapi.yaml',
      source_line: 9,
    },
  ],
  source_file: 'spec/openapi.yaml',
  source_member_count: 1,
  guard: 'none' as const,
  stale: false,
  computed_by_name: 'Ada Lovelace',
  created_at: '2026-09-16T11:30:00Z',
  updated_at: '2026-09-16T11:30:00Z',
};

/** One outstanding collision. */
const CONFLICT = {
  id: 'k1',
  plan_id: 'p1',
  pointer: '/info/version',
  scope: 'document',
  group_key: 'info',
  label: 'Changed /info/version',
  git_kind: 'update' as const,
  draft_kind: 'update' as const,
  base_value: '1.0.0',
  git_value: '2.0.0',
  draft_value: '1.5.0',
  source_file: 'spec/openapi.yaml',
  source_line: 4,
  source_url: `https://github.com/acme/specs/blob/${COMMIT_NEXT}/spec/openapi.yaml#L4`,
  resolution: null as string | null,
  resolved_by_name: null as string | null,
  resolution_note: null as string | null,
  created_at: '2026-09-16T11:30:00Z',
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
 * Install a `fetch` that answers the section's routes; the last matching route wins.
 *
 * @param routes - Extra routes, layered over the defaults.
 */
function installFetch(routes: Route[] = []): void {
  calls = [];
  const all: Route[] = [
    {
      test: /\/bindings\/sync\?/,
      reply: () => ({ success: true, version_id: VERSION_ID, bound: true, latest: null, history: [] }),
    },
    // Settling addresses the plan, not the version, so it needs its own route.
    { test: /\/sync\/plans\//, reply: () => statusWith(PLAN, []) },
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

/** A status reply carrying one merge result. */
function statusWith(
  plan: Record<string, unknown> = PLAN,
  conflicts: Array<Record<string, unknown>> = [],
  history: Array<Record<string, unknown>> = []
) {
  return {
    success: true,
    version_id: VERSION_ID,
    version_label: '2.0.0',
    bound: true,
    latest: { plan, conflicts },
    history,
  };
}

/**
 * Mount the section and wait for its first read.
 *
 * @param bound - Whether the version has an active binding.
 * @returns The rendered result.
 */
async function renderPanel(bound = true) {
  const result = render(
    <VersionSyncPanel projectId={PROJECT_ID} versionId={VERSION_ID} bound={bound} now={NOW} />
  );
  if (bound) {
    await screen.findByTestId('version-sync-panel');
    await waitFor(() => expect(calls.some((call) => call.url.includes('/bindings/sync?'))).toBe(true));
  }
  return result;
}

/** The URLs asked for so far. */
function urls(): string[] {
  return calls.map((call) => call.url);
}

/** The body of the last write, parsed. */
function lastBody(): Record<string, unknown> {
  const write = [...calls].reverse().find((call) => call.init?.method === 'POST');
  return JSON.parse(String(write?.init?.body ?? '{}'));
}

beforeEach(() => {
  installFetch();
});

describe('a version with no binding', () => {
  it('shows nothing at all and asks for nothing', async () => {
    await renderPanel(false);
    expect(screen.queryByTestId('version-sync-panel')).not.toBeInTheDocument();
    expect(urls()).toEqual([]);
  });
});

describe('before anything has been merged', () => {
  it('invites a merge and says what one does', async () => {
    await renderPanel();
    expect(await screen.findByText('This draft has not been merged with its branch yet')).toBeInTheDocument();
    expect(screen.getByTestId('sync-merge')).toBeInTheDocument();
    // The sentence that makes the whole surface safe to press.
    expect(screen.getByText(/never rewrites the draft/i)).toBeInTheDocument();
  });

  it('merges the branch and says the draft did not change', async () => {
    installFetch([{ test: /\/bindings\/sync\?/, reply: () => statusWith() }]);
    await renderPanel();
    fireEvent.click(screen.getByTestId('sync-merge'));

    await waitFor(() => expect(calls.some((call) => call.init?.method === 'POST')).toBe(true));
    const write = calls.find((call) => call.init?.method === 'POST');
    expect(write?.url).toBe(SYNC_URL);
    expect(lastBody()).toEqual({});
    expect(await screen.findByTestId('sync-notice')).toHaveTextContent(
      'Nothing about this draft changed'
    );
  });
});

describe('what a merge found', () => {
  it('records the base, Git and draft digests on the screen', async () => {
    installFetch([{ test: /\/bindings\/sync\?/, reply: () => statusWith() }]);
    await renderPanel();

    const card = await screen.findByTestId('sync-plan');
    expect(within(card).getByText('Last synchronized')).toBeInTheDocument();
    expect(within(card).getByText('1111111')).toBeInTheDocument();
    expect(within(card).getByText('2222222')).toBeInTheDocument();
    expect(within(card).getByText('sha256:1234567890ab')).toBeInTheDocument();
    expect(within(card).getByText('Merges cleanly')).toBeInTheDocument();
  });

  it('lists the incoming changes as what would apply, in order', async () => {
    installFetch([{ test: /\/bindings\/sync\?/, reply: () => statusWith() }]);
    await renderPanel();

    const applied = await screen.findByTestId('sync-changes');
    expect(within(applied).getByText('Would apply')).toBeInTheDocument();
    const pointers = within(applied)
      .getAllByText(/^\//)
      .map((node) => node.textContent);
    expect(pointers).toEqual(['/info/description', '/paths/~1pets/get/summary']);
    expect(within(applied).getByText('GET /pets')).toBeInTheDocument();
  });

  it('says the draft own changes are left exactly as they are', async () => {
    installFetch([{ test: /\/bindings\/sync\?/, reply: () => statusWith() }]);
    await renderPanel();
    expect(await screen.findByTestId('sync-local')).toHaveTextContent(
      /1 change in this draft that the repository did not touch is left exactly as it is/
    );
  });

  it('says plainly when the repository changed nothing', async () => {
    installFetch([
      {
        test: /\/bindings\/sync\?/,
        reply: () => statusWith({ ...PLAN, status: 'clean', auto_applied_count: 0, changes: [], local_count: 0 }),
      },
    ]);
    await renderPanel();
    expect(await screen.findByText('Nothing to merge')).toBeInTheDocument();
    expect(screen.queryByTestId('sync-changes')).not.toBeInTheDocument();
  });
});

describe('conflicts', () => {
  const conflicted = () =>
    statusWith(
      { ...PLAN, status: 'conflicted', conflict_count: 1, unresolved_count: 1 },
      [CONFLICT]
    );

  it('shows all three values side by side, located in the repository', async () => {
    installFetch([{ test: /\/bindings\/sync\?/, reply: conflicted }]);
    await renderPanel();

    const row = await screen.findByTestId('sync-conflict-k1');
    expect(within(row).getByText('/info/version')).toBeInTheDocument();
    expect(within(row).getByText('Last synchronized')).toBeInTheDocument();
    expect(within(row).getByText('In the repository')).toBeInTheDocument();
    expect(within(row).getByText('In this draft')).toBeInTheDocument();
    expect(within(row).getByText('"1.0.0"')).toBeInTheDocument();
    expect(within(row).getByText('"2.0.0"')).toBeInTheDocument();
    expect(within(row).getByText('"1.5.0"')).toBeInTheDocument();
    const link = within(row).getByRole('link', { name: 'spec/openapi.yaml:4' });
    expect(link).toHaveAttribute('href', CONFLICT.source_url);
  });

  it('offers the two sides and sends the one chosen with its note', async () => {
    installFetch([{ test: /\/bindings\/sync\?/, reply: conflicted }]);
    await renderPanel();

    const row = await screen.findByTestId('sync-conflict-k1');
    fireEvent.change(within(row).getByLabelText('Why, for /info/version'), {
      target: { value: 'the rename was agreed in review' },
    });
    fireEvent.click(within(row).getByRole('button', { name: /Take the repository/ }));

    await waitFor(() => expect(calls.some((call) => call.init?.method === 'POST')).toBe(true));
    const write = calls.find((call) => call.init?.method === 'POST');
    expect(write?.url).toBe(
      `/api/projects/${PROJECT_ID}/bindings/sync/plans/p1/conflicts/k1`
    );
    expect(lastBody()).toEqual({
      resolution: 'git',
      note: 'the rename was agreed in review',
    });
    expect(await screen.findByTestId('sync-notice')).toHaveTextContent(
      'The draft is unchanged either way'
    );
  });

  it('sends the other side when that is what was chosen', async () => {
    installFetch([{ test: /\/bindings\/sync\?/, reply: conflicted }]);
    await renderPanel();

    const row = await screen.findByTestId('sync-conflict-k1');
    fireEvent.click(within(row).getByRole('button', { name: /Keep this draft/ }));

    await waitFor(() => expect(calls.some((call) => call.init?.method === 'POST')).toBe(true));
    expect(lastBody()).toEqual({ resolution: 'draft' });
  });

  it('shows a settled conflict as a decision rather than as a question', async () => {
    installFetch([
      {
        test: /\/bindings\/sync\?/,
        reply: () =>
          statusWith(
            { ...PLAN, status: 'resolved', conflict_count: 1, unresolved_count: 0 },
            [
              {
                ...CONFLICT,
                resolution: 'git',
                resolved_at: '2026-09-16T11:45:00Z',
                resolved_by_name: 'Grace Hopper',
                resolution_note: 'agreed in review',
              },
            ]
          ),
      },
    ]);
    await renderPanel();

    const row = await screen.findByTestId('sync-conflict-k1');
    expect(within(row).getByTestId('sync-conflict-settled-k1')).toHaveTextContent(
      /Settled towards in the repository by Grace Hopper.*agreed in review/
    );
    expect(within(row).queryByRole('button')).not.toBeInTheDocument();
  });

  it('says so when the merge collided in more places than one result holds', async () => {
    installFetch([
      {
        test: /\/bindings\/sync\?/,
        reply: () =>
          statusWith(
            {
              ...PLAN,
              status: 'conflicted',
              conflict_count: 200,
              unresolved_count: 200,
              conflicts_truncated: true,
            },
            [CONFLICT]
          ),
      },
    ]);
    await renderPanel();
    expect(await screen.findByTestId('sync-conflicts')).toHaveTextContent(
      /the first of a longer list/
    );
  });

  it('names an absent side rather than drawing it as null', async () => {
    installFetch([
      {
        test: /\/bindings\/sync\?/,
        reply: () =>
          statusWith({ ...PLAN, status: 'conflicted', conflict_count: 1, unresolved_count: 1 }, [
            { ...CONFLICT, draft_kind: 'deletion', draft_value: null },
          ]),
      },
    ]);
    await renderPanel();
    const row = await screen.findByTestId('sync-conflict-k1');
    expect(within(row).getByText('removed')).toBeInTheDocument();
  });
});

describe('never overwriting work that already exists', () => {
  it('warns when the draft has been edited since the merge ran', async () => {
    installFetch([
      { test: /\/bindings\/sync\?/, reply: () => statusWith({ ...PLAN, stale: true }) },
    ]);
    await renderPanel();
    expect(await screen.findByTestId('sync-stale')).toHaveTextContent(
      /describes a document that no longer exists/
    );
  });

  it('surfaces the guard a recorded review decision puts on a result', async () => {
    installFetch([
      { test: /\/bindings\/sync\?/, reply: () => statusWith({ ...PLAN, guard: 'review_decided' }) },
    ]);
    await renderPanel();
    expect(await screen.findByTestId('sync-guard')).toHaveTextContent(/reviewer has already/i);
  });

  it('says a published version is no longer a draft', async () => {
    installFetch([
      {
        test: /\/bindings\/sync\?/,
        reply: () => statusWith({ ...PLAN, guard: 'version_published' }),
      },
    ]);
    await renderPanel();
    expect(await screen.findByTestId('sync-guard')).toHaveTextContent(/published/);
  });

  it('shows no guard at all for an ordinary draft', async () => {
    installFetch([{ test: /\/bindings\/sync\?/, reply: () => statusWith() }]);
    await renderPanel();
    await screen.findByTestId('sync-plan');
    expect(screen.queryByTestId('sync-guard')).not.toBeInTheDocument();
  });
});

describe('refusals', () => {
  it('explains a rewritten merge base in words a reader can act on', async () => {
    installFetch([
      {
        test: /\/bindings\/sync\?/,
        reply: (_url, init) =>
          init?.method === 'POST'
            ? { success: false, code: 'sync-base-drifted', error: 'drifted' }
            : { success: true, version_id: VERSION_ID, bound: true, latest: null, history: [] },
        status: 200,
      },
    ]);
    await renderPanel();
    fireEvent.click(screen.getByTestId('sync-merge'));
    expect(await screen.findByTestId('sync-error')).toHaveTextContent(/branch was rewritten/);
  });

  it('says what to do when the stored credential cannot read the repository', async () => {
    installFetch([
      {
        test: /\/bindings\/sync\?/,
        reply: (_url, init) =>
          init?.method === 'POST'
            ? { success: false, code: 'binding-repository-forbidden', error: 'no access' }
            : { success: true, version_id: VERSION_ID, bound: true, latest: null, history: [] },
      },
    ]);
    await renderPanel();
    fireEvent.click(screen.getByTestId('sync-merge'));
    expect(await screen.findByTestId('sync-error')).toHaveTextContent(/Re-link the account/);
  });
});

describe('earlier merges', () => {
  it('keeps the results before this one on the screen', async () => {
    installFetch([
      {
        test: /\/bindings\/sync\?/,
        reply: () =>
          statusWith(PLAN, [], [
            { ...PLAN, id: 'p0', status: 'clean', created_at: '2026-09-15T10:00:00Z' },
          ]),
      },
    ]);
    await renderPanel();

    const history = await screen.findByTestId('sync-history');
    expect(within(history).getByText('Nothing to merge')).toBeInTheDocument();
    expect(within(history).getByText('1111111 → 2222222')).toBeInTheDocument();
  });

  it('offers to merge again once there is a result', async () => {
    installFetch([{ test: /\/bindings\/sync\?/, reply: () => statusWith() }]);
    await renderPanel();
    fireEvent.click(await screen.findByTestId('sync-refresh'));
    await waitFor(() => expect(calls.some((call) => call.init?.method === 'POST')).toBe(true));
    expect(lastBody()).toEqual({ refresh: true });
  });
});
