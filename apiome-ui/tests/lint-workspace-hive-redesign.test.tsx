/**
 * The lint posture workspace, rendered (HIVE-5.8, #5311).
 *
 * `lint-workspace-model.test.ts` pins the rules and `lint-workspace-css.test.ts` pins the
 * declarations; this suite pins what the six components actually put on screen and what they
 * call back with — the mockup's **Notes → Keeps (1:1)** list, one `it` at a time.
 *
 * Two jsdom notes, both learned the expensive way on #5304:
 *
 * * `fireEvent.click` does not drive a Radix `Tabs.Trigger` (it changes value from
 *   `onMouseDown`) and does not open a `DropdownMenu` (it opens on `pointerdown`, which jsdom
 *   does not synthesise). The tab strip here is a plain `<button role="tab">`, so a click is
 *   enough — but `Segmented`'s options are Radix-flavoured `role="radio"` buttons that answer
 *   `onClick`, which is why the window switch is clicked and the shortcuts are not.
 * * Radix `Dialog`/`Drawer` never writes `aria-modal` in jsdom and its focus restoration does
 *   not settle, so those two are asserted in `e2e/hive-lint-workspace.spec.ts` instead.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import LintPostureSummary from '../src/app/components/ade/lintWorkspace/LintPostureSummary';
import LintSavedViewsBar from '../src/app/components/ade/lintWorkspace/LintSavedViewsBar';
import LintQueueTable from '../src/app/components/ade/lintWorkspace/LintQueueTable';
import LintWaiverDialog from '../src/app/components/ade/lintWorkspace/LintWaiverDialog';
import LintFindingDrawer from '../src/app/components/ade/lintWorkspace/LintFindingDrawer';
import LintTrendsPanel from '../src/app/components/ade/lintWorkspace/LintTrendsPanel';
import LintQualityRanksPanel from '../src/app/components/ade/lintWorkspace/LintQualityRanksPanel';
import {
  EMPTY_WORKSPACE_FILTERS,
  selectionKey,
  type WorkspaceFilters,
} from '../src/app/utils/lint-workspace';
import {
  FINDINGS,
  finding,
  findingsPage,
  rankFormat,
  rankSeries,
  savedView,
  summary,
  trends,
} from './helpers/lint-workspace-fixtures';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';
import LintWorkspacePage from '../src/app/ade/dashboard/lint-workspace/page';

/** The empty filter bundle, plus whatever a case is about. */
function filters(overrides: Partial<WorkspaceFilters> = {}): WorkspaceFilters {
  return { ...EMPTY_WORKSPACE_FILTERS, ...overrides };
}

// =========================================================================================
// The posture summary
// =========================================================================================

describe('LintPostureSummary', () => {
  it('draws the four tiles with their figures, units and footnotes', () => {
    render(<LintPostureSummary summary={summary()} onDrillDown={jest.fn()} />);
    expect(screen.getByTestId('summary-security-errors')).toHaveTextContent('2');
    expect(screen.getByTestId('summary-security-errors')).toHaveTextContent('Needs attention');
    expect(screen.getByTestId('summary-coverage')).toHaveTextContent('of 12 subjects');
    expect(screen.getByTestId('summary-new')).toHaveTextContent('7');
    expect(screen.getByTestId('summary-waiver-requests')).toHaveTextContent(
      '3 requested · 1 expiring soon'
    );
  });

  it('makes every tile a real button, so all four can be drilled into', () => {
    const onDrillDown = jest.fn();
    render(<LintPostureSummary summary={summary()} onDrillDown={onDrillDown} />);
    for (const target of ['security-errors', 'coverage', 'new', 'waiver-requests'] as const) {
      const tile = screen.getByTestId(`summary-${target}`);
      expect(tile.tagName).toBe('BUTTON');
      // A `button` with no explicit type submits whatever form it lands in.
      expect(tile).toHaveAttribute('type', 'button');
      fireEvent.click(tile);
      expect(onDrillDown).toHaveBeenCalledWith(target);
    }
    expect(onDrillDown).toHaveBeenCalledTimes(4);
  });

  it('draws every grade band, including the ones with no subjects in them', () => {
    render(<LintPostureSummary summary={summary()} onDrillDown={jest.fn()} />);
    const grades = screen.getByTestId('summary-grades');
    for (const letter of ['A', 'B', 'C', 'D', 'F']) {
      expect(within(grades).getByText(letter)).toBeInTheDocument();
    }
    expect(within(grades).getByText('Ungraded')).toBeInTheDocument();
  });

  it('says an unassessed axis is unassessed rather than scoring it zero', () => {
    render(<LintPostureSummary summary={summary()} onDrillDown={jest.fn()} />);
    expect(screen.getByTestId('summary-axis-quality')).toHaveTextContent('Quality · 84');
    const supply = screen.getByTestId('summary-axis-supply_chain');
    expect(supply).toHaveTextContent('Supply chain · —');
    expect(supply).toHaveAttribute('title', 'Supply chain: not assessed anywhere');
  });

  it('holds the strip’s shape while the summary is being read', () => {
    render(<LintPostureSummary summary={null} loading onDrillDown={jest.fn()} />);
    expect(screen.getByTestId('lint-workspace-summary-skeleton')).toBeInTheDocument();
  });

  it('draws nothing at all when the summary read failed', () => {
    const { container } = render(
      <LintPostureSummary summary={null} loading={false} onDrillDown={jest.fn()} />
    );
    expect(container).toBeEmptyDOMElement();
  });
});

// =========================================================================================
// Saved views
// =========================================================================================

