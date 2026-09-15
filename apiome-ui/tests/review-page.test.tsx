/**
 * The review page, rendered (COL-2.2, #4518).
 *
 * `review-page-model.test.ts` holds the rules and `review-page-css.test.ts` the declarations; this
 * mounts the real `ReviewPageClient` against mocked BFF routes and pins the ticket's acceptance
 * criteria in a DOM:
 *
 *   1. **A reviewer completes a decision entirely on this page** — Approve, and Request changes
 *      with its required note, each recorded from the sticky bar with the header, the reviewers
 *      card and the bar updating in place.
 *   2. **The diff tab lazy-loads** — no pane reads anything until its tab is shown, and the plain
 *      diff's documents are only built when the plain diff is shown.
 *   3. The header (version, requester, state), the Changes / Spec / Discussion tabs, the decision
 *      bar's read-only states, refusals, and loading failures.
 *
 * `e2e/journey/review-page.spec.ts` drives the same two decisions against the real stack.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import type { ReviewDetail, ReviewerDecisionRow } from '../lib/review-page';

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

jest.mock('@/app/components/ui/code/JsonDiffViewer', () => ({
  JsonDiffViewer: ({ original, modified }: { original: string; modified: string }) =>
    // jest.mock factories cannot close over imports, so React is required inside the factory.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').createElement('div', {
      'data-testid': 'json-diff-viewer',
      'data-original': original,
      'data-modified': modified,
    }),
}));

jest.mock('@/app/components/ade/dashboard/export/ReadOnlyCodeViewer', () => ({
  ReadOnlyCodeViewer: ({ value, language, documentLabel }: { value: string; language: string; documentLabel: string }) =>
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').createElement(
      'pre',
      { 'data-testid': 'read-only-code', 'data-language': language, 'data-label': documentLabel },
      value
    ),
}));

jest.mock('@lib/external-links', () => ({
  getStudioWorkspaceRoute: () => 'https://suite.test/workspace',
}));

import { toast } from 'sonner';
import ReviewPageClient from '../src/app/components/ade/reviews/ReviewPageClient';

const REVIEW_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const HEAD = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const VIEWER = '11111111-1111-4111-8111-111111111111';
const DANA = '22222222-2222-4222-8222-222222222222';
const BASE = `/api/reviews/${REVIEW_ID}`;

/**
 * A reviewer row.
 *
 * @param overrides - Fields to change.
 * @returns The row.
 */
function row(overrides: Partial<ReviewerDecisionRow>): ReviewerDecisionRow {
  return {
    id: 'row-ravi',
    review_id: REVIEW_ID,
    round: 2,
    user_id: VIEWER,
    user_name: 'Ravi Reviewer',
    decision: 'pending',
    note: null,
    decided_at: null,
    created_at: '2026-09-14T10:00:00Z',
    ...overrides,
  };
}

/**
 * A review as the BFF answers with it.
 *
 * @param overrides - Fields of the detail to change; `review` fields merge.
 * @returns The detail.
 */
function detail(overrides: Partial<Omit<ReviewDetail, 'review'>> & { review?: Partial<ReviewDetail['review']> } = {}): ReviewDetail {
  const { review, ...rest } = overrides;
  return {
    review: {
      id: REVIEW_ID,
      tenant_id: 't-1',
      project_id: PROJECT_ID,
      version_id: HEAD,
      version_label: '2.0.0',
      requested_by: 'u-rae',
      requested_by_name: 'Rae Requester',
      state: 'in_review',
      round: 2,
      spec_fingerprint: 'sha256:b',
      reviewer_count: 2,
      approved_count: 0,
      changes_requested_count: 0,
      pending_count: 2,
      closed_at: null,
      closed_by: null,
      created_at: '2026-09-10T10:00:00Z',
      updated_at: '2026-09-14T10:00:00Z',
      ...review,
    },
    reviewers: [row({}), row({ id: 'row-dana', user_id: DANA, user_name: 'Dana Doe' })],
    history: [
      row({ id: 'old-ravi', round: 1, decision: 'request_changes', note: 'Rename id to petId', decided_at: '2026-09-11T10:00:00Z' }),
      row({ id: 'old-dana', round: 1, user_id: DANA, user_name: 'Dana Doe' }),
    ],
    spec_changed: false,
    ...rest,
  };
}

