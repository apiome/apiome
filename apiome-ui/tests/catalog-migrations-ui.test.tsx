/**
 * Backstage and Compass import — CDG-5.5 (#5983).
 *
 * * **Rules**: the proxy forwards only the report, upload, decision and component paths with their
 *   own fields; counts, accept labels, unmapped grouping and file checks.
 * * **Import to catalog → Compass export**: the tile, the upload, then the report on the Import step.
 * * **Import report page**: teams and components with their actions, the unmapped fields, accepting
 *   (name and slug overrides, "register on its own" for a match) and dismissing; a viewer without
 *   `imports:create` sees no actions; axe passes.
 * * **Import reports list** and the **component page** (links, owner, facts).
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `import-wizard-compass` and
 * `backstage-import-report`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/ade/dashboard/catalog/imports',
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { user_id: 'u-1', current_tenant_id: 't-1' } } }),
}));

import ImportReportClient from '../src/app/ade/dashboard/catalog/imports/[id]/ImportReportClient';
import ImportReportsClient from '../src/app/ade/dashboard/catalog/imports/ImportReportsClient';
import ComponentDetailClient from '../src/app/ade/dashboard/catalog/components/[slug]/ComponentDetailClient';
import { CatalogImportDialog } from '../src/app/components/ade/dashboard/catalog/CatalogImportDialog';
import {
  acceptLabel,
  catalogMigrationProxyBody,
  catalogMigrationProxyPath,
  compassFileProblem,
  groupUnmapped,
  migrationCountsLine,
  suggestionEntityHref,
  type CatalogComponent,
  type MigrationRun,
  type MigrationSuggestion,
} from '../lib/catalog-migrations';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const RUN_ID = '11111111-1111-4111-8111-111111111111';
const TEAM_ID = '22222222-2222-4222-8222-222222222222';
const SVC_ID = '33333333-3333-4333-8333-333333333333';
const LEDGER_ID = '44444444-4444-4444-8444-444444444444';

const TEAM: MigrationSuggestion = {
  id: TEAM_ID,
  kind: 'team',
  source: 'backstage',
  externalRef: 'group:default/payments-team',
  name: 'Payments',
  slug: 'payments-team',
  status: 'suggested',
  payload: { contactEmail: 'payments@acme.example', chatUrl: 'https://chat.acme.example/payments' },
  match: null,
  entity: null,
  decidedAt: null,
};

const SERVICE: MigrationSuggestion = {
  id: SVC_ID,
  kind: 'component',
  source: 'backstage',
  externalRef: 'component:default/payments-svc',
  name: 'Payments service',
  slug: 'payments-svc',
  status: 'suggested',
  payload: {
    category: 'component',
    componentType: 'service',
    ownerRef: 'group:default/payments-team',
    links: [{ type: 'chat', url: 'https://chat.acme.example/payments' }],
    references: [{ reference: 'api:default/ledger', edgeKind: 'consumes', slug: 'ledger' }],
  },
  match: null,
  entity: null,
  decidedAt: null,
};

const LEDGER: MigrationSuggestion = {
  ...SERVICE,
  id: LEDGER_ID,
  externalRef: 'component:default/ledger',
  name: 'Ledger',
  slug: 'ledger',
  payload: { category: 'system', ownerRef: 'group:default/payments-team' },
  match: { kind: 'project', id: 'p-ledger', name: 'Ledger API', slug: 'ledger' },
};

const BACKSTAGE_RUN: MigrationRun = {
  id: RUN_ID,
  source: 'backstage',
  label: 'acme/payments · main',
  repositoryId: 'r-1',
  branch: 'main',
  counts: { files: 2, entities: 5, components: 2, teams: 1, teamsMatched: 0, apisImported: 1, matched: 1 },
  unmapped: [
    { entity: 'component:default/payments-svc', field: 'metadata.annotations.github.com/project-slug', reason: 'no Apiome field' },
    { entity: 'component:default/payments-svc', field: 'metadata.tags', reason: 'no Apiome field' },
    { entity: 'user:default/jdoe', field: 'kind', reason: "kind 'User' is not imported" },
  ],
  unmappedTotal: 3,
  pending: 3,
  suggestions: [TEAM, SERVICE, LEDGER],
  createdAt: '2026-10-19T09:00:00Z',
  updatedAt: '2026-10-19T09:00:00Z',
};

const COMPASS_RUN: MigrationRun = {
  ...BACKSTAGE_RUN,
  source: 'compass',
  label: 'compass-export.json',
  repositoryId: null,
  branch: null,
  counts: { files: 1, entities: 2, components: 2, teams: 1, teamsMatched: 0 },
  unmapped: [
    { entity: 'compass:Checkout', field: 'labels', reason: 'no Apiome field' },
    { entity: 'compass:Checkout', field: 'relationships[1]', reason: 'relationship CHILD_OF is not imported' },
  ],
  unmappedTotal: 2,
  suggestions: [
    { ...TEAM, source: 'compass', externalRef: 'ari:cloud:identity::team/aaaa1111', name: 'Checkout team', slug: 'checkout-team',
      payload: { description: 'Owns checkout' } },
    { ...SERVICE, source: 'compass', externalRef: 'ari:cloud:compass:1:component/checkout', name: 'Checkout', slug: 'checkout',
      payload: { category: 'component', componentType: 'SERVICE', links: [{ type: 'chat', url: 'https://c' }, { type: 'on_call', url: 'https://o' }] } },
    { ...LEDGER, source: 'compass', externalRef: 'ari:cloud:compass:1:component/ledger',
      payload: { category: 'component', ownerRef: 'ari:cloud:identity::team/aaaa1111' } },
  ],
};

const COMPONENT: CatalogComponent = {
  id: SVC_ID,
  slug: 'payments-svc',
  name: 'Payments service',
  description: 'Takes money',
  category: 'component',
  componentType: 'service',
  lifecycle: 'production',
  parentRef: 'billing',
  links: [
    { type: 'chat', url: 'https://chat.acme.example/payments', title: '#payments' },
    { type: 'on_call', url: 'https://oncall.acme.example/payments' },
  ],
  source: 'backstage',
  externalRef: 'component:default/payments-svc',
  owner: { team: { id: 't-pay', slug: 'payments-team', name: 'Payments' }, status: 'suggested', source: 'backstage' },
  createdAt: null,
  updatedAt: null,
};

const res = (body: unknown, status = 200) =>
  ({ ok: status >= 200 && status < 300, status, json: async () => body, headers: { get: () => null } }) as unknown as Response;

let calls: Array<{ url: string; method: string; body: unknown }> = [];
let permissions: string[] = ['imports:create'];
let report: MigrationRun = BACKSTAGE_RUN;

// Backstage and Compass import is released (RC7); its Teams suggestions wait for teams and ownership
// (lib/feature-release.ts). These suites test those too, so re-open teams.
const PREVIEW_FEATURES = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
beforeAll(() => {
  process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'teams,dependency-graph';
});
/** Run `fn` as the released build renders it (no preview override), for a docs fixture. */
async function asReleased<T>(fn: () => Promise<T>): Promise<T> {
  const preview = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  try {
    return await fn();
  } finally {
    if (preview === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = preview;
  }
}

afterAll(() => {
  if (PREVIEW_FEATURES === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = PREVIEW_FEATURES;
});

beforeEach(() => {
  calls = [];
  permissions = ['imports:create'];
  report = BACKSTAGE_RUN;
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? 'GET').toUpperCase();
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url === '/api/access/permissions/me') return res({ success: true, data: { is_admin: false, permissions } });
    if (url === '/api/catalog-migrations') return res({ runs: [BACKSTAGE_RUN, { ...COMPASS_RUN, id: 'r-2', pending: 0 }] });
    if (url === '/api/catalog-migrations/compass' && method === 'POST') return res(COMPASS_RUN, 201);
    if (url.startsWith('/api/catalog-migrations/suggestions/')) {
      const accepted = url.endsWith('/accept');
      return res({ ...TEAM, status: accepted ? 'accepted' : 'dismissed' });
    }
    if (url.startsWith('/api/catalog-migrations/components/')) return res(COMPONENT);
    if (url.startsWith('/api/catalog-migrations/')) return res(report);
    if (url === '/api/teams') return res({ teams: [{ id: 't-pay', slug: 'payments-team', name: 'Payments' }] });
    if (url.startsWith('/api/catalog/entities/')) return res({ kind: 'component', id: SVC_ID, facts: [], score: null });
    if (url.includes('/api/import/sources')) return res({ success: true, sources: [] });
    return res({}, 404);
  }) as unknown as typeof fetch;
});

