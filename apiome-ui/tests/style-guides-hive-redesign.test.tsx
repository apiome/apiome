/**
 * The style-guides redesign, rendered (HIVE-5.6, #5309).
 *
 * `style-guides-model.test.ts` holds the derivations and `style-guides-screen.test.tsx` holds
 * the REST contract, which this ticket did not change. This holds what the redesign *is*,
 * against a mocked `global.fetch` returning the `{success, data}` envelopes the proxies
 * really answer with — the ticket's four acceptance criteria and the mockup's
 * **Keeps (1:1)** list:
 *
 *   1. **The built-in guide stays read-only with its duplicate path**, asserted on the row's
 *      controls rather than on the model that decides them.
 *   2. **Assignment chips reflect tenant-default and per-project assignments.**
 *   3. **Non-admins see the read-only treatment**: a banner that says who may use the verbs
 *      and what a member can still do, where the screen this replaces removed the controls
 *      and said nothing at all.
 *   4. **Empty and loading states are present**, and a failed read is never drawn as an empty
 *      workspace.
 *
 * Plus the two additions the redesign makes: the toolbar's search and facet chips, and a
 * delete confirm that names what the deletion actually costs.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import StyleGuidesClient from '../src/app/ade/dashboard/style-guides/StyleGuidesClient';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

// ---------------------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------------------

/** One guide as `GET /api/style-guides` returns it. */
interface Row {
  id: string;
  name: string;
  description: string | null;
  source: 'builtin' | 'custom';
  isDefault: boolean;
  ruleCount: number;
  enabledRuleCount: number;
  tenantAssigned: boolean;
  projectAssignments: { projectId: string; projectName: string }[];
  createdAt: string | null;
  updatedAt: string | null;
}

/**
 * Build one guide row.
 *
 * @param over What this guide differs by.
 * @returns The row.
 */
function row(over: Partial<Row> & { id: string; name: string }): Row {
  return {
    description: 'House rules for public REST APIs.',
    source: 'custom',
    isDefault: false,
    ruleCount: 41,
    enabledRuleCount: 34,
    tenantAssigned: false,
    projectAssignments: [],
    createdAt: '2026-07-01T00:00:00Z',
    updatedAt: '2026-08-14T16:22:00Z',
    ...over,
  };
}

const BUILTIN = row({
  id: 'g-builtin',
  name: 'Apiome Recommended',
  source: 'builtin',
  description: 'Apiome’s baseline OpenAPI & AsyncAPI ruleset.',
  enabledRuleCount: 41,
  updatedAt: null,
});

const DEFAULT_GUIDE = row({
  id: 'g-default',
  name: 'Acme REST',
  isDefault: true,
  projectAssignments: [{ projectId: 'p-1', projectName: 'Payments API' }],
});

const ORPHAN = row({
  id: 'g-orphan',
  name: 'Partner API strict',
  description: 'Everything in Acme REST at error severity.',
  enabledRuleCount: 41,
  updatedAt: '2026-08-03T09:48:00Z',
});

const GUIDES = [BUILTIN, DEFAULT_GUIDE, ORPHAN];

const PROJECTS = [
  { id: 'p-1', name: 'Payments API' },
  { id: 'p-2', name: 'Inventory Events' },
];

// ---------------------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------------------

/** Every call the mocked proxies saw. */
let calls: { url: string; method: string; body: unknown }[] = [];

/** What the next read answers with. Reassigned per test. */
let guidesResponse: { ok: boolean; rows: Row[]; error?: string } = { ok: true, rows: GUIDES };

/** Whether the signed-in viewer administers the tenant. */
let isAdmin = true;

/** What the next mutation answers with. */
let mutationResponse: { ok: boolean; error?: string } = { ok: true };

/**
 * A `{success, data}` proxy answer.
 *
 * @param payload The envelope.
 * @returns A resolved `Response` double.
 */
