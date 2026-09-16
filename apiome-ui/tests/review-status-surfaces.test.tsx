/**
 * The review status surfaces, rendered (COL-2.4, #4520).
 *
 * `review-status-model.test.ts` holds the rules and `review-status-read.test.ts` the query; this
 * holds the four surfaces that draw them, and pins the ticket's three acceptance criteria:
 *
 *   1. **The pill renders the correct state** on a version row, a project card, a projects table
 *      row and the publish dialog — and renders *nothing* where there is no open review, because a
 *      draft already says it is a draft.
 *   2. **Clicking a pill navigates to the review page**: every pill is an `<a>` to
 *      `/ade/reviews/{id}`.
 *   3. **States update after decisions without stale caches**: the read is `no-store`, and the tab
 *      becoming visible again — what a reviewer coming back from the review page does — refetches.
 *
 * Plus the two things that are easy to get wrong and would not show up in a model test: the pill's
 * accessible name has to name the revision (colour is never the only signal), and on a project
 * card the pill has to sit above `.prj-card__link`'s stretched hit area or it cannot be clicked.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';
import { jest } from '@jest/globals';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/ade/dashboard/versions',
}));

/** Neither cell is under test here, and both reach for data of their own. */
jest.mock('@/app/components/ade/dashboard/VersionMockCell', () => ({
  VersionMockCell: () => <span data-testid="mock-cell" />,
}));
jest.mock('@/app/components/ade/dashboard/VersionLintBadge', () => ({
  VersionLintBadge: () => <span data-testid="lint-badge" />,
}));

import ProjectCard from '@/app/components/ade/projects/ProjectCard';
import ProjectsTable from '@/app/components/ade/projects/ProjectsTable';
import { ReviewStatusPanel } from '@/app/components/ade/reviews/ReviewStatusPanel';
import { ReviewStatusPill } from '@/app/components/ade/reviews/ReviewStatusPill';
import VersionsTable from '@/app/components/ade/versions/VersionsTable';
import type { Version } from '@/app/components/ade/versions/versionsModel';
import { useOpenReviews } from '@/app/hooks/useOpenReviews';
import {
  indexReviewsByVersion,
  summarizeProjectReviews,
  type ReviewStatusRow,
} from '@lib/review-status';

/* -------------------------------------------------------------------------- */
/* Fixtures                                                                   */
/* -------------------------------------------------------------------------- */

const PROJECT_ID = '8f2a1c00-0000-4000-8000-000000000001';
const DRAFT_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const OTHER_ID = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const REVIEW_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

/** An open review; `over` names only what the case is about. */
function review(over: Partial<ReviewStatusRow> = {}): ReviewStatusRow {
  return {
    reviewId: REVIEW_ID,
    projectId: PROJECT_ID,
    versionId: DRAFT_ID,
    versionLabel: '1.2.0',
    state: 'in_review',
    round: 1,
    reviewerCount: 2,
    approvedCount: 1,
    changesRequestedCount: 0,
    pendingCount: 1,
    updatedAt: '2026-09-01T10:00:00.000Z',
    ...over,
  };
}

/** A revision row. */
function version(over: Partial<Version> = {}): Version {
  return {
    id: DRAFT_ID,
    project_id: PROJECT_ID,
    creator_id: 'u-ada',
    version_id: '1.2.0',
    shortMessage: 'Add refunds',
    changelog: null,
    enabled: true,
    published: false,
    deleted_at: null,
    created_at: '2026-08-01T10:00:00.000Z',
    updated_at: '2026-08-02T10:00:00.000Z',
    published_at: null,
    creator_name: 'Ada Lovelace',
    creator_email: 'ada@example.com',
    ...over,
  };
}

/** A project row, as both projects views take it. */
const PROJECT = {
  id: PROJECT_ID,
  tenant_id: 't-acme',
  creator_id: 'u-ada',
  name: 'Payments API',
  slug: 'payments-api',
  description: 'Card, refund and payout endpoints.',
  enabled: true,
  deleted_at: null,
  created_at: '2026-06-01T10:00:00.000Z',
  updated_at: '2026-08-15T09:12:00.000Z',
  creator_name: 'Ada Lovelace',
  creator_email: 'ada@example.com',
  versionsCount: 6,
  qualityScore: 88,
  qualityGrade: 'B',
} as unknown as React.ComponentProps<typeof ProjectCard>['project'];