describe('the rules', () => {
  it('forwards only the report, upload, decision and component paths', () => {
    expect(catalogMigrationProxyPath([], 'GET')).toBe('catalog-migrations');
    expect(catalogMigrationProxyPath(['compass'], 'POST')).toBe('catalog-migrations/compass');
    expect(catalogMigrationProxyPath([RUN_ID], 'GET')).toBe(`catalog-migrations/${RUN_ID}`);
    expect(catalogMigrationProxyPath(['suggestions', TEAM_ID, 'accept'], 'POST')).toBe(
      `catalog-migration-suggestions/${TEAM_ID}/accept`,
    );
    expect(catalogMigrationProxyPath(['components', 'payments-svc'], 'GET')).toBe('catalog-components/payments-svc');
    expect(catalogMigrationProxyPath([], 'POST')).toBeNull();
    expect(catalogMigrationProxyPath(['compass'], 'GET')).toBeNull();
    expect(catalogMigrationProxyPath(['not-a-uuid'], 'GET')).toBeNull();
    expect(catalogMigrationProxyPath(['suggestions', TEAM_ID, 'delete'], 'POST')).toBeNull();
    expect(catalogMigrationProxyPath(['components', '../etc'], 'GET')).toBeNull();
  });

  it('forwards only each write’s own fields', () => {
    expect(catalogMigrationProxyBody('catalog-migrations/compass', { filename: 'c.json', content: '{}', evil: 1 })).toEqual({
      filename: 'c.json',
      content: '{}',
    });
    expect(
      catalogMigrationProxyBody(`catalog-migration-suggestions/${TEAM_ID}/accept`, { name: ' A ', slug: '', asComponent: 'yes' }),
    ).toEqual({ name: 'A' });
    expect(catalogMigrationProxyBody(`catalog-migration-suggestions/${TEAM_ID}/dismiss`, { name: 'x' })).toEqual({});
  });

  it('summarises, labels and groups', () => {
    expect(migrationCountsLine(BACKSTAGE_RUN)).toBe('5 entities · 2 components · 1 team · 1 API imported · 3 unmapped fields');
    expect(acceptLabel(TEAM)).toBe('Create team');
    expect(acceptLabel({ ...TEAM, payload: { existingTeam: true } })).toBe('Use team');
    expect(acceptLabel(SERVICE)).toBe('Register component');
    expect(acceptLabel(LEDGER)).toBe('Apply to Ledger API');
    expect(groupUnmapped(BACKSTAGE_RUN.unmapped).map(([entity, fields]) => [entity, fields.length])).toEqual([
      ['component:default/payments-svc', 2],
      ['user:default/jdoe', 1],
    ]);
    expect(suggestionEntityHref({ entity: { kind: 'component', id: SVC_ID, slug: 'payments-svc' } })).toBe(
      '/ade/dashboard/catalog/components/payments-svc',
    );
    expect(suggestionEntityHref({ entity: { kind: 'team', id: 't', slug: 'payments-team' } })).toBe('/ade/dashboard/teams/payments-team');
    expect(compassFileProblem({ name: 'export.yaml', size: 10 })).toMatch(/JSON/);
    expect(compassFileProblem({ name: 'export.json', size: 6 * 1024 * 1024 })).toMatch(/5 MB/);
    expect(compassFileProblem({ name: 'export.json', size: 10 })).toBeNull();
  });
});