describe('LintSavedViewsBar', () => {
  function renderBar(
    props: Partial<React.ComponentProps<typeof LintSavedViewsBar>> = {},
    current: Partial<WorkspaceFilters> = {}
  ) {
    const handlers = {
      onApply: jest.fn(),
      onSaveCurrent: jest.fn(),
      onTogglePin: jest.fn(),
      onDelete: jest.fn(),
      onSaveOpenChange: jest.fn(),
    };
    render(
      <LintSavedViewsBar
        views={[
          savedView(),
          savedView({
            id: 'view-2',
            name: 'My waivers',
            isPinned: false,
            filters: { state: ['waiver_requested'] },
          }),
        ]}
        filters={filters(current)}
        sort="severity"
        saveOpen={false}
        {...handlers}
        {...props}
      />
    );
    return handlers;
  }

  it('applies, pins and deletes a view', () => {
    const handlers = renderBar();
    const chips = screen.getAllByTestId('saved-view-chip');
    expect(chips).toHaveLength(2);
    fireEvent.click(within(chips[0]).getByTestId('saved-view-apply'));
    expect(handlers.onApply).toHaveBeenCalledWith(expect.objectContaining({ id: 'view-1' }));
    fireEvent.click(within(chips[1]).getByTestId('saved-view-pin'));
    expect(handlers.onTogglePin).toHaveBeenCalledWith(expect.objectContaining({ id: 'view-2' }));
    fireEvent.click(within(chips[0]).getByTestId('saved-view-delete'));
    expect(handlers.onDelete).toHaveBeenCalledWith(expect.objectContaining({ id: 'view-1' }));
  });

  it('names the pin action for the view it belongs to', () => {
    renderBar();
    expect(screen.getByLabelText('Unpin New security errors')).toBeInTheDocument();
    expect(screen.getByLabelText('Pin My waivers')).toBeInTheDocument();
  });

  it('marks the view a reader is actually looking at, and only that one', () => {
    renderBar({}, { severity: ['error'], axis: ['security'], state: ['open'] });
    const chips = screen.getAllByTestId('saved-view-chip');
    expect(chips[0]).toHaveAttribute('data-current', 'true');
    expect(chips[1]).not.toHaveAttribute('data-current');
  });

  it('marks none of them once a facet is flipped', () => {
    renderBar({}, { severity: ['error'], axis: ['security'] });
    for (const chip of screen.getAllByTestId('saved-view-chip')) {
      expect(chip).not.toHaveAttribute('data-current');
    }
  });

  it('will not save an unnamed view, and shows what it would save', () => {
    const handlers = renderBar({ saveOpen: true }, { severity: ['error'] });
    expect(screen.getByTestId('saved-view-query')).toHaveTextContent('severity=error');
    expect(screen.getByTestId('saved-view-submit')).toBeDisabled();
    fireEvent.change(screen.getByTestId('saved-view-name'), {
      target: { value: 'New security errors' },
    });
    fireEvent.click(screen.getByTestId('saved-view-submit'));
    expect(handlers.onSaveCurrent).toHaveBeenCalledWith('New security errors', true);
    expect(handlers.onSaveOpenChange).toHaveBeenCalledWith(false);
  });

  it('says so rather than showing a bare sort when nothing is narrowed', () => {
    renderBar({ saveOpen: true });
    expect(screen.getByTestId('saved-view-query')).toHaveTextContent(
      'No filters — the whole queue, sorted by severity'
    );
  });
});

// =========================================================================================
// The queue
// =========================================================================================