function jsonResponse(payload: unknown) {
  return Promise.resolve({
    status: 200,
    json: () => Promise.resolve(payload),
  } as Response);
}

/** Install a `fetch` double for the style-guide, access and project proxies. */
function mockFetch() {
  const fn = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method || 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : null });

    if (url.includes('/api/access/permissions/me')) {
      return jsonResponse({ success: true, data: { is_admin: isAdmin, permissions: [] } });
    }
    if (url.includes('/api/projects')) {
      return jsonResponse({ success: true, projects: PROJECTS });
    }
    if (url.startsWith('/api/style-guides') && method === 'GET') {
      return guidesResponse.ok
        ? jsonResponse({ success: true, data: { guides: guidesResponse.rows, count: guidesResponse.rows.length } })
        : jsonResponse({ success: false, error: guidesResponse.error });
    }
    if (url.startsWith('/api/style-guides')) {
      return mutationResponse.ok
        ? jsonResponse({ success: true, data: {} })
        : jsonResponse({ success: false, error: mutationResponse.error });
    }
    // The two policy panels load on their own tab; nothing here exercises them.
    return jsonResponse({ success: true, data: null });
  });
  // @ts-expect-error - assigning a test double to the global
  global.fetch = fn;
  return fn;
}

beforeEach(() => {
  calls = [];
  isAdmin = true;
  guidesResponse = { ok: true, rows: GUIDES };
  mutationResponse = { ok: true };
  mockFetch();
});

/** Render the page and wait for the guide list to land. */
async function renderPage() {
  const view = render(<StyleGuidesClient />);
  await waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/style-guides'))).toBe(true));
  return view;
}

/**
 * A facet chip by its testid.
 *
 * @param key The facet key.
 * @returns The chip.
 */
function chip(key: string): HTMLElement {
  return screen.getByTestId(`style-guides-facet-${key}`);
}

// ---------------------------------------------------------------------------------------
// 1. The page and its tabs
// ---------------------------------------------------------------------------------------