describe('the import report page', () => {
  /** Render the report; `actions` is how many accept buttons it shows (2 without the Teams table). */
  async function renderReport(actions = 3) {
    const view = render(<ImportReportClient id={RUN_ID} />);
    await screen.findByTestId('migration-report');
    await waitFor(() => expect(screen.getAllByRole('button', { name: /Create team|Register component|Apply to/ }).length).toBe(actions));
    return view;
  }

  it('lists teams, components and every unmapped field', async () => {
    await renderReport();
    expect(screen.getByTestId('migration-counts')).toHaveTextContent('5 entities · 2 components · 1 team');
    const teams = within(screen.getByTestId('migration-teams'));
    expect(teams.getByText('Payments')).toBeInTheDocument();
    expect(teams.getByText('payments@acme.example')).toBeInTheDocument();
    const components = within(screen.getByTestId('migration-components'));
    expect(components.getByText('Component · service · Owner group:default/payments-team · 1 link · 1 dependency')).toBeInTheDocument();
    expect(components.getByText('Matches Ledger API')).toBeInTheDocument();
    const unmapped = within(screen.getByTestId('migration-unmapped'));
    expect(unmapped.getByText('metadata.annotations.github.com/project-slug')).toBeInTheDocument();
    expect(unmapped.getByText("kind 'User' is not imported")).toBeInTheDocument();
  });

  it('accepts a team with the imported name and slug, or overrides them', async () => {
    await renderReport();
    fireEvent.click(screen.getByRole('button', { name: 'Create team' }));
    const dialog = await screen.findByTestId('migration-accept-dialog');
    fireEvent.change(within(dialog).getByLabelText('Slug'), { target: { value: 'payments' } });
    fireEvent.click(within(dialog).getByTestId('migration-accept-submit'));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith(`/${TEAM_ID}/accept`))).toBe(true));
    const accept = calls.find((c) => c.url.endsWith(`/${TEAM_ID}/accept`))!;
    expect(accept.method).toBe('POST');
    expect(accept.body).toEqual({ name: 'Payments', slug: 'payments', asComponent: false });
  });

  it('applies a matched component to its match, or registers it on its own', async () => {
    await renderReport();
    fireEvent.click(screen.getByRole('button', { name: 'Apply to Ledger API' }));
    const dialog = await screen.findByTestId('migration-accept-dialog');
    expect(within(dialog).queryByLabelText('Name')).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('checkbox', { name: /component of its own/ }));
    expect(within(dialog).getByLabelText('Name')).toHaveValue('Ledger');
    expect(within(dialog).getByRole('heading', { name: 'Register component' })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByTestId('migration-accept-submit'));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith(`/${LEDGER_ID}/accept`))).toBe(true));
    expect(calls.find((c) => c.url.endsWith(`/${LEDGER_ID}/accept`))!.body).toEqual({
      name: 'Ledger', slug: 'ledger', asComponent: true,
    });
    await waitFor(() => expect(screen.queryByTestId('migration-accept-dialog')).toBeNull());
  });

  it('dismisses a suggestion', async () => {
    await renderReport();
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss Payments service' }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith(`/${SVC_ID}/dismiss`) && c.method === 'POST')).toBe(true));
  });

  it('shows no actions to a viewer who cannot import', async () => {
    permissions = ['imports:view'];
    render(<ImportReportClient id={RUN_ID} />);
    await screen.findByTestId('migration-report');
    await waitFor(() => expect(calls.some((c) => c.url === '/api/access/permissions/me')).toBe(true));
    expect(screen.queryByRole('button', { name: 'Create team' })).not.toBeInTheDocument();
  });

  it('leaves the Teams suggestions out while teams are held back, and dumps the docs fixture', async () => {
    await asReleased(async () => {
      const { container } = await renderReport(2);
      expect(screen.queryByTestId('migration-teams')).not.toBeInTheDocument();
      expect(screen.getByTestId('migration-unmapped')).toBeInTheDocument();
      expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
      writeA11yFixture('backstage-import-report', liveMarkup((document.querySelector('.page') ?? container.firstElementChild)!));
    });
  });
});