describe('LintQueueTable', () => {
  function renderQueue(props: Partial<React.ComponentProps<typeof LintQueueTable>> = {}) {
    const page = findingsPage();
    const handlers = {
      onRetry: jest.fn(),
      onFiltersChange: jest.fn(),
      onSortChange: jest.fn(),
      onOffsetChange: jest.fn(),
      onSelectionChange: jest.fn(),
      onOpenFinding: jest.fn(),
      onBulkApply: jest.fn(),
      onOpenWaiverDialog: jest.fn(),
    };
    const view = render(
      <LintQueueTable
        findings={page.findings}
        total={page.total}
        offset={0}
        facets={page.facets}
        filters={filters()}
        sort="severity"
        pathname="/ade/dashboard/lint-workspace"
        selected={new Set()}
        {...handlers}
        {...props}
      />
    );
    return { ...handlers, view };
  }

  it('draws the seven-column row: rule, New pill, message, path, severity, state, subject', () => {
    renderQueue();
    expect(screen.getByText('no-http-basic')).toBeInTheDocument();
    expect(screen.getByTestId('finding-new-pill')).toBeInTheDocument();
    expect(screen.getByText('HTTP Basic auth scheme detected.')).toBeInTheDocument();
    // Both fixture rows carry the same path; the assertion is that the row *draws* one.
    expect(screen.getAllByText('components.securitySchemes.basicAuth')).toHaveLength(2);
    // Scoped to the table body: the facet strip above it carries the same six words.
    const rows = within(screen.getByRole('table'));
    expect(rows.getByText('Error')).toBeInTheDocument();
    expect(rows.getByText('Acknowledged')).toBeInTheDocument();
    expect(rows.getAllByText('Payments API')).toHaveLength(2);
    expect(screen.getAllByText('apiome-security')).not.toHaveLength(0);
  });

  it('shows the finding’s composite grade, and says ungraded when there is none', () => {
    renderQueue({ findings: [finding(), finding({ sourceFingerprint: 'f3', compositeGrade: null })] });
    expect(screen.getAllByTitle('Composite grade B')).toHaveLength(1);
    expect(screen.getByText('ungraded')).toBeInTheDocument();
  });

  it('marks an MCP subject as one', () => {
    renderQueue({
      findings: [finding({ subjectType: 'mcp_endpoint_version', versionRecordId: null })],
    });
    expect(screen.getByText('MCP')).toBeInTheDocument();
  });

  it('draws all four facet groups with the counts from the read', () => {
    renderQueue();
    const facets = screen.getByTestId('workspace-facets');
    expect(within(facets).getByTestId('facet-severity-error')).toHaveTextContent('21');
    expect(within(facets).getByTestId('facet-state-open')).toHaveTextContent('168');
    expect(within(facets).getByTestId('facet-axis-supply_chain')).toBeInTheDocument();
    expect(within(facets).getByTestId('facet-grade-F')).toBeInTheDocument();
  });

  it('flips a facet on the dimension it belongs to', () => {
    const { onFiltersChange } = renderQueue();
    fireEvent.click(screen.getByTestId('facet-severity-error'));
    expect(onFiltersChange).toHaveBeenCalledWith(expect.objectContaining({ severity: ['error'] }));
    fireEvent.click(screen.getByTestId('facet-state-waived'));
    expect(onFiltersChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ state: ['waived'], severity: [] })
    );
  });

  it('states the chips as toggles whether or not they are on', () => {
    renderQueue({ filters: filters({ severity: ['error'] }) });
    expect(screen.getByTestId('facet-severity-error')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('facet-severity-info')).toHaveAttribute('aria-pressed', 'false');
  });

  it('drives the six toolbar controls', () => {
    const { onFiltersChange, onSortChange } = renderQueue();
    fireEvent.change(screen.getByTestId('workspace-search'), { target: { value: 'basic' } });
    expect(onFiltersChange).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'basic' }));
    fireEvent.change(screen.getByTestId('workspace-sort'), { target: { value: 'newest' } });
    expect(onSortChange).toHaveBeenCalledWith('newest');
    fireEvent.change(screen.getByTestId('workspace-scanner'), { target: { value: 'spectral' } });
    expect(onFiltersChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ scanner: ['spectral'] })
    );
    fireEvent.change(screen.getByTestId('workspace-coverage'), { target: { value: 'missing' } });
    expect(onFiltersChange).toHaveBeenLastCalledWith(expect.objectContaining({ coverage: 'missing' }));
    fireEvent.change(screen.getByTestId('workspace-subject-type'), {
      target: { value: 'mcp_endpoint_version' },
    });
    expect(onFiltersChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ subjectType: 'mcp_endpoint_version' })
    );
  });

  it('offers Clear filters only when something is narrowing the queue, and keeps the project', () => {
    const plain = renderQueue();
    expect(screen.queryByTestId('workspace-clear-filters')).not.toBeInTheDocument();
    plain.view.unmount();

    const { onFiltersChange } = renderQueue({
      filters: filters({ projectId: 'p1', severity: ['error'], newOnly: true }),
    });
    const clear = screen.getByTestId('workspace-clear-filters');
    expect(clear).toHaveTextContent('Clear filters (2)');
    fireEvent.click(clear);
    expect(onFiltersChange).toHaveBeenCalledWith({ ...EMPTY_WORKSPACE_FILTERS, projectId: 'p1' });
  });

  it('prints the address the current view is shareable at', () => {
    renderQueue({ filters: filters({ severity: ['error'] }), offset: 50 });
    const line = screen.getByTestId('workspace-url-line');
    expect(line).toHaveTextContent('/ade/dashboard/lint-workspace');
    expect(line).toHaveTextContent('severity=error');
    expect(line).toHaveTextContent('offset=50');
    expect(line).toHaveTextContent('selection clears when filters change');
  });

  it('selects a row, and reports the selection as ids', () => {
    const { onSelectionChange } = renderQueue();
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    expect(onSelectionChange).toHaveBeenCalledWith(new Set([selectionKey(FINDINGS[0])]));
  });

  it('opens a finding from its row', () => {
    const { onOpenFinding } = renderQueue();
    fireEvent.click(screen.getByText('no-http-basic'));
    expect(onOpenFinding).toHaveBeenCalledWith(FINDINGS[0]);
  });

  it('counts the offset window and pages by offset', () => {
    const { onOffsetChange } = renderQueue({ offset: 50 });
    expect(screen.getByTestId('queue-pagination-summary')).toHaveTextContent(
      '51–100 of 213 findings · page size 50'
    );
    fireEvent.click(screen.getByLabelText('Page 3'));
    expect(onOffsetChange).toHaveBeenCalledWith(100);
  });

  it('shows the bulk bar only while something is selected, and names what is selected', () => {
    const plain = renderQueue();
    expect(screen.queryByTestId('bulk-acknowledged')).not.toBeInTheDocument();
    plain.view.unmount();

    renderQueue({ selected: new Set([selectionKey(FINDINGS[0])]) });
    expect(screen.getByText('1 finding selected')).toBeInTheDocument();
  });

  it('applies the four direct verbs and routes the two waiver verbs to the dialog', () => {
    const { onBulkApply, onOpenWaiverDialog } = renderQueue({
      selected: new Set([selectionKey(FINDINGS[0])]),
    });
    fireEvent.click(screen.getByTestId('bulk-acknowledged'));
    expect(onBulkApply).toHaveBeenCalledWith({ state: 'acknowledged' }, 'Acknowledge');
    fireEvent.click(screen.getByTestId('bulk-fixed'));
    expect(onBulkApply).toHaveBeenLastCalledWith({ state: 'fixed' }, 'Mark fixed');
    fireEvent.click(screen.getByTestId('bulk-false_positive'));
    expect(onBulkApply).toHaveBeenLastCalledWith({ state: 'false_positive' }, 'False positive');
    fireEvent.click(screen.getByTestId('bulk-open'));
    expect(onBulkApply).toHaveBeenLastCalledWith({ state: 'open' }, 'Reopen / reject');

    fireEvent.click(screen.getByTestId('bulk-waiver_requested'));
    expect(onOpenWaiverDialog).toHaveBeenCalledWith('request');
    fireEvent.click(screen.getByTestId('bulk-waived'));
    expect(onOpenWaiverDialog).toHaveBeenLastCalledWith('approve');
  });

  it('says which permission the two review verbs need', () => {
    renderQueue({ selected: new Set([selectionKey(FINDINGS[0])]) });
    expect(screen.getByTestId('bulk-waived')).toHaveAttribute(
      'title',
      'Requires waiver approval permission (lint_findings:publish)'
    );
    expect(screen.getByTestId('bulk-open')).toHaveAttribute(
      'title',
      expect.stringContaining('also rejects requested waivers')
    );
  });

  it('assigns an owner without changing any state', () => {
    const { onBulkApply } = renderQueue({ selected: new Set([selectionKey(FINDINGS[0])]) });
    expect(screen.getByTestId('bulk-assign-owner')).toBeDisabled();
    fireEvent.change(screen.getByTestId('bulk-owner-input'), { target: { value: ' user-9 ' } });
    fireEvent.click(screen.getByTestId('bulk-assign-owner'));
    expect(onBulkApply).toHaveBeenCalledWith({ ownerUserId: 'user-9' }, 'Assign');
  });

  it('holds every verb while a write is in flight', () => {
    renderQueue({ selected: new Set([selectionKey(FINDINGS[0])]), bulkBusy: true });
    expect(screen.getByTestId('bulk-acknowledged')).toBeDisabled();
    expect(screen.getByTestId('bulk-waived')).toBeDisabled();
  });

  it('tells a narrowed reader to widen and an empty workspace what would fill it', () => {
    const narrowed = renderQueue({ findings: [], total: 0, filters: filters({ severity: ['error'] }) });
    expect(screen.getByText('No findings match the current filters.')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('workspace-empty-clear'));
    expect(narrowed.onFiltersChange).toHaveBeenCalledWith(EMPTY_WORKSPACE_FILTERS);
    narrowed.view.unmount();

    renderQueue({ findings: [], total: 0 });
    expect(screen.getByText('No lint findings in this workspace.')).toBeInTheDocument();
  });

  it('names what it is waiting for while the queue loads', () => {
    renderQueue({ findings: [], loading: true });
    expect(screen.getByText('Loading the findings queue…')).toBeInTheDocument();
  });

  it('reports a failed read as an error with a retry, not as an empty workspace', () => {
    const { onRetry } = renderQueue({ findings: [], total: 0, error: 'The service timed out (504).' });
    expect(screen.getByText('The service timed out (504).')).toBeInTheDocument();
    expect(screen.queryByText('No lint findings in this workspace.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalled();
  });
});

// =========================================================================================
// The waiver dialog
// =========================================================================================

