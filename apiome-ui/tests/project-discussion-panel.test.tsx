/**
 * The Project Discussion panel, rendered (COL-1.3, #4515).
 *
 * `comment-discussion-model.test.ts` holds the rules and `discussion-css.test.ts` the declarations;
 * this mounts the real `ProjectDiscussionPanel` against mocked BFF routes and pins the ticket's
 * acceptance criteria:
 *
 *   1. **Every thread of the project is listed with working filters** — each chip (status,
 *      mentions me, element type) re-reads the list with exactly that filter, and "load more"
 *      pages through the rest.
 *   2. **Clicking a thread lands in Studio with the element focused and the popover open** — each
 *      row's link is the COL-1.2 deep link (an orphaned thread's opens its version).
 *   3. **Counts agree with the per-element badges** — the chips, each row's "N unresolved on this
 *      element" and the tab total are the summary route's numbers, drawn as given.
 *
 * With `DISCUSSION_FIXTURE_DUMP=1` it also writes the rendered panel to
 * `e2e/fixtures/project-discussion/` for `e2e/project-discussion.spec.ts`:
 *
 *     DISCUSSION_FIXTURE_DUMP=1 npx jest -c jest.config.ts tests/project-discussion-panel.test.tsx -t fixtures
 */

import * as fs from 'fs';
import * as path from 'path';
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { ProjectDiscussionPanel } from '../src/app/components/ade/discussion/ProjectDiscussionPanel';
import { formatVersionWithPrefix } from '../src/app/utils/version-display';
import type { DiscussionThread } from '../lib/comment-discussion';

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const REV_1 = '11111111-1111-4111-8111-111111111111';
const REV_2 = '22222222-2222-4222-8222-222222222222';
const WORKSPACE = 'https://suite.test/workspace';
const NOW = Date.parse('2026-09-14T12:00:00Z');

const VERSIONS = [
  { id: REV_1, version_id: '1.0.0' },
  { id: REV_2, version_id: '2.0.0' },
];

/**
 * A thread row as the list route returns it.
 *
 * @param overrides - Fields to change.
 * @returns The thread.
 */
function thread(overrides: Partial<DiscussionThread>): DiscussionThread {
  return {
    id: 'thread-x',
    project_id: PROJECT_ID,
    version_id: REV_2,
    anchor_type: 'class',
    anchor_id: 'class-customer',
    status: 'open',
    anchor_label: null,
    orphaned_at: null,
    created_by: 'u-jane',
    created_by_name: 'Jane Doe',
    resolved_by: null,
    resolved_at: null,
    created_at: '2026-09-10T12:00:00Z',
    last_activity_at: '2026-09-12T12:00:00Z',
    comment_count: 3,
    root_comment: {
      id: 'c-1',
      thread_id: 'thread-x',
      author_id: 'u-jane',
      author_name: 'Jane Doe',
      body: 'Should nickname be nullable, @bob?',
      mentions: ['u-bob'],
      edited_at: null,
      created_at: '2026-09-10T12:00:00Z',
    },
    anchor_context: { label: 'Customer', className: 'Customer' },
    ...overrides,
  };
}

const CLASS_THREAD = thread({ id: 'thread-class' });
const OPERATION_THREAD = thread({
  id: 'thread-operation',
  anchor_type: 'operation',
  anchor_id: 'op-get-customer',
  version_id: REV_1,
  comment_count: 1,
  root_comment: null,
  created_by_name: 'Bob Brown',
  anchor_context: { label: 'GET /customers/{id}', pathname: '/customers/{id}', method: 'GET' },
});
const ORPHANED_THREAD = thread({
  id: 'thread-orphaned',
  anchor_type: 'property',
  anchor_id: 'prop-gone',
  status: 'orphaned',
  anchor_label: 'Customer.nickname',
  anchor_context: null,
});

const SUMMARY = {
  success: true,
  statusTotals: { open: 2, resolved: 5, orphaned: 1 },
  unresolvedTotal: 2,
  unresolvedByAnchor: { 'class:class-customer': 2, 'operation:op-get-customer': 1 },
  truncated: false,
};

