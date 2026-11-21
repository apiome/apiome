/**
 * "Apply fix" in the Lint report and the Lint posture drawer, rendered — GVM-3.6 (#5874).
 *
 * The Versions badge's report dialog shows a *Fix* chip on fixable findings and *Apply N
 * deterministic fixes*, renders the reason of a breaking / conflicting fix, shows a published
 * revision's fixes read-only, and applies through the reason dialog then re-reads the stored
 * report. The finding drawer offers *Apply fix* for a ready catalog-revision fix and explains
 * why an MCP endpoint finding has none.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { VersionLintBadge } from '../src/app/components/ade/dashboard/VersionLintBadge';
import LintFindingDrawer from '../src/app/components/ade/lintWorkspace/LintFindingDrawer';
import { finding } from './helpers/lint-workspace-fixtures';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const RULES = { success: true, rules: [], count: 0 };

const REPORT = {
  success: true,
  projectId: 'p1',
  versionRecordId: 'v1',
  versionId: '1.0.0',
  score: 80,
  grade: 'B',
  findings: [
    {
      id: 'lint-a',
      path: 'paths./pets.get',
      category: 'naming',
      rule: 'operation-id-required',
      severity: 'warning',
      message: 'Operation has no operationId.',
    },
    {
      id: 'lint-b',
      path: 'components.schemas.Pet',
      category: 'naming',
      rule: 'enum-casing',
      severity: 'warning',
      message: 'Enum values are not UPPER_CASE.',
    },
    {
      id: 'lint-c',
      path: 'paths./pets',
      category: 'docs',
      rule: 'description-required',
      severity: 'info',
      message: 'No description.',
    },
    {
      id: 'lint-z',
      path: 'info',
      category: 'docs',
      rule: 'info-contact',
      severity: 'info',
      message: 'No contact.',
    },
  ],
  ruleHits: {},
  severityCounts: { error: 0, warning: 2, info: 2 },
  reportFingerprint: 'fp',
  baseRevisionId: null,
  compatibilityOverall: null,
};

/** The plan for REPORT: one ready, one breaking, one conflict. */
function planBody(published = false) {
  const base = {
    fixClass: 'fill-in',
    wireVisible: false,
    pointer: '/x',
    message: '',
    ops: [],
    reason: null,
  };
  return {
    success: true,
    projectId: 'p1',
    versionRecordId: 'v1',
    counts: { ready: 1, breaking: 1, conflict: 1 },
    published,
    entries: [
      {
        ...base,
        fixId: 'fix-a',
        ruleId: 'operation-id-required',
        path: 'paths./pets.get',
        findingId: 'lint-a',
        status: 'ready',
      },
      {
        ...base,
        fixId: 'fix-b',
        ruleId: 'enum-casing',
        path: 'components.schemas.Pet',
        findingId: 'lint-b',
        status: 'breaking',
        classification: {
          changes: [{ ruleId: 'enum-value-removed', severity: 'breaking', pointer: '/x' }],
        },
      },
      {
        ...base,
        fixId: 'fix-c',
        ruleId: 'description-required',
        path: 'paths./pets',
        findingId: 'lint-c',
        status: 'conflict',
        conflictsWith: 'fix-a',
      },
    ],
  };
}

const APPLIED = {
  success: true,
  projectId: 'p1',
  sourceVersionRecordId: 'v1',
  versionRecordId: 'v2',
  versionLabel: '1.0.1',
  appliedFixIds: ['fix-a'],
  skipped: [],
  score: 88,
  grade: 'B',
};

/** Route the mocked fetch by URL. */
function routeFetch(published = false) {
  return jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const reply = (body: unknown, ok = true, status = 200) =>
      Promise.resolve({ ok, status, json: async () => body });
    if (url.includes('/api/lint/rules')) return reply(RULES);
    if (url.endsWith('/lint/fixes/apply') && init?.method === 'POST')
      return reply(APPLIED, true, 201);
    if (url.endsWith('/lint/fixes')) return reply(planBody(published));
    if (url.includes('/lint')) return reply(REPORT);
    return reply({ success: false }, false, 404);
  });
}