const CHANGES = {
  success: true,
  head: { id: HEAD, label: '2.0.0' },
  baseline: { id: 'base-1', label: '1.1.0' },
  initialPublication: false,
  changes: [
    { ruleId: 'property-added', severity: 'non-breaking', pointer: '/components/schemas/Pet/properties/tag' },
    { ruleId: 'operation-removed', severity: 'breaking', pointer: '/paths/~1pets/delete' },
    { ruleId: 'response-removed', severity: 'breaking', pointer: '/paths/~1pets/get/responses/404' },
  ],
  counts: { breaking: 2, 'non-breaking': 1, 'docs-only': 0, total: 3 },
  maxSeverity: 'breaking',
  classifiedError: null,
};

type Call = { url: string; method: string; body: unknown };
type Route = { test: RegExp; method?: string; reply: (call: Call) => unknown };

let routes: Route[] = [];
let calls: Call[] = [];

/**
 * Install a fetch mock answering the BFF routes.
 *
 * @param extra - Routes that take precedence over the defaults.
 */
function installFetch(extra: Route[] = []) {
  routes = [
    { test: new RegExp(`${BASE}$`), reply: () => ({ success: true, review: detail(), project: { id: PROJECT_ID, name: 'Pets API', slug: 'pets' }, viewerId: VIEWER }) },
    { test: /\/changes$/, reply: () => CHANGES },
    { test: /\/spec\?side=head$/, reply: () => ({ success: true, side: 'head', spec: '{\n  "openapi": "3.1.0"\n}' }) },
    { test: /\/spec\?side=base$/, reply: () => ({ success: true, side: 'base', spec: '{\n  "openapi": "3.0.0"\n}' }) },
    { test: /\/comment-threads\?/, reply: () => ({ success: true, threads: [], total: 0, count: 0 }) },
    { test: /\/comment-threads\/summary/, reply: () => ({ success: true, statusTotals: { open: 0, resolved: 0, orphaned: 0 }, unresolvedTotal: 0, unresolvedByAnchor: {}, truncated: false }) },
    ...extra,
  ];
  calls = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const call: Call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    for (const route of [...routes].reverse()) {
      if (route.test.test(url) && (!route.method || route.method === call.method)) {
        return { ok: true, status: 200, json: async () => route.reply(call) } as unknown as Response;
      }
    }
    return { ok: false, status: 404, json: async () => ({ success: false, error: `unrouted ${url}` }) } as unknown as Response;
  }) as unknown as typeof fetch;
}

/** The URLs requested so far that match a pattern. */
function urls(pattern: RegExp): string[] {
  return calls.filter((call) => pattern.test(call.url)).map((call) => call.url);
}

/**
 * Render the page and wait for the review to load.
 *
 * @param props - Props to change.
 */
async function renderPage(props: Partial<React.ComponentProps<typeof ReviewPageClient>> = {}) {
  const view = render(<ReviewPageClient reviewId={REVIEW_ID} {...props} />);
  await screen.findByRole('heading', { name: /^Review of v2\.0\.0/ });
  return view;
}

beforeEach(() => {
  jest.clearAllMocks();
  installFetch();
  Object.assign(navigator, { clipboard: { writeText: jest.fn(async () => undefined) } });
});

describe('the header', () => {
  it('names the version, its state, the requester, the round and the tally', async () => {
    await renderPage();
    expect(screen.getByTestId('review-status')).toHaveTextContent('In review');
    expect(screen.getByTestId('review-summary')).toHaveTextContent('Requested by Rae Requester · Round 2 · 0 of 2 approved · 2 pending');
    const crumbs = screen.getByRole('navigation', { name: /breadcrumb/i });
    expect(within(crumbs).getByRole('link', { name: 'Pets API' })).toHaveAttribute(
      'href',
      `/ade/dashboard/versions?projectId=${PROJECT_ID}`
    );
  });

  it('shows a loading failure with the refusal in words, and retries', async () => {
    installFetch([{ test: new RegExp(`${BASE}$`), reply: () => ({ success: false, error: 'Review not found', code: 'review-not-found' }) }]);
    render(<ReviewPageClient reviewId={REVIEW_ID} />);
    expect(await screen.findByText('This review does not exist, or it belongs to another workspace.')).toBeInTheDocument();
    installFetch();
    fireEvent.click(screen.getByRole('button', { name: /try again|retry/i }));
    expect(await screen.findByRole('heading', { name: /^Review of v2\.0\.0/ })).toBeInTheDocument();
  });
});