/** The revisions table with whatever reviews the case supplies. */
function renderVersions(reviews: readonly ReviewStatusRow[], rows: Version[] = [version()]) {
  return render(
    <VersionsTable
      versions={rows}
      projectId={PROJECT_ID}
      headRevisionId={rows[0]?.id ?? null}
      tagsByVersionId={new Map()}
      hasClassSchemaMap={{}}
      reviewsByVersionId={indexReviewsByVersion(reviews)}
      effectiveIsAdmin
      currentUserId="u-ada"
      hasBranches={false}
      freezingSchemaVersionId={null}
      isVersionPublishable={() => true}
      gitlike={{ enabled: false, marked: false }}
      mockUsageByVersion={null}
      onMockChanged={jest.fn()}
      onRowAction={jest.fn()}
      sort={{ columnId: 'version', direction: 'desc' }}
      onSortChange={jest.fn()}
    />
  );
}

/** The cards view with whatever reviews the case supplies. */
function renderCard(reviews: readonly ReviewStatusRow[]) {
  const summaries = summarizeProjectReviews(reviews);
  return render(
    <ProjectCard
      project={PROJECT}
      reviewSummary={summaries.get(PROJECT_ID.toLowerCase()) ?? null}
      onOpenQuality={jest.fn()}
      onOpenLint={jest.fn()}
      onEdit={jest.fn()}
      onDelete={jest.fn()}
      onRestore={jest.fn()}
      onPermanentDelete={jest.fn()}
    />
  );
}

/* -------------------------------------------------------------------------- */
/* The pill itself                                                            */
/* -------------------------------------------------------------------------- */