describe('LintWaiverDialog', () => {
  it('is closed when it has no mode', () => {
    const { container } = render(
      <LintWaiverDialog mode={null} count={0} onClose={jest.fn()} onSubmit={jest.fn()} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('requires a rationale to request a waiver', () => {
    const onSubmit = jest.fn();
    render(<LintWaiverDialog mode="request" count={2} onClose={jest.fn()} onSubmit={onSubmit} />);
    expect(screen.getByText('Request waiver for 2 findings')).toBeInTheDocument();
    expect(screen.getByTestId('waiver-submit')).toBeDisabled();
    fireEvent.change(screen.getByTestId('waiver-rationale'), {
      target: { value: ' Vendor accepts the risk until Q4. ' },
    });
    fireEvent.click(screen.getByTestId('waiver-submit'));
    expect(onSubmit).toHaveBeenCalledWith({
      state: 'waiver_requested',
      rationale: 'Vendor accepts the risk until Q4.',
    });
  });

  it('requires a rationale AND an expiry to approve one', () => {
    const onSubmit = jest.fn();
    render(<LintWaiverDialog mode="approve" count={1} onClose={jest.fn()} onSubmit={onSubmit} />);
    expect(screen.getByText('Approve waiver for 1 finding')).toBeInTheDocument();
    fireEvent.change(screen.getByTestId('waiver-rationale'), { target: { value: 'Approved.' } });
    expect(screen.getByTestId('waiver-submit')).toBeDisabled();
    fireEvent.change(screen.getByTestId('waiver-expires'), { target: { value: '2026-09-30' } });
    fireEvent.click(screen.getByTestId('waiver-submit'));
    expect(onSubmit).toHaveBeenCalledWith({
      state: 'waived',
      rationale: 'Approved.',
      expiresAt: new Date('2026-09-30').toISOString(),
    });
  });

  it('carries the optional ticket, and says which permission approving needs', () => {
    const onSubmit = jest.fn();
    render(<LintWaiverDialog mode="approve" count={1} onClose={jest.fn()} onSubmit={onSubmit} />);
    expect(screen.getByTestId('waiver-permission-note')).toHaveTextContent(
      'lint_findings:publish'
    );
    fireEvent.change(screen.getByTestId('waiver-rationale'), { target: { value: 'Approved.' } });
    fireEvent.change(screen.getByTestId('waiver-expires'), { target: { value: '2026-09-30' } });
    fireEvent.change(screen.getByTestId('waiver-ticket'), {
      target: { value: 'https://tracker/SEC-1182' },
    });
    fireEvent.click(screen.getByTestId('waiver-submit'));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ linkedTicket: 'https://tracker/SEC-1182' })
    );
  });
});

// =========================================================================================
// The finding drawer
// =========================================================================================

describe('LintFindingDrawer', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  function renderDrawer(props: Partial<React.ComponentProps<typeof LintFindingDrawer>> = {}) {
    const handlers = { onClose: jest.fn(), onDecision: jest.fn(), onRequestWaiver: jest.fn() };
    render(<LintFindingDrawer finding={finding()} {...handlers} {...props} />);
    return handlers;
  }

  it('is closed when it has no finding', () => {
    const { container } = render(
      <LintFindingDrawer
        finding={null}
        onClose={jest.fn()}
        onDecision={jest.fn()}
        onRequestWaiver={jest.fn()}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('lists the six evidence fields the acceptance criteria name', () => {
    renderDrawer();
    const evidence = screen.getByTestId('detail-evidence');
    expect(within(evidence).getByText('apiome-security')).toBeInTheDocument();
    expect(within(evidence).getByText('Acme REST · security pack')).toBeInTheDocument();
    expect(screen.getByTestId('detail-evidence-run')).toHaveTextContent('run_7c1e92');
    expect(screen.getByTestId('detail-location')).toHaveTextContent(
      'path: components.securitySchemes.basicAuth, line: 412'
    );
    expect(screen.getByTestId('detail-remediation')).toHaveTextContent('OAuth2');
  });

  it('links the subject and states the policy verdict with its evaluation', () => {
    renderDrawer();
    expect(screen.getByTestId('detail-subject-link')).toHaveAttribute(
      'href',
      '/ade/dashboard/versions?projectId=p1'
    );
    const policy = screen.getByTestId('detail-policy');
    expect(policy).toHaveTextContent('Failed');
    expect(policy).toHaveTextContent('ev_44b0c1');
  });

  it('says no decisions were recorded when the finding has none', () => {
    renderDrawer();
    expect(screen.getByTestId('detail-history-empty')).toBeInTheDocument();
  });

  it('reads the remediation history for a finding that has a decision', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        events: [
          {
            id: 'e1',
            beforeState: 'open',
            afterState: 'waiver_requested',
            rationale: 'Legacy partner',
            actorLabel: 'Linus Torvalds',
            createdAt: 'Aug 14, 2026',
          },
        ],
      }),
    }) as unknown as typeof fetch;

    renderDrawer({ finding: FINDINGS[1] });
    await waitFor(() =>
      expect(screen.getByTestId('detail-history-event')).toHaveTextContent(
        'Open → Waiver requested'
      )
    );
    expect(screen.getByTestId('detail-history-event')).toHaveTextContent('Legacy partner');
  });

  it('says the history could not be read rather than saying there is none', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ success: false, error: 'Evidence service unavailable' }),
    }) as unknown as typeof fetch;

    renderDrawer({ finding: FINDINGS[1] });
    await waitFor(() =>
      expect(screen.getByTestId('detail-history-error')).toHaveTextContent(
        'Evidence service unavailable'
      )
    );
  });

  it('acknowledges this one finding, and sends the waiver through the dialog', () => {
    const handlers = renderDrawer();
    fireEvent.click(screen.getByTestId('detail-acknowledge'));
    expect(handlers.onDecision).toHaveBeenCalledWith(
      expect.objectContaining({ ruleId: 'no-http-basic' }),
      { state: 'acknowledged' },
      'Acknowledge'
    );
    fireEvent.click(screen.getByTestId('detail-request-waiver'));
    expect(handlers.onRequestWaiver).toHaveBeenCalledWith(
      expect.objectContaining({ ruleId: 'no-http-basic' })
    );
    // Never applied directly: a waiver with no rationale is one the server refuses.
    expect(handlers.onDecision).toHaveBeenCalledTimes(1);
  });

  it('offers the lint report only for a finding that has a revision to report on', () => {
    const withRevision = renderDrawer();
    expect(screen.getByTestId('detail-open-lint-report')).toBeInTheDocument();
    void withRevision;
    screen.getByTestId('finding-detail-drawer');
  });

  it('offers no lint report for an MCP finding, which has no revision', () => {
    renderDrawer({
      finding: finding({ versionRecordId: null, mcpVersionId: 'mcp-1', subjectType: 'mcp_endpoint_version' }),
    });
    expect(screen.queryByTestId('detail-open-lint-report')).not.toBeInTheDocument();
  });
});