describe('the page', () => {
  it('keeps the title, the description and the three governance tabs', async () => {
    await renderPage();

    expect(screen.getByRole('heading', { name: 'Style guides', level: 1 })).toBeInTheDocument();
    expect(
      screen.getByText('Governance rules your specs are scored against.')
    ).toBeInTheDocument();

    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(3);
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
  });

  it('counts the guides on the first tab once they have loaded', async () => {
    await renderPage();
    await screen.findByText('Acme REST');
    expect(screen.getByTestId('style-guides-tab-guides')).toHaveTextContent('3');
  });

  it('keeps the header actions with the list they belong to', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');
    expect(screen.getByTestId('style-guides-create')).toBeInTheDocument();

    await user.click(screen.getByTestId('style-guides-tab-verification'));

    expect(screen.queryByTestId('style-guides-create')).not.toBeInTheDocument();
    expect(screen.queryByTestId('style-guides-start-recommended')).not.toBeInTheDocument();
  });

  it('mounts only the tab that is showing, so an unopened panel costs nothing', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');
    expect(screen.queryByTestId('quality-policy-panel')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('style-guides-tab-quality'));

    expect(await screen.findByTestId('style-guides-panel-quality')).toBeInTheDocument();
    expect(screen.queryByTestId('style-guides-table')).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// 2. The list — the first two acceptance criteria
// ---------------------------------------------------------------------------------------

describe('the guides list', () => {
  it('draws each guide with its badges, rule count and updated date', async () => {
    await renderPage();

    const table = await screen.findByTestId('style-guides-table');
    expect(within(table).getByText('Apiome Recommended')).toBeInTheDocument();
    expect(within(table).getByText('Built-in')).toBeInTheDocument();
    expect(within(table).getByText('Default')).toBeInTheDocument();

    // Scoped per row: two guides really do enable every rule, and a bare `getByText` would
    // resolve to whichever came first and prove nothing about either.
    const builtinRow = within(table)
      .getAllByTestId('style-guide-row')
      .find((node) => node.dataset.guideName === 'Apiome Recommended') as HTMLElement;
    const builtinCells = builtinRow.closest('tr') as HTMLElement;
    expect(within(builtinCells).getByText('41 / 41')).toBeInTheDocument();
    // The shipped guide is never edited, so its Updated cell is an em dash.
    expect(within(builtinCells).getAllByText('—').length).toBeGreaterThan(0);

    const defaultRow = within(table)
      .getAllByTestId('style-guide-row')
      .find((node) => node.dataset.guideName === 'Acme REST') as HTMLElement;
    const defaultCells = defaultRow.closest('tr') as HTMLElement;
    expect(within(defaultCells).getByText('34 / 41')).toBeInTheDocument();
  });

  it('links each guide to its own page', async () => {
    await renderPage();
    await screen.findByText('Acme REST');

    expect(screen.getByRole('link', { name: 'Acme REST' })).toHaveAttribute(
      'href',
      '/ade/dashboard/style-guides/g-default'
    );
  });

  it('shows the tenant default and the pinned projects as chips', async () => {
    await renderPage();
    await screen.findByText('Acme REST');

    const table = screen.getByTestId('style-guides-table');
    expect(within(table).getByText('Tenant default')).toBeInTheDocument();
    expect(within(table).getByText('Payments API')).toBeInTheDocument();
    // A guide that governs nothing says so rather than showing an empty cell.
    expect(within(table).getAllByText('—').length).toBeGreaterThan(0);
  });

  it('keeps the built-in guide read-only, and keeps its duplicate path', async () => {
    await renderPage();
    await screen.findByText('Apiome Recommended');

    expect(screen.queryByLabelText('Edit Apiome Recommended')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Delete Apiome Recommended')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Duplicate Apiome Recommended')).toBeInTheDocument();
    expect(screen.getByTestId('style-guide-assign-g-builtin')).toBeInTheDocument();

    expect(screen.getByLabelText('Edit Acme REST')).toBeInTheDocument();
    expect(screen.getByLabelText('Delete Acme REST')).toBeInTheDocument();
  });

  it('says the built-in guide is read-only in the foot, where the rule is', async () => {
    await renderPage();
    await screen.findByText('Acme REST');
    expect(screen.getByTestId('style-guides-table')).toHaveTextContent(
      /read-only — duplicate it to customize/
    );
  });
});

// ---------------------------------------------------------------------------------------
// 3. The toolbar — the redesign's additions
// ---------------------------------------------------------------------------------------

describe('the toolbar', () => {
  it('counts each facet, and the counts partition the list', async () => {
    await renderPage();
    await screen.findByText('Acme REST');

    expect(chip('all')).toHaveTextContent('3');
    expect(chip('custom')).toHaveTextContent('2');
    expect(chip('assigned')).toHaveTextContent('1');
    expect(chip('unassigned')).toHaveTextContent('2');
  });

  it('narrows to a facet', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');

    await user.click(chip('unassigned'));

    const table = screen.getByTestId('style-guides-table');
    expect(within(table).getByText('Partner API strict')).toBeInTheDocument();
    expect(within(table).queryByText('Acme REST')).not.toBeInTheDocument();
  });

  it('searches the name, the description and the pinned projects', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');

    await user.type(screen.getByTestId('style-guides-search'), 'payments');

    const table = screen.getByTestId('style-guides-table');
    expect(within(table).getByText('Acme REST')).toBeInTheDocument();
    expect(within(table).queryByText('Partner API strict')).not.toBeInTheDocument();
  });

  it('offers a way back out of a search that matched nothing', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');

    await user.type(screen.getByTestId('style-guides-search'), 'zzzznothing');
    expect(screen.getByText('No style guides match these filters')).toBeInTheDocument();

    await user.click(screen.getByTestId('style-guides-clear-filters'));
    expect(await screen.findByText('Acme REST')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// 4. The dialogs
// ---------------------------------------------------------------------------------------

describe('the create dialog', () => {
  it('opens empty from New guide', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');

    await user.click(screen.getByTestId('style-guides-create'));

    const dialog = await screen.findByTestId('style-guide-create-dialog');
    expect(within(dialog).getByText('New style guide')).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/)).toHaveValue('');
    expect(screen.getByLabelText('Copy rules from')).toHaveValue('');
  });

  it('opens on the built-in guide from Start from Recommended', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');

    await user.click(screen.getByTestId('style-guides-start-recommended'));

    expect(await screen.findByLabelText(/^Name/)).toHaveValue('Apiome Recommended (copy)');
    expect(screen.getByLabelText('Copy rules from')).toHaveValue('g-builtin');
  });

  it('opens on the row’s own guide from Duplicate, and says so', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');

    await user.click(screen.getByLabelText('Duplicate Acme REST'));

    const dialog = await screen.findByTestId('style-guide-create-dialog');
    expect(within(dialog).getByText('Duplicate style guide')).toBeInTheDocument();
    expect(within(dialog).getByText(/Creates an editable copy of “Acme REST”/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/)).toHaveValue('Acme REST (copy)');
  });

  it('refuses a nameless guide without asking the server', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');

    await user.click(screen.getByTestId('style-guides-create'));
    await user.click(await screen.findByTestId('style-guide-create-submit'));

    expect(await screen.findByTestId('style-guide-create-error')).toHaveTextContent(
      'Give the guide a name.'
    );
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('reports a refused write inline and stays open', async () => {
    const user = userEvent.setup();
    mutationResponse = { ok: false, error: 'A guide with that name already exists' };
    await renderPage();
    await screen.findByText('Acme REST');

    await user.click(screen.getByTestId('style-guides-create'));
    await user.type(await screen.findByLabelText(/^Name/), 'Payments');
    await user.click(screen.getByTestId('style-guide-create-submit'));

    expect(await screen.findByTestId('style-guide-create-error')).toHaveTextContent(
      'A guide with that name already exists'
    );
    expect(screen.getByTestId('style-guide-create-dialog')).toBeInTheDocument();
  });
});