describe('tabs load lazily', () => {
  it('opens Changes and reads only the comparison', async () => {
    await renderPage();
    await screen.findByTestId('review-classified');
    expect(urls(/\/changes$/)).toEqual([`${BASE}/changes`]);
    expect(urls(/\/spec/)).toEqual([]);
    expect(urls(/comment-threads/)).toEqual([]);
    expect(screen.getByTestId('review-tab-changes')).toHaveAttribute('aria-selected', 'true');
  });

  it('opens a deep-linked tab first and reads nothing for the others', async () => {
    await renderPage({ initialTab: 'discussion' });
    await screen.findByTestId('project-discussion-panel');
    expect(urls(/comment-threads\?/)).toEqual([`/api/projects/${PROJECT_ID}/comment-threads?status=open&version=${HEAD}&limit=50&offset=0`]);
    expect(urls(/\/changes$/)).toEqual([]);
  });

  it('mounts a pane on first view and keeps it, without reading it again', async () => {
    await renderPage();
    await screen.findByTestId('review-classified');
    fireEvent.click(screen.getByTestId('review-tab-spec'));
    await screen.findByTestId('review-spec');
    fireEvent.click(screen.getByTestId('review-tab-changes'));
    fireEvent.click(screen.getByTestId('review-tab-spec'));
    expect(urls(/\/changes$/)).toHaveLength(1);
    expect(urls(/\/spec\?side=head$/)).toHaveLength(1);
    expect(screen.getByTestId('review-pane-changes')).not.toBeVisible();
  });

  it('moves between tabs with the arrow keys and records the tab in the address', async () => {
    await renderPage();
    const changes = screen.getByTestId('review-tab-changes');
    fireEvent.keyDown(changes, { key: 'ArrowRight' });
    expect(screen.getByTestId('review-tab-spec')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('review-tab-spec')).toHaveFocus();
    expect(window.location.search).toContain('tab=spec');
    fireEvent.keyDown(screen.getByTestId('review-tab-spec'), { key: 'End' });
    expect(screen.getByTestId('review-tab-discussion')).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(screen.getByTestId('review-tab-discussion'), { key: 'ArrowRight' });
    expect(screen.getByTestId('review-tab-changes')).toHaveAttribute('aria-selected', 'true');
  });
});

describe('the Changes tab', () => {
  it('lists breaking changes first, grouped by path, against the newest published version', async () => {
    await renderPage();
    const classified = await screen.findByTestId('review-classified');
    expect(screen.getByTestId('review-changes-compare')).toHaveTextContent('Compared with v1.1.0, the newest published version · 2 breaking · 1 non-breaking');
    const sections = within(classified).getAllByRole('region');
    expect(sections.map((section) => section.getAttribute('data-testid'))).toEqual([
      'review-severity-breaking',
      'review-severity-non-breaking',
    ]);
    const breaking = screen.getByTestId('review-severity-breaking');
    expect(within(breaking).getByText('2 changes')).toBeInTheDocument();
    expect(within(breaking).getByText('paths › /pets')).toBeInTheDocument();
    expect(within(breaking).getByText('Operation removed')).toBeInTheDocument();
    expect(within(breaking).getByText('paths › /pets › get › responses › 404')).toBeInTheDocument();
  });

  it('builds the two documents only when the plain diff is shown', async () => {
    await renderPage();
    await screen.findByTestId('review-classified');
    expect(urls(/\/spec/)).toEqual([]);
    fireEvent.click(screen.getByTestId('review-view-plain'));
    const viewer = await screen.findByTestId('json-diff-viewer');
    expect(viewer).toHaveAttribute('data-original', '{\n  "openapi": "3.0.0"\n}');
    expect(viewer).toHaveAttribute('data-modified', '{\n  "openapi": "3.1.0"\n}');
    expect(urls(/\/spec/).sort()).toEqual([`${BASE}/spec?side=base`, `${BASE}/spec?side=head`]);
  });

  it('falls back to the plain diff, saying why, when classification failed', async () => {
    installFetch([{ test: /\/changes$/, reply: () => ({ ...CHANGES, changes: [], counts: {}, classifiedError: 'Missing permission' }) }]);
    await renderPage();
    expect(await screen.findByTestId('review-classified-error')).toHaveTextContent('Missing permission');
    expect(screen.getByTestId('review-view-classified')).toBeDisabled();
    expect(await screen.findByTestId('json-diff-viewer')).toBeInTheDocument();
  });

  it('says this would be the first publication when nothing is published', async () => {
    installFetch([{ test: /\/changes$/, reply: () => ({ ...CHANGES, baseline: null, initialPublication: true, changes: [] }) }]);
    await renderPage();
    expect(await screen.findByTestId('review-changes-initial')).toHaveTextContent('First publication');
  });

  it('says so when nothing changed', async () => {
    installFetch([{ test: /\/changes$/, reply: () => ({ ...CHANGES, changes: [], counts: { total: 0 } }) }]);
    await renderPage();
    expect(await screen.findByTestId('review-changes-none')).toHaveTextContent("This version's document matches v1.1.0.");
  });
});