describe('ReviewStatusPill', () => {
  it('draws nothing when there is no open review', () => {
    const { container } = render(<ReviewStatusPill review={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    ['in_review', 'In review'],
    ['approved', 'Approved'],
    ['changes_requested', 'Changes requested'],
  ] as const)('says %s in words', (state, label) => {
    render(<ReviewStatusPill review={review({ state })} />);
    expect(screen.getByTestId('review-status-pill')).toHaveTextContent(label);
  });

  it('links to the review page', () => {
    render(<ReviewStatusPill review={review()} />);
    expect(screen.getByRole('link')).toHaveAttribute('href', `/ade/reviews/${REVIEW_ID}`);
  });

  it('names the revision in its accessible name, so colour is not the only signal', () => {
    render(<ReviewStatusPill review={review()} />);
    expect(screen.getByRole('link', { name: /v1\.2\.0 — in review/i })).toBeInTheDocument();
  });

  it('carries the state as data, so a surface can style or query off it', () => {
    render(<ReviewStatusPill review={review({ state: 'approved' })} />);
    expect(screen.getByTestId('review-status-pill')).toHaveAttribute('data-review-state', 'approved');
  });

  it('adds a +N chip, and says what it stands for, when it speaks for several reviews', () => {
    render(<ReviewStatusPill review={review()} moreCount={2} />);
    expect(screen.getByTestId('review-status-pill-more')).toHaveTextContent('+2');
    expect(screen.getByRole('link').getAttribute('aria-label')).toContain('2 more open reviews');
  });

  it('ignores a negative or fractional count rather than drawing "+-1"', () => {
    render(<ReviewStatusPill review={review()} moreCount={-3} />);
    expect(screen.queryByTestId('review-status-pill-more')).not.toBeInTheDocument();
  });
});

/* -------------------------------------------------------------------------- */
/* Version rows                                                               */
/* -------------------------------------------------------------------------- */

describe('the revisions table', () => {
  it('pills the revision that is in review, beside its lifecycle badge', () => {
    renderVersions([review()]);
    const cell = screen.getByTestId(`versions-status-${DRAFT_ID}`).closest('td') as HTMLElement;
    expect(within(cell).getByText('Draft')).toBeInTheDocument();
    expect(within(cell).getByTestId(`versions-review-${DRAFT_ID}`)).toHaveTextContent('In review');
  });

  it('links that pill to the review page', () => {
    renderVersions([review()]);
    expect(screen.getByTestId(`versions-review-${DRAFT_ID}`)).toHaveAttribute(
      'href',
      `/ade/reviews/${REVIEW_ID}`
    );
  });

  it('leaves a revision with no open review without a pill', () => {
    renderVersions([review()], [version(), version({ id: OTHER_ID, version_id: '1.1.0' })]);
    expect(screen.getByTestId(`versions-review-${DRAFT_ID}`)).toBeInTheDocument();
    expect(screen.queryByTestId(`versions-review-${OTHER_ID}`)).not.toBeInTheDocument();
  });

  it('draws no pill at all while the read is still in flight', () => {
    render(
      <VersionsTable
        versions={[version()]}
        projectId={PROJECT_ID}
        headRevisionId={DRAFT_ID}
        tagsByVersionId={new Map()}
        hasClassSchemaMap={{}}
        reviewsByVersionId={null}
        effectiveIsAdmin
        currentUserId="u-ada"
        hasBranches={false}
        freezingSchemaVersionId={null}
        isVersionPublishable={() => true}
        gitlike={{ enabled: false, marked: false }}
        mockUsageByVersion={null}
        onMockChanged={jest.fn()}
        onRowAction={jest.fn()}
        sort={{ columnId: 'version', direction: 'desc' }}
        onSortChange={jest.fn()}
      />
    );
    expect(screen.queryByTestId(`versions-review-${DRAFT_ID}`)).not.toBeInTheDocument();
  });
});

/* -------------------------------------------------------------------------- */
/* Project cards and the table                                                */
/* -------------------------------------------------------------------------- */

describe('the project card', () => {
  it('pills the most urgent open review of the project and links to it', () => {
    renderCard([review()]);
    const pill = screen.getByTestId('project-card-review');
    expect(pill).toHaveTextContent('In review');
    expect(pill).toHaveAttribute('href', `/ade/reviews/${REVIEW_ID}`);
  });

  it('lets changes requested speak for a project that also has an approval pending', () => {
    renderCard([
      review({ reviewId: 'r-approved', versionId: 'v-a', state: 'approved' }),
      review({ reviewId: 'r-changes', versionId: 'v-b', state: 'changes_requested' }),
    ]);
    const pill = screen.getByTestId('project-card-review');
    expect(pill).toHaveTextContent('Changes requested');
    expect(pill).toHaveAttribute('href', '/ade/reviews/r-changes');
    expect(within(pill).getByTestId('review-status-pill-more')).toHaveTextContent('+1');
  });

  it('raises the pill above the card link, or it could never be clicked', () => {
    // `.prj-card__link::after` stretches the project link over the whole card; anything
    // interactive has to sit on `.prj-card__above`, one stacking step higher.
    renderCard([review()]);
    const holder = screen.getByTestId('project-card-review').parentElement as HTMLElement;
    expect(holder).toHaveClass('prj-card__above');
  });

  it('gives up no card surface when there is nothing in review', () => {
    renderCard([]);
    expect(screen.queryByTestId('project-card-review')).not.toBeInTheDocument();
    const holder = screen.getByTestId('project-card-status').parentElement as HTMLElement;
    expect(holder).not.toHaveClass('prj-card__above');
  });
});

describe('the projects table', () => {
  /** The table, with a spy on the row activation the pill must not trigger. */
  function renderTable(onOpen = jest.fn()) {
    render(
      <ProjectsTable
        projects={[PROJECT]}
        historyById={{}}
        reviewsByProjectId={summarizeProjectReviews([review({ state: 'approved' })])}
        sort={null}
        onSortChange={jest.fn()}
        selectedIds={[]}
        onSelectionChange={jest.fn()}
        onOpen={onOpen}
        onOpenTrend={jest.fn()}
        onEdit={jest.fn()}
        onDelete={jest.fn()}
        onRestore={jest.fn()}
        onPermanentDelete={jest.fn()}
      />
    );
    return { onOpen };
  }

  it('draws the same pill in the Status cell', () => {
    renderTable();
    const pill = screen.getByTestId(`projects-review-${PROJECT_ID}`);
    expect(pill).toHaveTextContent('Approved');
    expect(pill).toHaveAttribute('href', `/ade/reviews/${REVIEW_ID}`);
  });

  it('does not also open the project — the row would navigate somewhere else', () => {
    // `DataTable` activates a row on click and on Enter, and only exempts the checkbox and the
    // actions column. Without the pill stopping both, one click would start two navigations.
    const { onOpen } = renderTable();
    const pill = screen.getByTestId(`projects-review-${PROJECT_ID}`);
    fireEvent.click(pill);
    fireEvent.keyDown(pill, { key: 'Enter' });
    expect(onOpen).not.toHaveBeenCalled();
  });
});

/* -------------------------------------------------------------------------- */
/* The publish dialog's panel                                                 */
/* -------------------------------------------------------------------------- */

describe('the publish dialog review panel', () => {
  it('waits rather than claiming there is no review', () => {
    render(<ReviewStatusPanel review={null} loading />);
    expect(screen.getByTestId('publish-review-panel')).toHaveTextContent(/Checking whether/i);
    expect(screen.queryByTestId('publish-review-none')).not.toBeInTheDocument();
  });

  it('keeps showing a review it already has while a refresh is in flight', () => {
    render(<ReviewStatusPanel review={review()} loading />);
    const panel = screen.getByTestId('publish-review-panel');
    expect(panel).toHaveTextContent('1 of 2 approved · 1 pending');
    expect(panel).not.toHaveTextContent(/Checking whether/i);
  });

  it('says a revision with no review may still be gated', () => {
    render(<ReviewStatusPanel review={null} />);
    expect(screen.getByTestId('publish-review-none')).toHaveTextContent(/No open review/i);
    expect(screen.queryByTestId('publish-review-pill')).not.toBeInTheDocument();
  });

  it('states the round and the tally so the COL-2.3 gate is never a surprise', () => {
    render(<ReviewStatusPanel review={review()} />);
    const panel = screen.getByTestId('publish-review-panel');
    expect(panel).toHaveTextContent('round 1');
    expect(panel).toHaveTextContent('1 of 2 approved · 1 pending');
    expect(panel).toHaveTextContent(/publishing is refused until this round has them/i);
  });

  it('warns harder when changes were requested', () => {
    render(<ReviewStatusPanel review={review({ state: 'changes_requested' })} />);
    expect(screen.getByTestId('publish-review-panel')).toHaveTextContent(
      /refuses this publish until the changes are addressed/i
    );
  });

  it('links out to the review page', () => {
    render(<ReviewStatusPanel review={review()} />);
    expect(screen.getByTestId('publish-review-link')).toHaveAttribute(
      'href',
      `/ade/reviews/${REVIEW_ID}`
    );
  });
});

/* -------------------------------------------------------------------------- */
/* Accessibility                                                              */
/* -------------------------------------------------------------------------- */

describe('accessibility', () => {
  it('adds no violation to the card it lands on', async () => {
    const view = renderCard([review({ state: 'changes_requested' })]);
    expect(await axe(view.container)).toHaveNoViolations();
  });

  it('adds no violation to the publish dialog panel', async () => {
    const view = render(<ReviewStatusPanel review={review()} />);
    expect(await axe(view.container)).toHaveNoViolations();
  });
});

/* -------------------------------------------------------------------------- */
/* Freshness                                                                  */
/* -------------------------------------------------------------------------- */

describe('useOpenReviews', () => {
  /** A probe that renders whatever the hook resolved. */
  function Probe({ projectId }: { projectId?: string | null }) {
    const { byVersionId } = useOpenReviews({ enabled: true, projectId });
    const row = byVersionId?.get(DRAFT_ID.toLowerCase()) ?? null;
    return <span data-testid="probe">{row ? row.state : 'none'}</span>;
  }

  let fetchMock: jest.Mock;

  beforeEach(() => {
    fetchMock = jest.fn(async () => ({
      ok: true,
      json: async () => ({ success: true, reviews: [review()] }),
    })) as unknown as jest.Mock;
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it('reads the whole tenant with no cache', async () => {
    render(<Probe />);
    await screen.findByText('in_review');
    expect(fetchMock).toHaveBeenCalledWith('/api/reviews/status', { cache: 'no-store' });
  });

  it('narrows to one project when given one', async () => {
    render(<Probe projectId={PROJECT_ID} />);
    await screen.findByText('in_review');
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/reviews/status?projectId=${PROJECT_ID}`,
      { cache: 'no-store' }
    );
  });

  it('refetches when the tab becomes visible again, so a decision cannot go stale', async () => {
    render(<Probe />);
    await screen.findByText('in_review');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fetchMock.mockImplementation(async () => ({
      ok: true,
      json: async () => ({ success: true, reviews: [review({ state: 'approved' })] }),
    }));
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await screen.findByText('approved');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('reports loading until the first read lands, but not during a background refresh', async () => {
    const seen: boolean[] = [];
    function LoadingProbe() {
      const { loading } = useOpenReviews({ enabled: true });
      seen.push(loading);
      return <span data-testid="loading">{String(loading)}</span>;
    }
    render(<LoadingProbe />);
    expect(seen[0]).toBe(true);
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));

    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(screen.getByTestId('loading')).toHaveTextContent('false');
  });

  it('draws no pill — and no error — when the read fails', async () => {
    fetchMock.mockImplementation(async () => {
      throw new Error('offline');
    });
    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('none'));
  });

  it('ignores a reply that did not succeed', async () => {
    fetchMock.mockImplementation(async () => ({ ok: false, json: async () => ({ success: false }) }));
    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('none'));
  });
});
