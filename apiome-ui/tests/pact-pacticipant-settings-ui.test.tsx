/**
 * Create, edit and delete a pacticipant — PFX-8.10 (#7307).
 *
 * * **Settings**: an editor sees the fields with the stored values; **Save changes** sends only
 *   what changed (one PATCH, then one request per label) and says what happened; a taken name is
 *   shown under **Name**; a bad field is named before anything is sent; **Discard** resets; a
 *   read-only role sees the values without inputs and no Danger zone; axe passes.
 * * **Delete**: the dialog spells out what goes; **Delete** stays off until the handle is typed;
 *   the reason is sent; after it the dialog offers **Restore**; a pacticipant with a version
 *   deployed cannot be deleted and the dialog says which.
 * * **New pacticipant**: the header action (pacts:create only) opens the dialog; a project fills an
 *   empty name; **Create pacticipant** posts and opens the new page; a taken name is shown under
 *   **Name**; an owner that cannot be set is reported, not dropped.
 * * **Deleted view**: the list's **Show → Deleted** lists what can be restored, and **Restore** posts
 *   by id.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-pacticipant-settings`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: jest.fn(), push: mockPush }),
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-pacticipants.json';
import PacticipantSettingsClient from '../src/app/components/ade/pactPacticipants/PacticipantSettingsClient';
import PacticipantsListClient from '../src/app/components/ade/pactPacticipants/PacticipantsListClient';
import type { Pacticipant } from '../lib/pact-pacticipants';
import type { DeletionImpact } from '../lib/pact-pacticipant-settings';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const BILLING: Pacticipant = {
  ...(fixture.pacticipants[0] as Pacticipant),
  display_name: 'Billing (EU)',
  aliases: ['Billing'],
  project_id: 'p-billing',
};
const base = '/api/pact/pacticipants/billing-service';
const EDITOR = {
  is_admin: false,
  permissions: ['pacts:view', 'pacts:create', 'pacts:edit', 'pacts:delete'],
};
const VIEWER = { is_admin: false, permissions: ['pacts:view'] };
const IMPACT: DeletionImpact = {
  slug: 'billing-service',
  name: 'Billing Service',
  versions: 214,
  pacts: 31,
  verification_results: 90,
  providers: ['Ledger API', 'Orders API'],
  providers_total: 2,
  consumers: [],
  consumers_total: 0,
  in_use: [],
  blocked: false,
  grace_days: 30,
};
const PROJECTS = {
  success: true,
  projects: [
    { id: 'p-billing', name: 'Billing API', slug: 'billing-api' },
    { id: 'p-orders', name: 'Orders API', slug: 'orders-api' },
  ],
};

type Call = { url: string; method: string; body: unknown };
type Answer = (call: Call) => { status: number; body: unknown };
let routes: Record<string, Answer>;
let calls: Call[];

/** Answer by `METHOD url` first, then by url. */
function installFetch() {
  calls = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    const call = { url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const route = routes[`${method} ${url}`] ?? routes[url];
    const { status, body } = route
      ? route(call)
      : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

const ok =
  (body: unknown): Answer =>
  () => ({ status: 200, body });
const writes = () => calls.filter((call) => call.method !== 'GET');

function baseRoutes(permissions = EDITOR): Record<string, Answer> {
  return {
    '/api/access/permissions/me': ok({ success: true, data: permissions }),
    [base]: ok(BILLING),
    '/api/projects': ok(PROJECTS),
    [`/api/owners/pacticipant/${BILLING.id}`]: ok({
      kind: 'pacticipant',
      entity_id: BILLING.id,
      owner: null,
      suggestions: [],
    }),
    '/api/teams': ok({ teams: [{ id: 't-1', slug: 'billing-team', name: 'Billing team' }] }),
    [`${base}/deletion-impact`]: ok(IMPACT),
    // The Badges panel (PFX-8.11): the pacts it can badge, and the badge REST serves.
    [`${base}/pacts`]: ok({
      matrix: [
        {
          consumer: { name: 'Billing Service', version: { number: '1' }, _links: { self: { href: '/pacticipants/billing-service' } } },
          provider: { name: 'Ledger API', version: null, _links: { self: { href: '/pacticipants/ledger-api' } } },
          pact: { createdAt: '2026-11-27T10:00:00Z' },
          verificationResult: null,
        },
      ],
    }),
    '/api/pact/badges?project=billing-api&pacticipant=billing-service': ok({
      tenant: 'acme',
      status: 'verified',
      svg: '<svg xmlns="http://www.w3.org/2000/svg" width="150" height="20" role="img" aria-label="pact: billing-service: verified"><title>pact: billing-service: verified</title><rect width="104" height="20" fill="#555"/><rect x="104" width="46" height="20" fill="#2e7d32"/></svg>',
    }),
  };
}

beforeEach(() => {
  mockPush.mockReset();
  routes = baseRoutes();
  installFetch();
});

// --- Settings ---------------------------------------------------------------------------------

describe('PacticipantSettingsClient', () => {
  it('shows the stored values in the fields, the handle and old names, and passes axe', async () => {
    const { container } = render(<PacticipantSettingsClient slug="billing-service" />);
    const name = await screen.findByTestId('ppx-settings-name');
    expect(name).toHaveValue('Billing Service');
    expect(screen.getByTestId('ppx-settings-display-name')).toHaveValue('Billing (EU)');
    expect(screen.getByTestId('ppx-settings-main-branch')).toHaveValue('main');
    expect(screen.getByTestId('ppx-settings-repository')).toHaveValue(
      'https://github.com/acme/billing-service',
    );
    await waitFor(() =>
      expect(screen.getByTestId('ppx-settings-project')).toHaveValue('p-billing'),
    );
    expect(
      within(screen.getByTestId('ppx-settings-labels')).getByText('team-billing'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('ppx-settings-facts')).toHaveTextContent('Handlebilling-service');
    expect(screen.getByTestId('ppx-settings-facts')).toHaveTextContent('Previous namesBilling');
    expect(screen.getByTestId('ppx-tab-settings')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTestId('ppx-tab-overview')).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/billing-service',
    );
    expect(screen.getByTestId('ppx-settings-save')).toBeDisabled();
    expect(screen.getByTestId('ppx-danger-zone')).toHaveTextContent('Delete Billing Service…');
    expect(screen.getByTestId('ppx-settings-command')).toHaveTextContent(
      'apiome pact create-or-update-pacticipant',
    );
    await screen.findByTestId('entity-owner-description');
    expect(await screen.findByTestId('ppx-badges-image')).toHaveAttribute('alt', 'Pact badge: verified');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-pacticipant-settings', liveMarkup(container));
  });

  it('saves only what changed: the rename, then each label', async () => {
    routes[`PATCH ${base}`] = (call) => ({
      status: 200,
      body: {
        ...BILLING,
        ...(call.body as object),
        name: 'Billing Core',
        aliases: ['Billing', 'Billing Service'],
      },
    });
    routes[`PUT ${base}/labels/payments`] = ok({});
    routes[`DELETE ${base}/labels/tier-1`] = ok({});
    render(<PacticipantSettingsClient slug="billing-service" />);
    fireEvent.change(await screen.findByTestId('ppx-settings-name'), {
      target: { value: 'Billing Core' },
    });
    fireEvent.click(
      within(screen.getByTestId('ppx-settings-labels')).getByRole('button', {
        name: 'Remove the label tier-1',
      }),
    );
    fireEvent.change(screen.getByTestId('ppx-settings-label-input'), {
      target: { value: 'payments' },
    });
    fireEvent.keyDown(screen.getByTestId('ppx-settings-label-input'), { key: 'Enter' });
    expect(screen.getByTestId('ppx-settings-command')).toHaveTextContent(
      'The new name is not carried by the command',
    );
    fireEvent.click(screen.getByTestId('ppx-settings-save'));
    await waitFor(() =>
      expect(screen.getByTestId('ppx-settings-outcome')).toHaveTextContent('Saved.'),
    );
    expect(screen.getByTestId('ppx-settings-outcome')).toHaveTextContent(
      'the old name Billing Service still resolves',
    );
    expect(writes()).toEqual([
      { url: base, method: 'PATCH', body: { name: 'Billing Core' } },
      { url: `${base}/labels/payments`, method: 'PUT', body: undefined },
      { url: `${base}/labels/tier-1`, method: 'DELETE', body: undefined },
    ]);
  });

  it('puts a taken name under Name, and sends nothing for a bad field', async () => {
    routes[`PATCH ${base}`] = () => ({
      status: 409,
      body: { success: false, error: 'A pacticipant named Ledger API already exists.' },
    });
    render(<PacticipantSettingsClient slug="billing-service" />);
    await screen.findByTestId('ppx-settings-name');
    fireEvent.change(screen.getByTestId('ppx-settings-repository'), {
      target: { value: 'git@github.com:a/b.git' },
    });
    fireEvent.click(screen.getByTestId('ppx-settings-save'));
    expect(
      await screen.findByText('Use an http(s) URL, such as https://github.com/acme/orders-ui.'),
    ).toBeInTheDocument();
    expect(writes()).toEqual([]);

    fireEvent.change(screen.getByTestId('ppx-settings-repository'), {
      target: { value: 'https://github.com/acme/billing' },
    });
    fireEvent.change(screen.getByTestId('ppx-settings-name'), { target: { value: 'Ledger API' } });
    fireEvent.click(screen.getByTestId('ppx-settings-save'));
    expect(
      await screen.findByText('A pacticipant named Ledger API already exists.'),
    ).toBeInTheDocument();
    // FormField re-keys its control when an error appears, so read the field again.
    expect(screen.getByTestId('ppx-settings-name')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.queryByTestId('ppx-settings-outcome')).not.toBeInTheDocument();
  });

  it('reports a label that could not be saved instead of dropping it', async () => {
    routes[`PUT ${base}/labels/payments`] = () => ({
      status: 403,
      body: { success: false, error: 'Permission denied: pacts:edit' },
    });
    render(<PacticipantSettingsClient slug="billing-service" />);
    fireEvent.change(await screen.findByTestId('ppx-settings-label-input'), {
      target: { value: 'payments' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    fireEvent.click(screen.getByTestId('ppx-settings-save'));
    await waitFor(() =>
      expect(screen.getByTestId('ppx-settings-outcome')).toHaveTextContent(
        'Saved, except: Permission denied: pacts:edit.',
      ),
    );
  });

  it('Discard puts the stored values back', async () => {
    render(<PacticipantSettingsClient slug="billing-service" />);
    const branch = await screen.findByTestId('ppx-settings-main-branch');
    fireEvent.change(branch, { target: { value: 'trunk' } });
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(branch).toHaveValue('main');
    expect(screen.getByTestId('ppx-settings-save')).toBeDisabled();
  });

  it('shows a read-only role the values without inputs and no Danger zone', async () => {
    routes = baseRoutes(VIEWER);
    const { container } = render(<PacticipantSettingsClient slug="billing-service" />);
    const values = await screen.findByTestId('ppx-settings-values');
    expect(values).toHaveTextContent('Display nameBilling (EU)');
    await waitFor(() => expect(values).toHaveTextContent('Linked projectBilling API'));
    expect(
      within(screen.getByTestId('ppx-general')).queryByRole('textbox'),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId('ppx-settings-save')).not.toBeInTheDocument();
    expect(screen.queryByTestId('ppx-danger-zone')).not.toBeInTheDocument();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});

// --- Delete -----------------------------------------------------------------------------------

describe('the Delete dialog', () => {
  it('spells out what goes, needs the handle typed, sends the reason, then offers Restore', async () => {
    routes[`DELETE ${base}?reason=retired`] = ok({});
    routes[`POST ${base}/restore`] = ok(BILLING);
    render(<PacticipantSettingsClient slug="billing-service" />);
    fireEvent.click(await screen.findByTestId('ppx-delete-open'));
    const impact = await screen.findByTestId('ppx-delete-impact');
    expect(impact).toHaveTextContent(
      'Its 214 versions, 31 pacts and 90 verification results go with it.',
    );
    expect(impact).toHaveTextContent('2 providers lose a consumer (Ledger API and Orders API)');
    expect(impact).toHaveTextContent('You can restore it for 30 days.');
    const confirm = screen.getByTestId('ppx-delete-confirm');
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByTestId('ppx-delete-typed'), {
      target: { value: 'Billing Service' },
    });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByTestId('ppx-delete-typed'), {
      target: { value: 'billing-service' },
    });
    fireEvent.change(screen.getByTestId('ppx-delete-reason'), { target: { value: 'retired' } });
    expect(screen.getByTestId('ppx-delete-command')).toHaveTextContent(
      'apiome pact delete-pacticipant',
    );
    expect(await axe(screen.getByTestId('ppx-delete-dialog'), AXE_OPTIONS)).toHaveNoViolations();
    fireEvent.click(confirm);
    expect(await screen.findByText('Billing Service is deleted')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('ppx-delete-restore'));
    expect(await screen.findByText('Billing Service is back')).toBeInTheDocument();
    expect(writes().map((call) => `${call.method} ${call.url}`)).toEqual([
      `DELETE ${base}?reason=retired`,
      `POST ${base}/restore`,
    ]);
  });

  it('cannot delete a pacticipant with a version deployed, and says which', async () => {
    routes[`${base}/deletion-impact`] = ok({ ...IMPACT, in_use: ['3.3.2'], blocked: true });
    render(<PacticipantSettingsClient slug="billing-service" />);
    fireEvent.click(await screen.findByTestId('ppx-delete-open'));
    expect(await screen.findByTestId('ppx-delete-blocked')).toHaveTextContent(
      '3.3.2 of Billing Service is deployed or released. Record the undeployment first.',
    );
    expect(screen.queryByTestId('ppx-delete-confirm')).not.toBeInTheDocument();
    expect(screen.queryByTestId('ppx-delete-typed')).not.toBeInTheDocument();
  });

  it('shows REST’s refusal and reads the impact again', async () => {
    routes[`DELETE ${base}`] = () => ({
      status: 409,
      body: { success: false, error: 'version(s) 3.3.2 are currently deployed' },
    });
    render(<PacticipantSettingsClient slug="billing-service" />);
    fireEvent.click(await screen.findByTestId('ppx-delete-open'));
    fireEvent.change(await screen.findByTestId('ppx-delete-typed'), {
      target: { value: 'billing-service' },
    });
    fireEvent.click(screen.getByTestId('ppx-delete-confirm'));
    expect(await screen.findByTestId('ppx-delete-problem')).toHaveTextContent(
      'version(s) 3.3.2 are currently deployed',
    );
    await waitFor(() =>
      expect(calls.filter((call) => call.url === `${base}/deletion-impact`)).toHaveLength(2),
    );
  });
});

// --- New pacticipant and the Deleted view -------------------------------------------------------

describe('the Pacticipants list', () => {
  const list = (rows: Pacticipant[]) =>
    ok({ pacticipants: rows, count: rows.length, has_more: false, next_cursor: null });

  beforeEach(() => {
    routes['/api/pact/pacticipants'] = list(fixture.pacticipants as Pacticipant[]);
    routes['/api/pact/labels'] = ok({ labels: [], count: 0, has_more: false });
  });

  it('creates a pacticipant from a project, with an owner, and opens it', async () => {
    routes['POST /api/pact/pacticipants'] = (call) => ({
      status: 201,
      body: {
        ...BILLING,
        id: 'new-id',
        slug: 'orders-api',
        name: (call.body as { name: string }).name,
      },
    });
    routes['/api/owners/assign'] = ok({ count: 1 });
    render(<PacticipantsListClient />);
    fireEvent.click(await screen.findByTestId('ppx-new-open'));
    const dialog = await screen.findByTestId('ppx-new-dialog');
    await waitFor(() =>
      expect(within(dialog).getByRole('option', { name: 'Orders API' })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId('ppx-new-project'), { target: { value: 'p-orders' } });
    expect(screen.getByTestId('ppx-new-name')).toHaveValue('Orders API');
    expect(dialog).toHaveTextContent('Its handle will be orders-api');
    fireEvent.change(await screen.findByTestId('ppx-new-owner'), {
      target: { value: 'billing-team' },
    });
    expect(await axe(dialog, AXE_OPTIONS)).toHaveNoViolations();
    fireEvent.click(screen.getByTestId('ppx-new-create'));
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith('/ade/dashboard/pacts/pacticipants/orders-api'),
    );
    expect(writes()).toEqual([
      {
        url: '/api/pact/pacticipants',
        method: 'POST',
        body: { name: 'Orders API', main_branch: 'main', project: 'p-orders' },
      },
      {
        url: '/api/owners/assign',
        method: 'POST',
        body: { team: 'billing-team', entities: [{ kind: 'pacticipant', id: 'new-id' }] },
      },
    ]);
  });

  it('puts a taken name under Name, and reports an owner that could not be set', async () => {
    let taken = true;
    routes['POST /api/pact/pacticipants'] = () =>
      taken
        ? {
            status: 409,
            body: {
              success: false,
              error: "a pacticipant 'billing-service' already exists in this tenant",
            },
          }
        : {
            status: 201,
            body: { ...BILLING, id: 'new-id', slug: 'billing-eu', name: 'Billing EU' },
          };
    routes['/api/owners/assign'] = () => ({
      status: 403,
      body: { success: false, error: 'Permission denied' },
    });
    render(<PacticipantsListClient />);
    fireEvent.click(await screen.findByTestId('ppx-new-open'));
    fireEvent.change(await screen.findByTestId('ppx-new-name'), {
      target: { value: 'Billing Service' },
    });
    fireEvent.click(screen.getByTestId('ppx-new-create'));
    expect(
      await screen.findByText("a pacticipant 'billing-service' already exists in this tenant"),
    ).toBeInTheDocument();
    taken = false;
    fireEvent.change(screen.getByTestId('ppx-new-name'), { target: { value: 'Billing EU' } });
    fireEvent.change(await screen.findByTestId('ppx-new-owner'), {
      target: { value: 'billing-team' },
    });
    fireEvent.click(screen.getByTestId('ppx-new-create'));
    expect(await screen.findByTestId('ppx-list-notice')).toHaveTextContent(
      'Billing EU was created, but its owner could not be set: Permission denied. Set it on the Settings tab.',
    );
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('hides New pacticipant from a read-only role', async () => {
    routes['/api/access/permissions/me'] = ok({ success: true, data: VIEWER });
    render(<PacticipantsListClient />);
    await screen.findByTestId('ppx-pacticipants-table');
    await act(async () => undefined);
    expect(screen.queryByTestId('ppx-new-open')).not.toBeInTheDocument();
  });

  it('lists the deleted pacticipants and restores one by id', async () => {
    const deleted = {
      ...BILLING,
      deleted_at: '2026-11-20T10:00:00Z',
      deleted_by_label: 'dev@example.com',
      purge_after: '2026-12-20T10:00:00Z',
      delete_reason: 'retired',
    };
    routes['/api/pact/pacticipants?state=deleted'] = list([deleted]);
    routes[`POST /api/pact/pacticipants/${BILLING.id}/restore`] = ok(BILLING);
    render(<PacticipantsListClient />);
    await screen.findByTestId('ppx-pacticipants-table');
    fireEvent.change(screen.getByTestId('ppx-show-filter'), { target: { value: 'deleted' } });
    const row = await screen.findByTestId('ppx-deleted-billing-service');
    expect(row).toHaveTextContent('2026-11-20 10:00 UTC by dev@example.com');
    expect(row).toHaveTextContent('retired');
    expect(row).toHaveTextContent('2026-12-20 10:00 UTC');
    fireEvent.click(within(row).getByRole('button', { name: 'Restore Billing Service' }));
    expect(await screen.findByTestId('ppx-list-notice')).toHaveTextContent(
      'Billing Service is restored',
    );
    expect(writes()).toEqual([
      { url: `/api/pact/pacticipants/${BILLING.id}/restore`, method: 'POST', body: undefined },
    ]);
  });
});