type Route = { test: RegExp; reply: (url: string) => unknown };

let routes: Route[] = [];
let calls: string[] = [];

/**
 * Install a fetch mock answering the BFF routes.
 *
 * @param extra - Routes that take precedence over the defaults.
 */
function installFetch(extra: Route[] = []) {
  routes = [
    {
      test: /\/comment-threads\?/,
      reply: () => ({ success: true, threads: [CLASS_THREAD, OPERATION_THREAD, ORPHANED_THREAD], total: 3, count: 3 }),
    },
    { test: /\/comment-threads\/summary/, reply: () => SUMMARY },
    ...extra,
  ];
  calls = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    calls.push(url);
    for (const route of [...routes].reverse()) {
      if (route.test.test(url)) {
        return { ok: true, status: 200, json: async () => route.reply(url) } as unknown as Response;
      }
    }
    return { ok: false, status: 404, json: async () => ({ success: false, error: `unrouted ${url}` }) } as unknown as Response;
  }) as unknown as typeof fetch;
}

/** The list-route URLs requested so far. */
function listCalls(): string[] {
  return calls.filter((url) => /\/comment-threads\?/.test(url));
}

/** The summary-route URLs requested so far. */
function summaryCalls(): string[] {
  return calls.filter((url) => /\/comment-threads\/summary/.test(url));
}

/**
 * Render the panel and wait for its first list.
 *
 * @param props - Props to change.
 * @returns The render result.
 */
async function renderPanel(props: Partial<React.ComponentProps<typeof ProjectDiscussionPanel>> = {}) {
  const view = render(
    <ProjectDiscussionPanel projectId={PROJECT_ID} versions={VERSIONS} workspaceRoute={WORKSPACE} now={NOW} {...props} />
  );
  await screen.findByTestId('discussion-thread-list');
  return view;
}

beforeEach(() => {
  installFetch();
});

describe('the list', () => {
  it('reads the open threads of the project first', async () => {
    await renderPanel();
    expect(listCalls()).toEqual([`/api/projects/${PROJECT_ID}/comment-threads?status=open&limit=50&offset=0`]);
    expect(summaryCalls()).toEqual([`/api/projects/${PROJECT_ID}/comment-threads/summary`]);
    expect(screen.getByTestId('discussion-status-open')).toHaveAttribute('aria-pressed', 'true');
  });

  it("narrows the list and the counts to one version for the review page's Discussion tab (COL-2.2)", async () => {
    await renderPanel({ versionId: REV_2 });
    expect(listCalls()).toEqual([
      `/api/projects/${PROJECT_ID}/comment-threads?status=open&version=${REV_2}&limit=50&offset=0`,
    ]);
    expect(summaryCalls()).toEqual([`/api/projects/${PROJECT_ID}/comment-threads/summary?version=${REV_2}`]);
  });

  it('draws each thread: element, kind, status, version, opening comment, author, activity, replies', async () => {
    await renderPanel();
    const row = screen.getByTestId('discussion-thread-thread-class');
    expect(within(row).getByText('Customer')).toBeInTheDocument();
    expect(within(row).getByText('Class')).toBeInTheDocument();
    expect(within(row).getByText('Open')).toBeInTheDocument();
    expect(within(row).getByText(formatVersionWithPrefix('2.0.0'))).toBeInTheDocument();
    expect(within(row).getByText('Should nickname be nullable, @bob?')).toBeInTheDocument();
    expect(within(row).getByText('Jane Doe')).toBeInTheDocument();
    expect(within(row).getByText('Active 2d ago')).toHaveAttribute('dateTime', '2026-09-12T12:00:00Z');
    expect(within(row).getByText('2 replies')).toBeInTheDocument();

    const operation = screen.getByTestId('discussion-thread-thread-operation');
    expect(within(operation).getByText('GET /customers/{id}')).toHaveClass('mono');
    expect(within(operation).getByText(formatVersionWithPrefix('1.0.0'))).toBeInTheDocument();
    expect(within(operation).getByText('Bob Brown')).toBeInTheDocument();
    expect(within(operation).getByText('No replies')).toBeInTheDocument();

    const orphaned = screen.getByTestId('discussion-thread-thread-orphaned');
    expect(within(orphaned).getByText('Customer.nickname')).toBeInTheDocument();
    expect(within(orphaned).getByText('Orphaned')).toBeInTheDocument();
  });

  it('names a version it does not know by revision id', async () => {
    installFetch([
      {
        test: /\/comment-threads\?/,
        reply: () => ({ success: true, total: 1, threads: [thread({ id: 'lost', version_id: '99999999-aaaa-4aaa-8aaa-aaaaaaaaaaaa' })] }),
      },
    ]);
    await renderPanel();
    expect(screen.getByText('Revision 99999999')).toBeInTheDocument();
  });
});