describe('Import to catalog → Compass export', () => {
  it('uploads the export and shows its report on the Import step', async () => {
    report = COMPASS_RUN;
    const onSuccess = jest.fn();
    render(<CatalogImportDialog open onClose={jest.fn()} onSuccess={onSuccess} />);
    fireEvent.click(await screen.findByTestId('catalog-import-source-compass'));
    const file = new File([JSON.stringify({ components: [] })], 'compass-export.json', { type: 'application/json' });
    fireEvent.change(screen.getByTestId('compass-intake-file'), { target: { files: [file] } });
    fireEvent.click(screen.getByTestId('compass-intake-import'));
    await screen.findByTestId('migration-report');
    const upload = calls.find((c) => c.url === '/api/catalog-migrations/compass')!;
    expect(upload.body).toEqual({ filename: 'compass-export.json', content: '{"components":[]}' });
    expect(onSuccess).toHaveBeenCalled();
    expect(within(screen.getByTestId('migration-unmapped')).getByText('relationship CHILD_OF is not imported')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByRole('button', { name: /Create team|Register component|Apply to/ }).length).toBe(3));
  });

  it('dumps the docs fixture as the released build shows it', async () => {
    await asReleased(async () => {
      report = COMPASS_RUN;
      render(<CatalogImportDialog open onClose={jest.fn()} onSuccess={jest.fn()} />);
      fireEvent.click(await screen.findByTestId('catalog-import-source-compass'));
      const file = new File([JSON.stringify({ components: [] })], 'compass-export.json', { type: 'application/json' });
      fireEvent.change(screen.getByTestId('compass-intake-file'), { target: { files: [file] } });
      fireEvent.click(screen.getByTestId('compass-intake-import'));
      await screen.findByTestId('migration-report');
      expect(screen.queryByTestId('migration-teams')).not.toBeInTheDocument();
      await waitFor(() => expect(screen.getAllByRole('button', { name: /Register component|Apply to/ }).length).toBeGreaterThan(0));
      writeA11yFixture('import-wizard-compass', liveMarkup(document.querySelector('[role="dialog"]')!));
    });
  });

  it('refuses a file that is not JSON before uploading it', async () => {
    render(<CatalogImportDialog open onClose={jest.fn()} />);
    fireEvent.click(await screen.findByTestId('catalog-import-source-compass'));
    fireEvent.change(screen.getByTestId('compass-intake-file'), {
      target: { files: [new File(['a: b'], 'catalog-info.yaml')] },
    });
    expect(screen.getByText('Choose the JSON file Compass exported.')).toBeInTheDocument();
    expect(screen.getByTestId('compass-intake-import')).toBeDisabled();
    expect(calls.some((c) => c.url === '/api/catalog-migrations/compass')).toBe(false);
  });
});