describe('the Spec tab', () => {
  it('shows the document read-only, in JSON or YAML, and copies it', async () => {
    await renderPage({ initialTab: 'spec' });
    const code = await screen.findByTestId('read-only-code');
    expect(code).toHaveAttribute('data-language', 'json');
    expect(code).toHaveAttribute('data-label', 'pets-2-0-0-openapi.json');
    expect(code).toHaveTextContent('"openapi": "3.1.0"');

    fireEvent.click(screen.getByTestId('review-spec-format-yaml'));
    expect(screen.getByTestId('read-only-code')).toHaveAttribute('data-language', 'yaml');
    expect(screen.getByTestId('read-only-code')).toHaveTextContent('openapi: 3.1.0');

    fireEvent.click(screen.getByTestId('review-spec-copy'));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith('openapi: 3.1.0\n'));
  });

  it('shows why the document could not be built', async () => {
    installFetch([{ test: /\/spec\?side=head$/, reply: () => ({ success: false, error: 'Forbidden' }) }]);
    await renderPage({ initialTab: 'spec' });
    expect(await screen.findByTestId('review-spec-error')).toHaveTextContent('Forbidden');
  });
});

describe('deciding', () => {
  it('approves with an optional note, updating the page in place', async () => {
    const after = detail({
      review: { approved_count: 1, pending_count: 1 },
      reviewers: [row({ decision: 'approve', note: 'Looks right', decided_at: '2026-09-14T11:00:00Z' }), row({ id: 'row-dana', user_id: DANA, user_name: 'Dana Doe' })],
    });
    installFetch([{ test: /\/decision$/, method: 'POST', reply: () => ({ success: true, review: after }) }]);
    await renderPage();

    fireEvent.change(screen.getByTestId('review-decision-note'), { target: { value: 'Looks right' } });
    fireEvent.click(screen.getByTestId('review-approve'));

    expect(await screen.findByText('You approved this round.')).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST')).toEqual([
      { url: `${BASE}/decision`, method: 'POST', body: { decision: 'approve', note: 'Looks right' } },
    ]);
    expect(screen.getByTestId('review-summary')).toHaveTextContent('1 of 2 approved · 1 pending');
    expect(screen.getByTestId('review-decision-own-note')).toHaveTextContent('Looks right');
    expect(within(screen.getByTestId('review-reviewer-row-ravi')).getByText('Approved')).toBeInTheDocument();
    expect(toast.success).toHaveBeenCalledWith('You approved this version.');
    expect(screen.queryByTestId('review-approve')).not.toBeInTheDocument();
  });

  it('requires a note to request changes, then sends it', async () => {
    const after = detail({
      review: { state: 'changes_requested', changes_requested_count: 1, pending_count: 1 },
      reviewers: [row({ decision: 'request_changes', note: 'Keep Pet', decided_at: 'x' }), row({ id: 'row-dana', user_id: DANA, user_name: 'Dana Doe' })],
    });
    installFetch([{ test: /\/decision$/, method: 'POST', reply: () => ({ success: true, review: after }) }]);
    await renderPage();

    fireEvent.click(screen.getByTestId('review-request-changes'));
    expect(await screen.findByText('Say what needs to change before requesting changes.')).toBeInTheDocument();
    expect(screen.getByTestId('review-decision-note')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByTestId('review-decision-note')).toHaveFocus();
    expect(calls.filter((call) => call.method === 'POST')).toEqual([]);

    fireEvent.change(screen.getByTestId('review-decision-note'), { target: { value: 'Keep Pet' } });
    expect(screen.queryByText('Say what needs to change before requesting changes.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('review-request-changes'));

    expect(await screen.findByText('You requested changes in this round.')).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST').map((call) => call.body)).toEqual([
      { decision: 'request_changes', note: 'Keep Pet' },
    ]);
    expect(screen.getByTestId('review-status')).toHaveTextContent('Changes requested');
    expect(toast.success).toHaveBeenCalledWith('You requested changes.');
  });

  it('shows a refusal in words and reads the review again', async () => {
    installFetch([
      {
        test: /\/decision$/,
        method: 'POST',
        reply: () => ({ success: false, error: 'you already decided', code: 'review-already-decided' }),
      },
    ]);
    await renderPage();
    fireEvent.click(screen.getByTestId('review-approve'));
    expect(await screen.findByTestId('review-decision-error')).toHaveTextContent(
      'You already decided in this round. Decisions cannot be changed.'
    );
    await waitFor(() => expect(urls(new RegExp(`${BASE}$`))).toHaveLength(2));
  });

  it('keeps the note when recording fails for a reason that does not move the review', async () => {
    installFetch([{ test: /\/decision$/, method: 'POST', reply: () => ({ success: false, error: 'Gateway timeout' }) }]);
    await renderPage();
    fireEvent.change(screen.getByTestId('review-decision-note'), { target: { value: 'Draft thought' } });
    fireEvent.click(screen.getByTestId('review-approve'));
    expect(await screen.findByTestId('review-decision-error')).toHaveTextContent('Gateway timeout');
    expect(screen.getByTestId('review-decision-note')).toHaveValue('Draft thought');
    expect(urls(new RegExp(`${BASE}$`))).toHaveLength(1);
  });
});