describe('the delete confirm', () => {
  it('names what the deletion costs', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');

    await user.click(screen.getByLabelText('Delete Acme REST'));

    const impact = await screen.findByTestId('style-guide-delete-impact');
    expect(impact).toHaveTextContent('is the tenant default');
    expect(impact).toHaveTextContent('is pinned to Payments API');
    expect(impact).toHaveTextContent('scored by Apiome Recommended');
  });

  it('says nothing extra about a guide that governs nothing', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Partner API strict');

    await user.click(screen.getByLabelText('Delete Partner API strict'));

    await screen.findByTestId('style-guide-delete-dialog');
    expect(screen.queryByTestId('style-guide-delete-impact')).not.toBeInTheDocument();
  });

  it('reports a refused delete inline rather than behind the dialog', async () => {
    const user = userEvent.setup();
    mutationResponse = { ok: false, error: 'Built-in guides cannot be deleted' };
    await renderPage();
    await screen.findByText('Acme REST');

    await user.click(screen.getByLabelText('Delete Acme REST'));
    await user.click(await screen.findByTestId('style-guide-delete-submit'));

    expect(await screen.findByTestId('style-guide-delete-error')).toHaveTextContent(
      'Built-in guides cannot be deleted'
    );
    expect(screen.getByTestId('style-guide-delete-dialog')).toBeInTheDocument();
  });
});

