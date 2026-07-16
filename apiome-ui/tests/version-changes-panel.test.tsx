/**
 * "Changes" tab panel on the Versions dashboard (CTG-3.2, #4476).
 *
 * Renders the stored `ctg.changelog.v1` changelog for a selected published
 * revision: severity badges per version, grouped entries (breaking first), and
 * per-entry deep links into the diff view. Also covers the initial-publication,
 * failed, and pending (no stored row) states.
 */
import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

import {
  VersionChangesPanel,
  type VersionChangesVersionRow,
} from '../src/app/ade/dashboard/versions/VersionChangesPanel';

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const REV_2 = '22222222-2222-4222-8222-222222222222';
const REV_1 = '11111111-1111-4111-8111-111111111111';

const VERSIONS: VersionChangesVersionRow[] = [
  { id: REV_1, project_id: PROJECT_ID, version_id: '1.0.0', published: true, published_at: '2026-06-01T00:00:00Z' },
  { id: REV_2, project_id: PROJECT_ID, version_id: '2.0.0', published: true, published_at: '2026-07-01T00:00:00Z' },
  { id: 'draft', project_id: PROJECT_ID, version_id: '2.1.0', published: false, published_at: null },
];

function summariesPayload() {
  return {
    success: true,
    projectId: PROJECT_ID,
    filteredCount: 2,
    changelogs: [
      {
        publishedRevisionId: REV_2,
        versionLabel: '2.0.0',
        publishedAt: '2026-07-01T00:00:00Z',
        baselineRevisionId: REV_1,
        baselineVersionLabel: '1.0.0',
        status: 'ready',
        maxSeverity: 'breaking',
        counts: { breaking: 1, 'non-breaking': 1, 'docs-only': 0, unclassified: 0, total: 2 },
      },
      {
        publishedRevisionId: REV_1,
        versionLabel: '1.0.0',
        publishedAt: '2026-06-01T00:00:00Z',
        baselineRevisionId: null,
        baselineVersionLabel: null,
        status: 'initial',
        maxSeverity: null,
        counts: { total: 0 },
      },
    ],
  };
}

function readyChangelogPayload() {
  return {
    success: true,
    changelog: {
      publishedRevisionId: REV_2,
      baselineRevisionId: REV_1,
      versionLabel: '2.0.0',
      baselineVersionLabel: '1.0.0',
      publishedAt: '2026-07-01T00:00:00Z',
      status: 'ready',
      maxSeverity: 'breaking',
      error: null,
      changelog: {
        schemaVersion: 'ctg.changelog.v1',
        fromVersion: '1.0.0',
        toVersion: '2.0.0',
        counts: { breaking: 1, 'non-breaking': 1, 'docs-only': 0, unclassified: 0, total: 2 },
        maxSeverity: 'breaking',
        entries: [
          {
            severity: 'breaking',
            pathGroup: '/pets',
            pointer: '/paths/~1pets/get',
            ruleId: 'operation-removed',
            changeKind: 'removed',
            summary: 'GET /pets was removed',
          },
          {
            severity: 'non-breaking',
            pathGroup: 'components.schemas',
            pointer: '/components/schemas/Pet/properties/nickname',
            ruleId: 'property-added',
            changeKind: 'added',
            summary: 'Optional property nickname added',
          },
        ],
      },
    },
  };
}

function initialChangelogPayload() {
  return {
    success: true,
    changelog: {
      publishedRevisionId: REV_1,
      baselineRevisionId: null,
      versionLabel: '1.0.0',
      baselineVersionLabel: null,
      publishedAt: '2026-06-01T00:00:00Z',
      status: 'initial',
      maxSeverity: null,
      error: null,
      changelog: {
        schemaVersion: 'ctg.changelog.v1',
        initialPublication: true,
        fromVersion: null,
        toVersion: '1.0.0',
        counts: { total: 0 },
        maxSeverity: null,
        entries: [],
      },
    },
  };
}

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, statusText: ok ? 'OK' : 'Error', json: async () => body } as Response;
}

let detailResponses: Record<string, { body: unknown; status?: number }>;