// =========================================================================================
// Trends
// =========================================================================================

describe('LintTrendsPanel', () => {
  it('splits remediation from policy, and totals each series over the window', () => {
    render(<LintTrendsPanel trends={trends(3)} />);
    expect(screen.getByTestId('trend-newFindings')).toHaveTextContent('6 in 30d');
    expect(screen.getByTestId('trend-remediatedFindings')).toHaveTextContent('3 in 30d');
    expect(screen.getByTestId('trend-waiversGranted')).toBeInTheDocument();
    expect(screen.getByTestId('trend-policyPackPublications')).toBeInTheDocument();
  });

  it('keeps both notes, which are the reason the split exists', () => {
    render(<LintTrendsPanel trends={trends(3)} />);
    expect(screen.getByText(/genuine fixes only/)).toBeInTheDocument();
    expect(screen.getByText(/attributable to fixes, not rule changes/)).toBeInTheDocument();
  });

  it('names each series to a screen reader rather than leaving a shape unlabelled', () => {
    render(<LintTrendsPanel trends={trends(3)} />);
    expect(
      screen.getByRole('img', { name: /New findings per day over the last 30 days/ })
    ).toBeInTheDocument();
  });

  it('shows the tab-level empty state when there is no series at all', () => {
    render(<LintTrendsPanel trends={null} />);
    expect(screen.getByText('No trend data yet')).toBeInTheDocument();
    render(<LintTrendsPanel trends={{ days: 30, series: [] }} />);
    expect(screen.getAllByText('No trend data yet')).toHaveLength(2);
  });
});

// =========================================================================================
// Quality ranks
// =========================================================================================

describe('LintQualityRanksPanel', () => {
  it('draws one card per (scope, format) with its distribution and its trend', () => {
    render(
      <LintQualityRanksPanel
        series={rankSeries({
          formats: [rankFormat(), rankFormat({ scope: 'export', formatKey: 'grpc' })],
        })}
        days={30}
        onDaysChange={jest.fn()}
      />
    );
    expect(screen.getByTestId('quality-rank-import-openapi-3.1')).toBeInTheDocument();
    expect(screen.getByTestId('quality-rank-export-grpc')).toBeInTheDocument();
    expect(screen.getByTestId('grade-distribution-openapi-3.1')).toBeInTheDocument();
    expect(screen.getByTestId('score-trend-openapi-3.1')).toBeInTheDocument();
  });

  it('reports the outcomes an import has and the ones an export has', () => {
    const { unmount } = render(
      <LintQualityRanksPanel series={rankSeries()} days={30} onDaysChange={jest.fn()} />
    );
    expect(screen.getByTestId('stat-secondary')).toHaveTextContent('Blocked');
    expect(screen.getByTestId('stat-tertiary')).toHaveTextContent('Warned');
    unmount();

    render(
      <LintQualityRanksPanel
        series={rankSeries({
          formats: [rankFormat({ scope: 'export', averageReadiness: 96, bestRank: 1 })],
        })}
        days={30}
        onDaysChange={jest.fn()}
      />
    );
    expect(screen.getByTestId('stat-secondary')).toHaveTextContent('Average readiness');
    expect(screen.getByTestId('stat-tertiary')).toHaveTextContent('Best rank');
  });

  it('renders an em dash rather than a zero for an unmeasured figure', () => {
    render(
      <LintQualityRanksPanel
        series={rankSeries({ formats: [rankFormat({ averageScore: null })] })}
        days={30}
        onDaysChange={jest.fn()}
      />
    );
    expect(within(screen.getByTestId('stat-primary')).getByText('—')).toBeInTheDocument();
  });

  it('states the drift, and says a format never drifted rather than calling it flat', () => {
    const { unmount } = render(
      <LintQualityRanksPanel series={rankSeries()} days={30} onDaysChange={jest.fn()} />
    );
    expect(screen.getByTestId('rank-drift')).toHaveTextContent('+6 pts over the window');
    unmount();

    render(
      <LintQualityRanksPanel
        series={rankSeries({ formats: [rankFormat({ scoreDelta: null })] })}
        days={30}
        onDaysChange={jest.fn()}
      />
    );
    expect(screen.getByTestId('rank-drift')).toHaveTextContent('No drift');
  });

  it('splits adapter findings from specification findings and says which is which', () => {
    render(<LintQualityRanksPanel series={rankSeries()} days={30} onDaysChange={jest.fn()} />);
    const attribution = screen.getByTestId('attribution-import-openapi-3.1');
    expect(attribution).toHaveTextContent('38% adapter · 62% specification');
    expect(attribution).toHaveTextContent('cannot read yet');
  });

  it('warns when the grades in a window came from more than one guide version', () => {
    render(
      <LintQualityRanksPanel
        series={rankSeries({ formats: [rankFormat({ styleGuideVersions: ['a', 'b'] })] })}
        days={30}
        onDaysChange={jest.fn()}
      />
    );
    expect(screen.getByTestId('rank-guide-drift-note')).toHaveTextContent(
      '2 style-guide versions'
    );
  });

  it('says the view was capped rather than implying it is the whole picture', () => {
    render(
      <LintQualityRanksPanel
        series={rankSeries({ truncated: true })}
        days={30}
        onDaysChange={jest.fn()}
      />
    );
    expect(screen.getByTestId('quality-rank-truncated')).toHaveTextContent('the busiest 6');
  });

  it('changes the window', () => {
    const onDaysChange = jest.fn();
    render(<LintQualityRanksPanel series={rankSeries()} days={30} onDaysChange={onDaysChange} />);
    fireEvent.click(screen.getByRole('radio', { name: '90d' }));
    expect(onDaysChange).toHaveBeenCalledWith(90);
  });

  it('distinguishes a window with no grades from a tab with no data at all', () => {
    const { unmount } = render(
      <LintQualityRanksPanel
        series={rankSeries({ formats: [] })}
        days={30}
        onDaysChange={jest.fn()}
      />
    );
    expect(screen.getByTestId('quality-rank-window-empty')).toBeInTheDocument();
    unmount();

    render(<LintQualityRanksPanel series={null} days={30} onDaysChange={jest.fn()} />);
    expect(screen.getByText('No quality-rank data yet')).toBeInTheDocument();
  });
});