describe('deep links into Studio', () => {
  it('links a live thread with its element selected and its popover open', async () => {
    await renderPanel();
    const link = within(screen.getByTestId('discussion-thread-thread-class')).getByTestId('discussion-thread-link');
    const url = new URL(link.getAttribute('href') ?? '');
    expect(`${url.origin}${url.pathname}`).toBe(WORKSPACE);
    expect(url.searchParams.get('projectId')).toBe(PROJECT_ID);
    expect(url.searchParams.get('versionId')).toBe(REV_2);
    expect(url.searchParams.get('lens')).toBe('schemas');
    expect(url.searchParams.get('sel')).toBe(`${REV_2}|%2Fcomponents%2Fschemas%2FCustomer|class-customer`);
    expect(url.searchParams.get('comment')).toBe('class:class-customer');
    expect(url.searchParams.get('thread')).toBe('thread-class');
    expect(link).toHaveTextContent('Customer, open in Studio');
  });

  it('links an operation through the paths lens', async () => {
    await renderPanel();
    const link = within(screen.getByTestId('discussion-thread-thread-operation')).getByTestId('discussion-thread-link');
    const url = new URL(link.getAttribute('href') ?? '');
    expect(url.searchParams.get('lens')).toBe('paths');
    expect(url.searchParams.get('comment')).toBe('operation:op-get-customer');
  });

  it("links an orphaned thread to its version, where the Studio lists it", async () => {
    await renderPanel();
    const link = within(screen.getByTestId('discussion-thread-thread-orphaned')).getByTestId('discussion-thread-link');
    expect(link).toHaveAttribute('href', `${WORKSPACE}?projectId=${PROJECT_ID}&versionId=${REV_2}`);
    expect(link).toHaveTextContent('open its version in Studio');
  });

  it('draws names without links when there is no Studio', async () => {
    await renderPanel({ workspaceRoute: null });
    expect(screen.queryAllByTestId('discussion-thread-link')).toHaveLength(0);
    expect(screen.getByText('Customer')).toBeInTheDocument();
  });
});

describe('counts', () => {
  it('draws the summary on the chips, on each row, and reports the tab total', async () => {
    const onTotal = jest.fn();
    await renderPanel({ onUnresolvedTotalChange: onTotal });
    await waitFor(() => expect(screen.getByTestId('discussion-status-open')).toHaveTextContent('Open2'));
    expect(screen.getByTestId('discussion-status-resolved')).toHaveTextContent('Resolved5');
    expect(screen.getByTestId('discussion-status-orphaned')).toHaveTextContent('Orphaned1');
    expect(screen.getByTestId('discussion-status-all')).toHaveTextContent('All8');
    expect(onTotal).toHaveBeenCalledWith(2);

    expect(
      within(screen.getByTestId('discussion-thread-thread-class')).getByTestId('discussion-thread-unresolved')
    ).toHaveTextContent('2 unresolved on this element');
    expect(
      within(screen.getByTestId('discussion-thread-thread-operation')).getByTestId('discussion-thread-unresolved')
    ).toHaveTextContent('1 unresolved on this element');
    expect(
      within(screen.getByTestId('discussion-thread-thread-orphaned')).queryByTestId('discussion-thread-unresolved')
    ).toBeNull();
  });

  it('keeps the list when the summary fails, without numbers', async () => {
    installFetch([{ test: /\/comment-threads\/summary/, reply: () => ({ success: false, error: 'nope' }) }]);
    await renderPanel();
    await waitFor(() => expect(summaryCalls()).toHaveLength(1));
    expect(screen.getByTestId('discussion-status-open')).toHaveTextContent(/^Open$/);
    expect(screen.queryAllByTestId('discussion-thread-unresolved')).toHaveLength(0);
  });

  it('says when per-element counts were capped', async () => {
    installFetch([{ test: /\/comment-threads\/summary/, reply: () => ({ ...SUMMARY, truncated: true }) }]);
    await renderPanel();
    expect(await screen.findByTestId('discussion-truncated')).toHaveTextContent('first 2,000 unresolved threads');
  });
});