describe('Lint report dialog — Apply fix', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  async function openReport(published = false) {
    const fetchMock = routeFetch(published);
    global.fetch = fetchMock as unknown as typeof fetch;
    const onFixApplied = jest.fn();
    render(
      <VersionLintBadge
        projectId="p1"
        versionId="v1"
        versionLabel="1.0.0"
        storedScore={80}
        storedGrade="B"
        onFixApplied={onFixApplied}
      />,
    );
    fireEvent.click(screen.getByTestId('version-lint-badge'));
    await screen.findByTestId('lint-fix-bar');
    return { fetchMock, onFixApplied };
  }

  it('shows a Fix chip on the fixable finding and the reason on breaking and conflicting ones', async () => {
    await openReport();
    await waitFor(() => expect(screen.getAllByTestId('lint-fix-row')).toHaveLength(3));
    expect(screen.getByTestId('lint-fix-chip')).toHaveTextContent('Fix');
    const rows = screen.getAllByTestId('lint-fix-row');
    const breaking = rows.find((row) => row.getAttribute('data-status') === 'breaking')!;
    expect(breaking).toHaveTextContent(/breaking change \(enum-value-removed\)/);
    const conflict = rows.find((row) => row.getAttribute('data-status') === 'conflict')!;
    expect(conflict).toHaveTextContent(/as fix-a/);
    expect(screen.getByTestId('lint-fix-apply-all')).toHaveTextContent('Apply 1 deterministic fix');
  });

  it('applies through the reason dialog, links the new revision and re-reads the report', async () => {
    const { fetchMock, onFixApplied } = await openReport();
    fireEvent.click(await screen.findByTestId('lint-fix-chip'));
    const dialog = await screen.findByTestId('lint-fix-apply-dialog');
    expect(within(dialog).getByTestId('lint-fix-reason')).toHaveValue(
      'Apply the deterministic operation-id-required fix.',
    );
    fireEvent.change(within(dialog).getByTestId('lint-fix-reason'), {
      target: { value: 'Name the pets operation' },
    });
    fireEvent.click(within(dialog).getByTestId('lint-fix-submit'));

    const note = await screen.findByTestId('lint-fix-result');
    expect(note).toHaveTextContent('Applied 1 fix as a new revision v1.0.1');
    expect(note).toHaveTextContent('B · 88/100');
    expect(screen.getByTestId('lint-fix-result-link')).toHaveAttribute(
      'href',
      '/ade/dashboard/versions?projectId=p1',
    );
    const apply = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/apply'))!;
    expect(JSON.parse(String(apply[1]?.body))).toEqual({
      fixIds: ['fix-a'],
      reason: 'Name the pets operation',
    });
    expect(onFixApplied).toHaveBeenCalledTimes(1);
    // The stored report is read again after the apply.
    const reportReads = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/v1/lint'));
    expect(reportReads.length).toBeGreaterThanOrEqual(2);
  });

  it('shows a published revision’s fixes read-only with the refusal reason', async () => {
    await openReport(true);
    expect(await screen.findByTestId('lint-fix-published')).toHaveTextContent(
      'This revision is published, so fixes cannot be applied to it.',
    );
    expect(screen.queryByTestId('lint-fix-apply-all')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lint-fix-chip')).not.toBeInTheDocument();
    expect(await screen.findByTestId('lint-fix-chip-readonly')).toBeInTheDocument();
  });
});