beforeEach(() => {
  detailResponses = {
    [REV_2]: { body: readyChangelogPayload() },
    [REV_1]: { body: initialChangelogPayload() },
  };
  global.fetch = jest.fn(async (url: string) => {
    if (url.includes('/changelogs')) {
      return jsonResponse(summariesPayload());
    }
    const m = url.match(/\/api\/versions\/([^/]+)\/changelog\?/);
    if (m) {
      const conf = detailResponses[m[1]];
      if (!conf) return jsonResponse({ success: false, error: 'not found' }, false, 404);
      return jsonResponse(conf.body, (conf.status ?? 200) < 400, conf.status ?? 200);
    }
    throw new Error(`Unexpected fetch: ${url}`);
  }) as unknown as typeof fetch;
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('VersionChangesPanel', () => {
  it('lists published revisions (newest first) with stored severity badges', async () => {
    render(<VersionChangesPanel projectId={PROJECT_ID} versions={VERSIONS} onOpenDiff={jest.fn()} />);

    const v2 = await screen.findByTestId(`changes-version-${REV_2}`);
    const v1 = screen.getByTestId(`changes-version-${REV_1}`);
    expect(within(v2).getByText('v2.0.0')).toBeInTheDocument();
    await waitFor(() => expect(within(v2).getByText('Breaking')).toBeInTheDocument());
    expect(within(v1).getByText('Initial')).toBeInTheDocument();
    // Drafts are not listed.
    expect(screen.queryByText('v2.1.0')).not.toBeInTheDocument();
  });

  it('renders the stored changelog grouped by severity then path, breaking first', async () => {
    render(<VersionChangesPanel projectId={PROJECT_ID} versions={VERSIONS} onOpenDiff={jest.fn()} />);

    await screen.findByTestId('changes-section-breaking');
    const sections = screen.getAllByTestId(/changes-section-/);
    expect(sections[0]).toHaveAttribute('data-testid', 'changes-section-breaking');
    expect(sections[1]).toHaveAttribute('data-testid', 'changes-section-non-breaking');

    const breaking = screen.getByTestId('changes-section-breaking');
    expect(within(breaking).getByText('GET /pets was removed')).toBeInTheDocument();
    expect(within(breaking).getByText('/paths/~1pets/get')).toBeInTheDocument();
    expect(screen.getByTestId('changes-max-severity')).toHaveTextContent('Breaking');
    expect(screen.getByTestId('changes-count-breaking')).toHaveTextContent('1 breaking');
  });

  it('deep-links each entry to the diff view for the classified pair', async () => {
    const onOpenDiff = jest.fn();
    render(<VersionChangesPanel projectId={PROJECT_ID} versions={VERSIONS} onOpenDiff={onOpenDiff} />);

    const links = await screen.findAllByTestId('changes-entry-diff-link');
    await userEvent.click(links[0]);
    expect(onOpenDiff).toHaveBeenCalledWith(REV_1, REV_2, '/paths/~1pets/get');
  });

  it('shows the initial-publication state without diff links', async () => {
    render(<VersionChangesPanel projectId={PROJECT_ID} versions={VERSIONS} onOpenDiff={jest.fn()} />);

    await screen.findByTestId(`changes-version-${REV_1}`);
    await userEvent.click(screen.getByTestId(`changes-version-${REV_1}`));

    await screen.findByTestId('changes-initial');
    expect(screen.getByText(/first published version/)).toBeInTheDocument();
    expect(screen.queryAllByTestId('changes-entry-diff-link')).toHaveLength(0);
  });

  it('renders a pending state when no changelog row is stored (404)', async () => {
    detailResponses[REV_2] = { body: { success: false, error: 'No changelog stored' }, status: 404 };
    render(<VersionChangesPanel projectId={PROJECT_ID} versions={VERSIONS} onOpenDiff={jest.fn()} />);

    await screen.findByText(/Changelog not available yet/);
    expect(screen.queryByText('No changelog stored')).not.toBeInTheDocument();
  });

  it('surfaces failed classification with the stored error', async () => {
    detailResponses[REV_2] = {
      body: {
        success: true,
        changelog: {
          ...readyChangelogPayload().changelog,
          status: 'failed',
          maxSeverity: null,
          error: 'reconstruction failed',
          changelog: null,
        },
      },
    };
    render(<VersionChangesPanel projectId={PROJECT_ID} versions={VERSIONS} onOpenDiff={jest.fn()} />);

    const failed = await screen.findByTestId('changes-failed');
    expect(failed).toHaveTextContent('reconstruction failed');
  });

  it('shows an empty state when the project has no published versions', () => {
    render(
      <VersionChangesPanel
        projectId={PROJECT_ID}
        versions={[{ id: 'x', project_id: PROJECT_ID, version_id: '0.1.0', published: false, published_at: null }]}
        onOpenDiff={jest.fn()}
      />,
    );
    expect(screen.getByText('No Published Versions')).toBeInTheDocument();
  });
});