describe('when there is nothing for the viewer to decide', () => {
  /**
   * Render with a given review and viewer.
   *
   * @param review - The review.
   * @param viewerId - The viewer.
   */
  async function renderWith(review: ReviewDetail, viewerId: string | null = VIEWER) {
    installFetch([
      { test: new RegExp(`${BASE}$`), reply: () => ({ success: true, review, project: { id: PROJECT_ID, name: 'Pets API', slug: 'pets' }, viewerId }) },
    ]);
    await renderPage();
  }

  it('tells someone who is not a reviewer', async () => {
    await renderWith(detail(), 'someone-else');
    expect(screen.getByTestId('review-decision-bar')).toHaveAttribute('data-mode', 'not-reviewer');
    expect(screen.queryByTestId('review-approve')).not.toBeInTheDocument();
  });

  it('warns that the spec changed and closes the form', async () => {
    await renderWith(detail({ spec_changed: true }));
    expect(screen.getByTestId('review-stale')).toHaveTextContent('changed after round 2 was requested');
    expect(screen.getByTestId('review-decision-bar')).toHaveAttribute('data-mode', 'stale');
    expect(screen.queryByTestId('review-request-changes')).not.toBeInTheDocument();
  });

  it('shows a withdrawn review as withdrawn', async () => {
    await renderWith(detail({ review: { closed_at: '2026-09-15T00:00:00Z' }, spec_changed: null }));
    expect(screen.getByTestId('review-status')).toHaveTextContent('Withdrawn');
    expect(screen.getByTestId('review-decision-bar')).toHaveAttribute('data-mode', 'withdrawn');
    expect(screen.queryByTestId('review-stale')).not.toBeInTheDocument();
  });

  it('closes the form for a pending reviewer once someone requested changes', async () => {
    await renderWith(detail({ review: { state: 'changes_requested' } }));
    expect(screen.getByTestId('review-decision-bar')).toHaveAttribute('data-mode', 'round-decided');
  });
});

describe('the reviewers card', () => {
  it('lists the current round, marks the viewer, and keeps earlier rounds as recorded', async () => {
    await renderPage();
    const card = screen.getByTestId('review-reviewers');
    expect(within(card).getByText('Round 2')).toBeInTheDocument();
    const ravi = screen.getByTestId('review-reviewer-row-ravi');
    expect(ravi).toHaveTextContent('Ravi Reviewer (you)');
    expect(within(ravi).getByText('Pending')).toBeInTheDocument();
    const earlier = screen.getByTestId('review-round-1');
    expect(within(earlier).getByText('Requested changes')).toBeInTheDocument();
    expect(within(earlier).getByText('Rename id to petId')).toBeInTheDocument();
    expect(within(earlier).getAllByText('Pending')).toHaveLength(1);
  });
});