describe('Lint posture drawer — Apply fix', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  function renderDrawer(props: Partial<React.ComponentProps<typeof LintFindingDrawer>> = {}) {
    const handlers = {
      onClose: jest.fn(),
      onDecision: jest.fn(),
      onRequestWaiver: jest.fn(),
      onApplyFix: jest.fn(),
    };
    render(
      <LintFindingDrawer
        finding={finding({ sourceFingerprint: 'lint-a' })}
        {...handlers}
        {...props}
      />,
    );
    return handlers;
  }

  it('offers Apply fix for a ready catalog-revision fix', async () => {
    global.fetch = routeFetch() as unknown as typeof fetch;
    const handlers = renderDrawer();
    expect(await screen.findByTestId('detail-fix-ready')).toHaveTextContent('fill-in');
    fireEvent.click(screen.getByTestId('detail-apply-fix'));
    expect(handlers.onApplyFix).toHaveBeenCalledWith(
      expect.objectContaining({ sourceFingerprint: 'lint-a' }),
    );
  });

  it('explains why an MCP endpoint finding has no fix, without planning', () => {
    const fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    renderDrawer({
      finding: finding({
        subjectType: 'mcp_endpoint_version',
        versionRecordId: null,
        mcpVersionId: 'mcp1',
      }),
    });
    expect(screen.getByTestId('detail-fix-unsupported')).toHaveTextContent(
      'MCP endpoint findings have no document to fix',
    );
    expect(screen.queryByTestId('detail-apply-fix')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/lint/fixes'))).toBe(false);
  });

  it('renders the reason of a breaking fix and offers no Apply fix', async () => {
    global.fetch = routeFetch() as unknown as typeof fetch;
    renderDrawer({ finding: finding({ sourceFingerprint: 'lint-b' }) });
    expect(await screen.findByTestId('detail-fix-reason')).toHaveTextContent(/breaking change/);
    expect(screen.queryByTestId('detail-apply-fix')).not.toBeInTheDocument();
  });

  it('shows a published revision as read-only', async () => {
    global.fetch = routeFetch(true) as unknown as typeof fetch;
    renderDrawer();
    expect(await screen.findByTestId('detail-fix-published')).toHaveTextContent('published');
    expect(screen.queryByTestId('detail-apply-fix')).not.toBeInTheDocument();
  });

  it('shows the new revision and the observed Fixed state after an apply', async () => {
    global.fetch = routeFetch() as unknown as typeof fetch;
    const target = finding({ sourceFingerprint: 'lint-a', effectiveState: 'fixed' });
    renderDrawer({
      finding: target,
      fixOutcome: {
        revisions: [
          {
            projectId: 'p1',
            sourceVersionRecordId: 'ver_2f0a91',
            result: { ...APPLIED, sourceVersionRecordId: 'ver_2f0a91' },
          },
        ],
        fixed: [target],
        remaining: [],
        skipped: [],
        states: { 'lint-a': 'fixed' },
        markError: null,
      },
    });
    expect(await screen.findByTestId('detail-fix-observed')).toHaveTextContent('no longer reports');
    expect(screen.getByTestId('lint-fix-result-link')).toHaveTextContent('v1.0.1');
    expect(screen.queryByTestId('detail-apply-fix')).not.toBeInTheDocument();
  });
});

// =========================================================================================
// Docs screenshot fixtures (`A11Y_FIXTURE_DUMP=1`): lint-report-apply-fix, lint-posture-apply-fix
// =========================================================================================

describe('fixture', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('writes the lint report with its Fix chip, Apply bar and breaking / conflict reasons', async () => {
    global.fetch = routeFetch() as unknown as typeof fetch;
    render(
      <VersionLintBadge
        projectId="p1"
        versionId="v1"
        versionLabel="1.0.0"
        storedScore={80}
        storedGrade="B"
      />,
    );
    fireEvent.click(screen.getByTestId('version-lint-badge'));
    await waitFor(() => expect(screen.getAllByTestId('lint-fix-row')).toHaveLength(3));
    writeA11yFixture('lint-report-apply-fix', liveMarkup(screen.getByRole('dialog')));
  });

  it('writes the finding drawer with a ready fix and Apply fix', async () => {
    global.fetch = routeFetch() as unknown as typeof fetch;
    render(
      <LintFindingDrawer
        finding={finding({
          sourceFingerprint: 'lint-a',
          ruleId: 'operation-id-required',
          message: 'Operation GET /pets has no operationId.',
          severity: 'warning',
          category: 'naming',
          axisKey: 'quality',
          scannerId: 'apiome-lint',
          location: { path: 'paths./pets.get' },
          remediation: null,
        })}
        onClose={jest.fn()}
        onDecision={jest.fn()}
        onRequestWaiver={jest.fn()}
        onApplyFix={jest.fn()}
      />,
    );
    await screen.findByTestId('detail-fix-ready');
    writeA11yFixture(
      'lint-posture-apply-fix',
      liveMarkup(screen.getByTestId('finding-detail-drawer')),
    );
  });
});