// =========================================================================================
// The docs fixtures
// =========================================================================================

/** The address bar the page reads its filters from; each docs case sets its own. */
let mockSearchParams = new URLSearchParams();

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => '/ade/dashboard/lint-workspace',
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'u-ada', current_tenant_id: 't-acme', email: 'ada@acme.io' } },
    status: 'authenticated',
    update: jest.fn(),
  }),
  AuthSessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

/**
 * The documentation site's Lint posture page (`apiome-docs/screens.json`, DOCS-1.8) is captured
 * from these dumps:
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/lint-workspace-hive-redesign.test.tsx -t "docs fixtures"`
 *
 * They render the real page against a mocked API: an Acme tenant with three REST catalogs and
 * one MCP server, a queue of eight findings across every severity and most decision states,
 * three saved views and a month of trends.
 */
describe('the docs fixtures', () => {
  const originalFetch = global.fetch;

  /** The queue, as the findings endpoint sends it. */
  const DOCS_FINDINGS = [
    finding({
      sourceFingerprint: 'docs-f1',
      ruleId: 'no-http-basic',
      message: 'HTTP Basic auth scheme detected on the payouts surface.',
      location: { path: 'components.securitySchemes.basicAuth', line: 412 },
      projectId: 'p-payments',
      projectName: 'Payments API',
      subjectLabel: 'v2.4.0',
      compositeGrade: 'C',
      isNew: true,
    }),
    finding({
      sourceFingerprint: 'docs-f2',
      ruleId: 'oauth2-scopes-declared',
      message: 'Operation GET /accounts/{id} requires OAuth2 but declares no scopes.',
      location: { path: 'paths./accounts/{id}.get.security', line: 88 },
      remediation: { fix: 'List the scopes the operation needs, e.g. accounts:read.' },
      projectId: 'p-accounts',
      projectName: 'Accounts API',
      subjectLabel: 'v1.9.2',
      versionRecordId: 'ver_accounts_192',
      compositeGrade: 'B',
      isNew: true,
      evidenceRunId: 'run_a91c04',
    }),
    finding({
      sourceFingerprint: 'docs-f3',
      ruleId: 'no-secrets-in-examples',
      message: 'Tool example for create_journal_entry contains a live-looking API key.',
      location: { path: 'tools.create_journal_entry.examples[0].arguments.api_key' },
      remediation: { fix: 'Replace the value with a placeholder such as sk_test_….' },
      scannerId: 'apiome-mcp',
      profile: 'Acme MCP · trust pack',
      subjectType: 'mcp_endpoint_version',
      versionRecordId: null,
      mcpVersionId: 'mcpv_ledger_081',
      projectId: null,
      projectName: null,
      subjectLabel: 'Ledger MCP 0.8.1',
      compositeGrade: 'D',
      isNew: false,
      effectiveState: 'waiver_requested',
      evidenceRunId: 'run_mcp_5521',
      decision: {
        id: 'dec-ledger-secrets',
        projectId: null,
        state: 'waiver_requested',
        ownerUserId: 'u-grace',
        rationale: 'Sandbox key, rotated nightly; the example is generated from the test tenant.',
        linkedTicket: 'https://tracker.acme.io/SEC-2210',
        expiresAt: null,
      },
      latestPolicyEvaluationId: 'ev_mcp_3310',
    }),
    finding({
      sourceFingerprint: 'docs-f4',
      ruleId: 'operation-4xx-response',
      message: 'POST /payouts documents no 4xx response.',
      severity: 'warning',
      category: 'quality',
      axisKey: 'quality',
      location: { path: 'paths./payouts.post.responses', line: 640 },
      remediation: { fix: 'Document at least a 400 and a 422 response with a problem+json body.' },
      scannerId: 'spectral',
      profile: 'Acme REST · baseline',
      projectId: 'p-payments',
      projectName: 'Payments API',
      subjectLabel: 'v2.4.0',
      compositeGrade: 'C',
      isNew: false,
      effectiveState: 'acknowledged',
      decision: {
        id: 'dec-payouts-4xx',
        projectId: 'p-payments',
        state: 'acknowledged',
        ownerUserId: 'u-ada',
        rationale: null,
        linkedTicket: 'https://tracker.acme.io/PAY-1182',
        expiresAt: null,
      },
      policyPassed: true,
    }),
    finding({
      sourceFingerprint: 'docs-f5',
      ruleId: 'operation-description',
      message: 'Operation DELETE /inventory/items/{sku} has no description.',
      severity: 'warning',
      category: 'quality',
      axisKey: 'quality',
      location: { path: 'paths./inventory/items/{sku}.delete', line: 233 },
      remediation: { fix: 'Describe what the operation does and when it fails.' },
      scannerId: 'spectral',
      profile: 'Acme REST · baseline',
      projectId: 'p-inventory',
      projectName: 'Inventory API',
      subjectLabel: 'v3.0.0',
      versionRecordId: 'ver_inventory_300',
      compositeGrade: 'A',
      isNew: true,
      policyPassed: true,
    }),
    finding({
      sourceFingerprint: 'docs-f6',
      ruleId: 'tool-input-schema-strict',
      message: 'Tool post_transfer accepts additional properties in its input schema.',
      severity: 'warning',
      category: 'protocol',
      axisKey: 'protocol',
      location: { path: 'tools.post_transfer.inputSchema' },
      remediation: { fix: 'Set additionalProperties: false on the tool’s input schema.' },
      scannerId: 'apiome-mcp',
      profile: 'Acme MCP · trust pack',
      subjectType: 'mcp_endpoint_version',
      versionRecordId: null,
      mcpVersionId: 'mcpv_ledger_081',
      projectId: null,
      projectName: null,
      subjectLabel: 'Ledger MCP 0.8.1',
      compositeGrade: 'D',
      isNew: true,
    }),
    finding({
      sourceFingerprint: 'docs-f7',
      ruleId: 'sbom-license-declared',
      message: 'Generated SDK dependency left-pad@1.3.0 declares no licence.',
      severity: 'info',
      category: 'supply_chain',
      axisKey: 'supply_chain',
      location: { path: 'sbom.components[14].licenses' },
      remediation: null,
      scannerId: 'apiome-supply-chain',
      profile: 'Acme REST · supply chain',
      projectId: 'p-accounts',
      projectName: 'Accounts API',
      subjectLabel: 'v1.9.2',
      versionRecordId: 'ver_accounts_192',
      compositeGrade: 'B',
      isNew: false,
      effectiveState: 'waived',
      waived: true,
      decision: {
        id: 'dec-sbom-licence',
        projectId: 'p-accounts',
        state: 'waived',
        ownerUserId: 'u-grace',
        rationale: 'Upstream fix tracked; the package is MIT per its repository.',
        linkedTicket: 'https://tracker.acme.io/OSS-311',
        expiresAt: '2026-12-31T00:00:00Z',
      },
      policyPassed: true,
    }),
    finding({
      sourceFingerprint: 'docs-f8',
      ruleId: 'path-kebab-case',
      message: 'Path segment /inventory/stockLevels is not kebab-case.',
      severity: 'info',
      category: 'quality',
      axisKey: 'quality',
      location: { path: 'paths./inventory/stockLevels', line: 512 },
      remediation: { fix: 'Rename the segment to /inventory/stock-levels in the next major.' },
      scannerId: 'spectral',
      profile: 'Acme REST · baseline',
      projectId: 'p-inventory',
      projectName: 'Inventory API',
      subjectLabel: 'v3.0.0',
      versionRecordId: 'ver_inventory_300',
      compositeGrade: 'A',
      isNew: false,
      effectiveState: 'false_positive',
      decision: {
        id: 'dec-stock-levels',
        projectId: 'p-inventory',
        state: 'false_positive',
        ownerUserId: 'u-ada',
        rationale: 'Frozen public path; renaming is a breaking change already scheduled for v4.',
        linkedTicket: null,
        expiresAt: null,
      },
      policyPassed: true,
    }),
  ].map((row) => ({ ...row, evidenceCreatedAt: '2026-10-06T08:52:00Z' }));

  /** The two unwaived security errors the "Unwaived security errors" view narrows to. */
  const SECURITY_ERRORS = DOCS_FINDINGS.filter(
    (row) => row.severity === 'error' && row.axisKey === 'security' && row.effectiveState === 'open'
  );

  const DOCS_VIEWS = [
    savedView({
      id: 'view-security',
      name: 'Unwaived security errors',
      filters: { severity: ['error'], axis: ['security'], state: ['open'] },
      isPinned: true,
    }),
    savedView({
      id: 'view-waivers',
      name: 'Waivers to review',
      filters: { state: ['waiver_requested'] },
      isPinned: true,
    }),
    savedView({
      id: 'view-mcp',
      name: 'MCP protocol warnings',
      filters: { severity: ['warning'], axis: ['protocol'], subjectType: 'mcp_endpoint_version' },
      isPinned: false,
    }),
  ];

  const DOCS_SUMMARY = summary({
    subjects: { catalog_revisions: 11, mcp_endpoint_versions: 3 },
    gradeDistribution: { A: 4, B: 5, C: 2, D: 2, F: 0, ungraded: 1 },
    axes: [
      { key: 'quality', label: 'Quality', assessedCount: 14, notAssessedCount: 0, averageScore: 86, gradeDistribution: {}, severityCounts: {} },
      { key: 'protocol', label: 'Protocol', assessedCount: 3, notAssessedCount: 11, averageScore: 71, gradeDistribution: {}, severityCounts: {} },
      { key: 'security', label: 'Security', assessedCount: 12, notAssessedCount: 2, averageScore: 78, gradeDistribution: {}, severityCounts: {} },
      { key: 'supply_chain', label: 'Supply chain', assessedCount: 9, notAssessedCount: 5, averageScore: 92, gradeDistribution: {}, severityCounts: {} },
      { key: 'supportability', label: 'Supportability', assessedCount: 0, notAssessedCount: 14, averageScore: null, gradeDistribution: {}, severityCounts: {} },
    ],
    coverage: {
      missingCount: 2,
      subjects: [
        { subjectType: 'catalog_revision', subjectId: 'ver_inventory_300', projectId: 'p-inventory', subjectLabel: 'v3.0.0', missingAxes: ['security'] },
        { subjectType: 'mcp_endpoint_version', subjectId: 'mcpv_ledger_081', projectId: null, subjectLabel: 'Ledger MCP 0.8.1', missingAxes: ['supply_chain'] },
      ],
    },
    findings: { open: 31, new_count: 9, unwaived_errors: 6, unwaived_security_errors: 2 },
    waivers: { active: 5, requested: 1, expiring_soon: 1 },
  });

  /** Thirty days of remediation and policy activity. */
  const DOCS_TRENDS = {
    days: 30,
    series: Array.from({ length: 30 }, (_, index) => ({
      date: `2026-09-${String(index + 1).padStart(2, '0')}`,
      newFindings: [3, 1, 0, 4, 2, 0, 1][index % 7],
      remediatedFindings: [1, 2, 3, 1, 0, 2, 4][index % 7],
      waiversGranted: index % 9 === 0 ? 1 : 0,
      waiversExpired: index === 17 ? 1 : 0,
      markedFalsePositive: index % 11 === 0 ? 1 : 0,
      policyPackPublications: index === 4 || index === 21 ? 1 : 0,
    })),
  };

  /** What the findings endpoint answers for a query string. */
  function findingsReply(query: URLSearchParams) {
    const narrowed = query.get('severity') === 'error' && query.get('axis') === 'security';
    if (narrowed) {
      return {
        findings: SECURITY_ERRORS,
        count: SECURITY_ERRORS.length,
        total: SECURITY_ERRORS.length,
        limit: 50,
        offset: 0,
        facets: {
          severity: { error: 2 },
          effectiveState: { open: 2 },
          axis: { security: 2 },
          grade: { B: 1, C: 1 },
          scannerId: { 'apiome-security': 2 },
        },
      };
    }
    return {
      findings: DOCS_FINDINGS,
      count: DOCS_FINDINGS.length,
      total: DOCS_FINDINGS.length,
      limit: 50,
      offset: 0,
      facets: {
        severity: { error: 3, warning: 3, info: 2 },
        effectiveState: { open: 3, acknowledged: 1, waiver_requested: 1, waived: 1, false_positive: 1 },
        axis: { quality: 3, security: 3, protocol: 1, supply_chain: 1 },
        grade: { A: 2, B: 2, C: 2, D: 2 },
        scannerId: { spectral: 3, 'apiome-security': 2, 'apiome-mcp': 2, 'apiome-supply-chain': 1 },
      },
    };
  }

  /** Answer every read the page and its drawer make. */
  function installDocsFetch() {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      let body: Record<string, unknown> = {};
      if (url.pathname === '/api/lint/workspace/findings') body = findingsReply(url.searchParams);
      else if (url.pathname === '/api/lint/workspace/summary') body = { ...DOCS_SUMMARY };
      else if (url.pathname === '/api/lint/workspace/trends') body = { ...DOCS_TRENDS };
      else if (url.pathname === '/api/lint/workspace/quality-ranks') body = { ...rankSeries() };
      else if (url.pathname === '/api/lint/workspace/views') body = { views: DOCS_VIEWS };
      else if (url.pathname.startsWith('/api/lint/decisions/')) {
        body = {
          events: [
            {
              id: 'evt-1',
              beforeState: null,
              afterState: 'open',
              rationale: null,
              actorLabel: null,
              createdAt: 'Sep 28, 2026 09:14',
            },
            {
              id: 'evt-2',
              beforeState: 'open',
              afterState: 'waiver_requested',
              rationale: 'Sandbox key, rotated nightly; the example is generated from the test tenant.',
              actorLabel: 'Grace Hopper',
              createdAt: 'Oct 2, 2026 16:40',
            },
          ],
        };
      }
      return { ok: true, status: 200, statusText: 'OK', json: async () => ({ success: true, ...body }) };
    }) as unknown as typeof fetch;
  }

  /** The page root. */
  const pageRoot = () => document.querySelector('.page') as HTMLElement;

  /** Render the page and wait for the queue, the summary and the views to land. */
  async function renderPage(query = '') {
    mockSearchParams = new URLSearchParams(query);
    installDocsFetch();
    render(<LintWorkspacePage />);
    await screen.findByTestId('lint-workspace-summary');
    await waitFor(() => expect(screen.getAllByTestId('saved-view-chip')).toHaveLength(3));
    await screen.findAllByText('no-http-basic');
    // Let the trend and rank reads settle before anything is written.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  }

  /** Tick rows of the queue by their rule id. */
  function selectRows(ruleIds: string[]) {
    const table = screen.getByRole('table');
    for (const ruleId of ruleIds) {
      const row = within(table).getByText(ruleId).closest('tr') as HTMLElement;
      fireEvent.click(within(row).getByRole('checkbox'));
    }
  }

  afterEach(() => {
    global.fetch = originalFetch;
    mockSearchParams = new URLSearchParams();
  });

  it('writes the page and the finding drawer', async () => {
    await renderPage();
    expect(screen.getByTestId('tab-queue')).toHaveTextContent('8');
    writeA11yFixture('lint-posture', liveMarkup(pageRoot()));

    fireEvent.click(within(screen.getByRole('table')).getByText('no-secrets-in-examples'));
    const drawer = await screen.findByTestId('finding-detail-drawer');
    await waitFor(() => expect(screen.getAllByTestId('detail-history-event')).toHaveLength(2));
    writeA11yFixture('lint-posture-finding', liveMarkup(drawer));
  });

  it('writes the queue narrowed by the "Unwaived security errors" view', async () => {
    await renderPage('severity=error&axis=security&state=open');
    const current = screen
      .getAllByTestId('saved-view-chip')
      .find((chip) => chip.hasAttribute('data-current'));
    expect(current).toHaveTextContent('Unwaived security errors');
    expect(screen.getByTestId('workspace-clear-filters')).toHaveTextContent('Clear filters (3)');
    writeA11yFixture('lint-posture-filtered', liveMarkup(pageRoot()));
  });

  it('writes the bulk bar, the owner assignment and both waiver dialogs', async () => {
    await renderPage();
    selectRows(['no-http-basic', 'oauth2-scopes-declared', 'operation-description']);
    expect(screen.getByText('3 findings selected')).toBeInTheDocument();
    writeA11yFixture('lint-posture-bulk', liveMarkup(pageRoot()));

    fireEvent.change(screen.getByTestId('bulk-owner-input'), { target: { value: 'u-grace' } });
    expect(screen.getByTestId('bulk-assign-owner')).toBeEnabled();
    writeA11yFixture('lint-posture-assign', liveMarkup(pageRoot()));
    fireEvent.change(screen.getByTestId('bulk-owner-input'), { target: { value: '' } });

    fireEvent.click(screen.getByTestId('bulk-waiver_requested'));
    const request = await screen.findByTestId('waiver-dialog');
    expect(request).toHaveTextContent('Request waiver for 3 findings');
    fireEvent.change(screen.getByTestId('waiver-rationale'), {
      target: {
        value:
          'Partner integrations still authenticate with Basic until the OAuth2 migration ships in Q1.',
      },
    });
    fireEvent.change(screen.getByTestId('waiver-ticket'), {
      target: { value: 'https://tracker.acme.io/SEC-2231' },
    });
    fireEvent.change(screen.getByTestId('waiver-expires'), { target: { value: '2026-12-31' } });
    expect(screen.getByTestId('waiver-submit')).toBeEnabled();
    writeA11yFixture('lint-posture-waive', liveMarkup(request));
    fireEvent.click(within(request).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByTestId('waiver-dialog')).not.toBeInTheDocument());

    fireEvent.click(screen.getByTestId('bulk-waived'));
    const approve = await screen.findByTestId('waiver-dialog');
    expect(approve).toHaveTextContent('Approve waiver for 3 findings');
    fireEvent.change(screen.getByTestId('waiver-rationale'), {
      target: { value: 'Accepted by the security review board on Oct 6; re-scan after migration.' },
    });
    fireEvent.change(screen.getByTestId('waiver-ticket'), {
      target: { value: 'https://tracker.acme.io/SEC-2231' },
    });
    fireEvent.change(screen.getByTestId('waiver-expires'), { target: { value: '2027-01-31' } });
    expect(screen.getByTestId('waiver-permission-note')).toBeInTheDocument();
    writeA11yFixture('lint-posture-waive-approve', liveMarkup(approve));
  });

  it('writes the save-view dialog, the trends tab and the quality ranks tab', async () => {
    await renderPage('severity=warning&axis=protocol');
    fireEvent.click(screen.getByTestId('lint-workspace-save-view'));
    const dialog = await screen.findByTestId('saved-view-dialog');
    fireEvent.change(screen.getByTestId('saved-view-name'), {
      target: { value: 'Protocol warnings' },
    });
    expect(screen.getByTestId('saved-view-query')).toHaveTextContent('severity=warning');
    writeA11yFixture('lint-posture-save-view', liveMarkup(dialog));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByTestId('saved-view-dialog')).not.toBeInTheDocument());

    mockSearchParams = new URLSearchParams();
    fireEvent.click(screen.getByTestId('tab-trends'));
    await screen.findByTestId('lint-workspace-trends');
    writeA11yFixture('lint-posture-trends', liveMarkup(pageRoot()));

    fireEvent.click(screen.getByTestId('tab-ranks'));
    await screen.findByTestId('lint-workspace-quality-ranks');
    writeA11yFixture('lint-posture-ranks', liveMarkup(pageRoot()));
  });
});