describe('filters', () => {
  it('re-reads the list for a status, without re-reading the counts', async () => {
    await renderPanel();
    await waitFor(() => expect(summaryCalls()).toHaveLength(1));
    fireEvent.click(screen.getByTestId('discussion-status-resolved'));
    await waitFor(() =>
      expect(listCalls()).toContain(`/api/projects/${PROJECT_ID}/comment-threads?status=resolved&limit=50&offset=0`)
    );
    expect(screen.getByTestId('discussion-status-resolved')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('discussion-status-open')).toHaveAttribute('aria-pressed', 'false');
    expect(summaryCalls()).toHaveLength(1);

    fireEvent.click(screen.getByTestId('discussion-status-all'));
    await waitFor(() => expect(listCalls()).toContain(`/api/projects/${PROJECT_ID}/comment-threads?limit=50&offset=0`));
  });

  it('narrows to threads that mention the viewer, list and counts alike', async () => {
    await renderPanel();
    fireEvent.click(screen.getByTestId('discussion-mentions-me'));
    await waitFor(() =>
      expect(listCalls()).toContain(
        `/api/projects/${PROJECT_ID}/comment-threads?status=open&mentions_me=true&limit=50&offset=0`
      )
    );
    await waitFor(() =>
      expect(summaryCalls()).toContain(`/api/projects/${PROJECT_ID}/comment-threads/summary?mentions_me=true`)
    );
    expect(screen.getByTestId('discussion-mentions-me')).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByTestId('discussion-mentions-me'));
    expect(screen.getByTestId('discussion-mentions-me')).toHaveAttribute('aria-pressed', 'false');
  });

  it('narrows to one element type', async () => {
    await renderPanel();
    fireEvent.click(screen.getByTestId('discussion-element-operation'));
    await waitFor(() =>
      expect(listCalls()).toContain(
        `/api/projects/${PROJECT_ID}/comment-threads?status=open&anchor_type=operation&limit=50&offset=0`
      )
    );
    await waitFor(() =>
      expect(summaryCalls()).toContain(`/api/projects/${PROJECT_ID}/comment-threads/summary?anchor_type=operation`)
    );
    expect(screen.getByTestId('discussion-element-operation')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('discussion-element-all')).toHaveAttribute('aria-pressed', 'false');
  });

  it('groups the chips for assistive technology', async () => {
    await renderPanel();
    expect(screen.getByRole('group', { name: 'Thread status' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Element type' })).toBeInTheDocument();
  });
});

describe('states', () => {
  it('shows the loading state until the list arrives', () => {
    global.fetch = jest.fn(() => new Promise(() => undefined)) as unknown as typeof fetch;
    render(<ProjectDiscussionPanel projectId={PROJECT_ID} versions={VERSIONS} workspaceRoute={WORKSPACE} now={NOW} />);
    expect(screen.getByText('Loading comment threads…')).toBeInTheDocument();
  });

  it('says there is nothing to resolve, and adapts the sentence to the filters', async () => {
    installFetch([{ test: /\/comment-threads\?/, reply: () => ({ success: true, threads: [], total: 0 }) }]);
    render(<ProjectDiscussionPanel projectId={PROJECT_ID} versions={VERSIONS} workspaceRoute={WORKSPACE} now={NOW} />);
    expect(await screen.findByText('Nothing to resolve. Start a thread on an element in Studio.')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('discussion-mentions-me'));
    expect(await screen.findByText('No thread matching these filters mentions you.')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('discussion-mentions-me'));
    fireEvent.click(screen.getByTestId('discussion-status-resolved'));
    expect(await screen.findByText('No threads match these filters.')).toBeInTheDocument();
  });

  it('shows the error the route reports', async () => {
    installFetch([{ test: /\/comment-threads\?/, reply: () => ({ success: false, error: 'Project not found' }) }]);
    render(<ProjectDiscussionPanel projectId={PROJECT_ID} versions={VERSIONS} workspaceRoute={WORKSPACE} now={NOW} />);
    expect(await screen.findByTestId('discussion-error')).toHaveTextContent('Project not found');
  });
});

describe('load more', () => {
  it('appends the next page until every thread is shown', async () => {
    installFetch([
      {
        test: /\/comment-threads\?/,
        reply: (url) =>
          url.includes('offset=0')
            ? { success: true, total: 4, threads: [CLASS_THREAD, OPERATION_THREAD, ORPHANED_THREAD] }
            : { success: true, total: 4, threads: [ORPHANED_THREAD, thread({ id: 'thread-late' })] },
      },
    ]);
    await renderPanel();
    expect(screen.getByTestId('discussion-shown')).toHaveTextContent('Showing 3 of 4');

    fireEvent.click(screen.getByTestId('discussion-load-more'));
    await screen.findByTestId('discussion-thread-thread-late');
    expect(listCalls()).toContain(`/api/projects/${PROJECT_ID}/comment-threads?status=open&limit=50&offset=3`);
    // The repeated row is not drawn twice.
    expect(screen.getAllByTestId('discussion-thread-thread-orphaned')).toHaveLength(1);
    expect(screen.queryByTestId('discussion-load-more')).toBeNull();
  });

  it('keeps the list and says so when the next page fails', async () => {
    installFetch([
      {
        test: /\/comment-threads\?/,
        reply: (url) =>
          url.includes('offset=0')
            ? { success: true, total: 9, threads: [CLASS_THREAD] }
            : { success: false, error: 'Rate limited' },
      },
    ]);
    await renderPanel();
    fireEvent.click(screen.getByTestId('discussion-load-more'));
    expect(await screen.findByTestId('discussion-more-error')).toHaveTextContent('Rate limited');
    expect(screen.getByTestId('discussion-thread-thread-class')).toBeInTheDocument();
    expect(screen.getByTestId('discussion-load-more')).not.toBeDisabled();
  });
});

describe('fixtures', () => {
  it('renders the fixture the e2e suite measures', async () => {
    installFetch([
      {
        test: /\/comment-threads\?/,
        reply: () => ({
          success: true,
          total: 12,
          threads: [
            CLASS_THREAD,
            OPERATION_THREAD,
            ORPHANED_THREAD,
            thread({
              id: 'thread-long',
              anchor_type: 'path',
              anchor_id: 'path-long',
              status: 'resolved',
              anchor_context: {
                label: '/tenants/{tenantSlug}/projects/{projectRef}/versions/{versionId}/comment-threads/{threadId}/comments',
                pathname:
                  '/tenants/{tenantSlug}/projects/{projectRef}/versions/{versionId}/comment-threads/{threadId}/comments',
              },
              root_comment: {
                id: 'c-long',
                thread_id: 'thread-long',
                author_id: 'u-ada',
                author_name: 'Ada Lovelace',
                body: 'An unbroken token: '.concat('x'.repeat(240)),
                mentions: [],
                edited_at: null,
                created_at: '2026-09-01T12:00:00Z',
              },
            }),
          ],
        }),
      },
      { test: /\/comment-threads\/summary/, reply: () => ({ ...SUMMARY, truncated: true }) },
    ]);
    const { container } = await renderPanel();
    await screen.findByTestId('discussion-truncated');
    expect(screen.getByTestId('discussion-load-more')).toBeInTheDocument();

    if (process.env.DISCUSSION_FIXTURE_DUMP === '1') {
      const dir = path.join(__dirname, '..', 'e2e', 'fixtures', 'project-discussion');
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, 'panel.html'), `${container.innerHTML}\n`);
    }
  });
});