describe('the import reports list', () => {
  it('links every report and shows what is waiting', async () => {
    render(<ImportReportsClient />);
    const table = await screen.findByTestId('import-reports');
    expect(within(table).getByRole('link', { name: 'acme/payments · main' })).toHaveAttribute(
      'href',
      `/ade/dashboard/catalog/imports/${RUN_ID}`,
    );
    expect(within(table).getByText('Compass')).toBeInTheDocument();
  });
});

describe('the component page', () => {
  it('leaves out the owner and the dependency graph while their features are held back', async () => {
    await asReleased(async () => {
      render(<ComponentDetailClient slug="payments-svc" />);
      await screen.findByTestId('component-detail');
      expect(screen.queryByTestId('entity-owner')).not.toBeInTheDocument();
      expect(screen.queryByRole('link', { name: 'Open the dependency graph' })).not.toBeInTheDocument();
    });
  });

  it('shows the imported fields, links, owner and facts', async () => {
    const { container } = render(<ComponentDetailClient slug="payments-svc" />);
    await screen.findByTestId('component-detail');
    expect(screen.getByText('production')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /#payments/ })).toHaveAttribute('href', 'https://chat.acme.example/payments');
    expect(within(screen.getByTestId('entity-owner')).getByText('Payments')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open the dependency graph' })).toHaveAttribute(
      'href',
      `/ade/dashboard/graph?entity=${encodeURIComponent(`component:${SVC_ID}`)}`,
    );
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});