describe('the assign dialog', () => {
  it('shows the tenant default state rather than offering to set it again', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');

    await user.click(screen.getByTestId('style-guide-assign-g-default'));

    expect(await screen.findByTestId('style-guide-is-default')).toBeInTheDocument();
    expect(screen.queryByTestId('style-guide-make-default')).not.toBeInTheDocument();
  });

  it('offers only the projects this guide is not already pinned to', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');

    await user.click(screen.getByTestId('style-guide-assign-g-default'));

    const select = await screen.findByLabelText('Project to assign');
    expect(within(select).getByText('Inventory Events')).toBeInTheDocument();
    expect(within(select).queryByText('Payments API')).not.toBeInTheDocument();
  });

  it('lists the pinned projects with a way to unpin each', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Acme REST');

    await user.click(screen.getByTestId('style-guide-assign-g-default'));

    const list = await screen.findByTestId('style-guide-assignments');
    expect(within(list).getByText('Payments API')).toBeInTheDocument();
    expect(screen.getByLabelText('Unassign Payments API')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// 5. The states — the third and fourth acceptance criteria
// ---------------------------------------------------------------------------------------

describe('the states', () => {
  it('waits with a labelled skeleton rather than an unnamed spinner', async () => {
    render(<StyleGuidesClient />);
    expect(await screen.findByText('Loading style guides…')).toBeInTheDocument();
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
  });

  it('says the workspace has no guides only when the read succeeded', async () => {
    guidesResponse = { ok: true, rows: [] };
    await renderPage();

    expect(await screen.findByText('No style guides yet.')).toBeInTheDocument();
    // Both CTAs, as the mockup's empty state has them.
    expect(screen.getAllByText('New guide').length).toBeGreaterThan(0);
  });

  it('reports a refused read as a failure, never as an empty workspace', async () => {
    guidesResponse = { ok: false, rows: [], error: 'No tenant selected' };
    await renderPage();

    expect(await screen.findByText('No tenant selected')).toBeInTheDocument();
    expect(screen.queryByText('No style guides yet.')).not.toBeInTheDocument();
  });

  it('gives a member the read-only treatment, with the reason on it', async () => {
    isAdmin = false;
    await renderPage();
    await screen.findByText('Acme REST');

    const banner = screen.getByTestId('style-guides-readonly');
    expect(banner).toHaveTextContent('Read-only for members.');
    expect(banner).toHaveTextContent(/Only tenant administrators can create, assign or edit/);
    expect(banner).toHaveTextContent(/You can open any guide and browse its rules/);

    // The verbs whose writes the server would refuse are still absent…
    expect(screen.queryByTestId('style-guides-create')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Edit Acme REST')).not.toBeInTheDocument();
    expect(screen.queryByTestId('style-guide-assign-g-default')).not.toBeInTheDocument();
    // …and the list itself is still fully readable, which is the point of the treatment.
    expect(screen.getByText('Apiome Recommended')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Acme REST' })).toBeInTheDocument();
  });

  it('shows no read-only banner to an administrator', async () => {
    await renderPage();
    await screen.findByText('Acme REST');
    expect(screen.queryByTestId('style-guides-readonly')).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// The docs fixtures
// ---------------------------------------------------------------------------------------

/**
 * The documentation site's Style guides page (`apiome-docs/screens.json`, DOCS-1.8) is captured
 * from these dumps when the golden-path stack is not running. Written into
 * `e2e/fixtures/hive-a11y/` with
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/style-guides-hive-redesign.test.tsx -t "docs fixtures"`.
 *
 * The list is a believable workspace — the built-in guide, a tenant default pinned to one
 * project, a second guide pinned to two more, and one not yet assigned — and the two policy
 * tabs answer with saved, versioned policies (one blocking import floor, one active waiver), so
 * every section of the docs page has something real to point at.
 */
describe('the docs fixtures', () => {
  const DOCS_GUIDES: Row[] = [
    BUILTIN,
    row({
      id: 'g-acme',
      name: 'Acme REST',
      description: 'House rules for Acme’s public REST APIs.',
      isDefault: true,
      enabledRuleCount: 36,
      projectAssignments: [{ projectId: 'p-payments', projectName: 'Payments API' }],
      updatedAt: '2026-09-22T14:05:00Z',
    }),
    row({
      id: 'g-partner',
      name: 'Partner API strict',
      description: 'Acme REST with every naming and security rule raised to error.',
      enabledRuleCount: 41,
      projectAssignments: [
        { projectId: 'p-partners', projectName: 'Partner Gateway' },
        { projectId: 'p-billing', projectName: 'Billing API' },
      ],
      updatedAt: '2026-09-30T09:48:00Z',
    }),
    row({
      id: 'g-events',
      name: 'Event streams',
      description: 'AsyncAPI channel and message conventions for Kafka topics.',
      ruleCount: 18,
      enabledRuleCount: 15,
      updatedAt: '2026-08-11T17:30:00Z',
    }),
  ];

  const QUALITY_POLICY = {
    policyVersionId: 'qp-4',
    versionNumber: 4,
    contentFingerprint: '9f2c4e7a1b3d5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8',
    isDefault: false,
    import: { minGrade: 'C', minScore: 70, blockOnSeverity: 'error', enforcement: 'block' },
    export: { minGrade: 'B', minScore: null, blockOnSeverity: null, enforcement: 'advisory' },
    formatOverrides: { graphql: { import: { minGrade: 'D' } } },
    allowOverride: true,
    overrideRoles: ['owner', 'admin'],
    waiverTtlHours: 168,
    actorLabel: 'maria.chen@acme.dev',
    createdAt: '2026-09-29T15:12:00Z',
  };

  const QUALITY_VERSIONS = [
    QUALITY_POLICY,
    {
      ...QUALITY_POLICY,
      policyVersionId: 'qp-3',
      versionNumber: 3,
      contentFingerprint: '41d8e2b7c0a9f3e6d5c4b3a2918070f6e5d4c3b2a1908f7e6d5c4b3a29180706',
      actorLabel: 'maria.chen@acme.dev',
      createdAt: '2026-09-02T10:40:00Z',
    },
    {
      ...QUALITY_POLICY,
      policyVersionId: 'qp-2',
      versionNumber: 2,
      contentFingerprint: 'c7a1e93b5d2f8064a7b9c1d3e5f7092b4d6f8a0c2e4f6a8b0c2d4e6f8a0b2c4d',
      actorLabel: 'devon.ruiz@acme.dev',
      createdAt: '2026-07-18T08:25:00Z',
    },
  ];

  const WAIVERS = [
    {
      id: 'w-1',
      scope: 'import',
      subjectKey: '3b9f0c2d7e8a1b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4',
      subjectLabel: 'legacy-orders.yaml',
      formatKey: 'openapi',
      reportFingerprint: null,
      score: 64,
      grade: 'D',
      reason: 'Legacy orders contract imported as-is for the Q4 migration; cleanup tracked in PAY-412.',
      expiresAt: '2026-10-09T15:00:00Z',
      policyVersionId: 'qp-4',
      actorLabel: 'devon.ruiz@acme.dev',
      actorRole: 'admin',
      createdAt: '2026-10-02T15:00:00Z',
    },
  ];

  const VERIFICATION_POLICY = {
    policyVersionId: 'vp-2',
    versionNumber: 2,
    contentFingerprint: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    isDefault: false,
    requiredSuiteDigests: [
      'sha256:7d865e959b2466918c9863afca942d0fb89d7c9ac0c99bafc3749504ded97730',
      'sha256:2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae',
    ],
    maxEvidenceAgeSeconds: 86400,
    requiredTargetNetworkClass: 'private',
    purpose: 'both',
    breakingChangeAction: 'warn',
    enforcement: 'block',
    actorLabel: 'maria.chen@acme.dev',
    createdAt: '2026-09-24T11:03:00Z',
  };

  const VERIFICATION_VERSIONS = [
    VERIFICATION_POLICY,
    {
      ...VERIFICATION_POLICY,
      policyVersionId: 'vp-1',
      versionNumber: 1,
      enforcement: 'advisory',
      createdAt: '2026-08-30T16:45:00Z',
    },
  ];

  beforeEach(() => {
    guidesResponse = { ok: true, rows: DOCS_GUIDES };
    const base = global.fetch;
    const fn = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.includes('/api/projects')) {
        return jsonResponse({
          success: true,
          projects: [
            { id: 'p-payments', name: 'Payments API' },
            { id: 'p-partners', name: 'Partner Gateway' },
            { id: 'p-billing', name: 'Billing API' },
            { id: 'p-inventory', name: 'Inventory Events' },
            { id: 'p-identity', name: 'Identity Service' },
          ],
        });
      }
      if (url.startsWith('/api/quality-policy/versions')) {
        return jsonResponse({
          success: true,
          data: { versions: QUALITY_VERSIONS, count: QUALITY_VERSIONS.length },
        });
      }
      if (url.startsWith('/api/quality-policy/waivers')) {
        return jsonResponse({ success: true, data: { waivers: WAIVERS, count: WAIVERS.length } });
      }
      if (url.startsWith('/api/quality-policy')) {
        return jsonResponse({ success: true, data: QUALITY_POLICY });
      }
      if (url.startsWith('/api/verification-policy/versions')) {
        return jsonResponse({
          success: true,
          data: { versions: VERIFICATION_VERSIONS, count: VERIFICATION_VERSIONS.length },
        });
      }
      if (url.startsWith('/api/verification-policy')) {
        return jsonResponse({ success: true, data: VERIFICATION_POLICY });
      }
      return (base as typeof fetch)(input, init);
    });
    // @ts-expect-error - assigning a test double to the global
    global.fetch = fn;
  });

  /** The page root, which is what the docs screenshot mounts. */
  const page = () =>
    (document.querySelector('.page') ?? document.body.firstElementChild) as HTMLElement;

  it('renders the list, the create and assign dialogs, and both policy tabs', async () => {
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText('Event streams');
    writeA11yFixture('style-guides', liveMarkup(page()));

    await user.click(screen.getByTestId('style-guides-start-recommended'));
    const create = await screen.findByTestId('style-guide-create-dialog');
    expect(create).toHaveTextContent('Copy rules from');
    writeA11yFixture('style-guides-create-dialog', liveMarkup(create));
    await user.click(within(create).getByRole('button', { name: 'Cancel' }));
    await waitFor(() =>
      expect(screen.queryByTestId('style-guide-create-dialog')).not.toBeInTheDocument()
    );

    await user.click(screen.getByTestId('style-guide-assign-g-partner'));
    const assign = await screen.findByTestId('style-guide-assign-dialog');
    expect(within(assign).getByText('Partner Gateway')).toBeInTheDocument();
    writeA11yFixture('style-guides-assign-dialog', liveMarkup(assign));
    await user.click(within(assign).getByRole('button', { name: 'Done' }));
    await waitFor(() =>
      expect(screen.queryByTestId('style-guide-assign-dialog')).not.toBeInTheDocument()
    );

    await user.click(screen.getByTestId('style-guides-tab-quality'));
    expect(await screen.findByTestId('quality-policy-waivers')).toHaveTextContent(
      'legacy-orders.yaml'
    );
    writeA11yFixture('style-guides-policies', liveMarkup(page()));

    await user.click(screen.getByTestId('style-guides-tab-verification'));
    expect(await screen.findByTestId('verification-policy-versions')).toHaveTextContent(
      'v2 · block · warn'
    );
    writeA11yFixture('style-guides-verification-policy', liveMarkup(page()));
  });

  it('renders the read-only treatment a member sees', async () => {
    isAdmin = false;
    await renderPage();
    await screen.findByText('Event streams');
    expect(screen.getByTestId('style-guides-readonly')).toBeInTheDocument();
    writeA11yFixture('style-guides-readonly', liveMarkup(page()));
  });
});
