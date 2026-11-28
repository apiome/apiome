/**
 * The Environments page's writes — PFX-8.12 (#7309).
 *
 * * Roles: an editor sees **Record a deployment** (primary), **New environment** and **Record a
 *   release**, and each environment's menu; a read-only role sees none of them.
 * * **New environment**: the name follows the display name until typed; problems per field; the
 *   body sent; a taken name (409) under **Name**; the command block; axe passes.
 * * **Edit environment**: read from REST's list; a `PUT` that keeps the other contacts.
 * * **Delete environment**: blocked while versions run there (no delete button); deleted when
 *   nothing does.
 * * **Record a deployment**: can-i-deploy is asked once the form is complete; a "yes" records; a
 *   "no" shows the reasons and records only after **Record it anyway**, sending `recordAnyway`;
 *   the proxy's refusal is shown; **Record a deployment here** starts in that environment; axe.
 * * **Record a release**: lists what stays supported; the body sent.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-environment-new` and
 * `pact-record-deployment`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn(), replace: jest.fn() }) }));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-environments.json';
import EnvironmentsClient from '../src/app/components/ade/pactEnvironments/EnvironmentsClient';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const EDITOR = { is_admin: false, permissions: ['pacts:view', 'pacts:create', 'pacts:edit', 'pacts:delete'] };
const VIEWER = { is_admin: false, permissions: ['pacts:view'] };
const PRODUCTION_UUID = fixture.topology.environments[0].uuid;
const QA_UUID = fixture.topology.environments[2].uuid;
const BROKER_LIST = {
  _embedded: {
    environments: [
      {
        uuid: PRODUCTION_UUID,
        name: 'production',
        displayName: 'Production',
        production: true,
        contractRequired: true,
        contacts: [{ name: 'Platform team', details: { emailAddress: 'platform@acme.dev' } }, { name: 'On call' }],
      },
      { uuid: QA_UUID, name: 'qa', displayName: 'QA', production: false, contractRequired: false, contacts: [] },
    ],
  },
};
const NO = {
  summary: { deployable: false, reason: 'One or more verifications failed', success: 0, failed: 1, unknown: 0 },
  notices: [{ type: 'error', text: 'Orders UI 3.3.2 in Production needs currency on POST /invoices; 2.7.0 does not return it.' }],
  matrix: [],
};
const YES = { summary: { deployable: true, reason: 'All verified', success: 1, failed: 0, unknown: 0 }, notices: [], matrix: [] };

type Call = { url: string; method: string; body: unknown };
type Answer = (call: Call) => { status: number; body: unknown };
let routes: Record<string, Answer>;
let calls: Call[];

const ok = (body: unknown): Answer => () => ({ status: 200, body });

/** REST through the proxies: `METHOD url` or `url` keys, the longest prefix answering. */
function installFetch() {
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const call: Call = { url: String(input), method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const key = Object.keys(routes)
      .sort((a, b) => b.length - a.length)
      .find((candidate) => `${call.method} ${call.url}`.startsWith(candidate) || (call.method === 'GET' && call.url.startsWith(candidate)));
    const { status, body } = key ? routes[key](call) : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

function baseRoutes(permissions = EDITOR): Record<string, Answer> {
  return {
    '/api/access/permissions/me': ok({ success: true, data: permissions }),
    '/api/pact/environment-topology': ok(fixture.topology),
    '/api/pact/environment-board': ok(fixture.board),
    '/api/pact/environments': ok(BROKER_LIST),
    '/api/pact/pacticipants': ok({
      pacticipants: [
        { id: 'p-1', slug: 'billing-service', name: 'Billing Service', labels: [] },
        { id: 'p-2', slug: 'mobile-app', name: 'Mobile App', labels: [] },
      ],
      next_cursor: null,
    }),
    '/api/pact/pacticipants/billing-service/versions': ok({
      versions: [{ id: 'v-1', pacticipant_id: 'p-1', number: '2.7.0+9f31c20', seq: 2, branches: ['main'], tags: [] }],
      next_cursor: null,
    }),
    '/api/pact/pacticipants/mobile-app/versions': ok({
      versions: [{ id: 'v-2', pacticipant_id: 'p-2', number: '5.3.0', seq: 4, branches: ['main'], tags: [] }],
      next_cursor: null,
    }),
    '/api/pact/can-i-deploy': ok(NO),
  };
}

beforeEach(() => {
  calls = [];
  routes = baseRoutes();
  installFetch();
});

const bodyMarkup = () => liveMarkup(document.body).replace(/^<body[^>]*>|<\/body>$/g, '');

/** Radix `DropdownMenu.Trigger` opens on `pointerdown`, which jsdom does not synthesise. */
function openMenu(trigger: HTMLElement) {
  fireEvent.keyDown(trigger, { key: 'Enter' });
}

async function renderPage() {
  render(<EnvironmentsClient />);
  await screen.findByTestId('penv-board');
}

describe('roles', () => {
  it('gives an editor the three header actions and the environment menu', async () => {
    await renderPage();
    expect(await screen.findByTestId('penv-action-deploy')).toHaveTextContent('Record a deployment');
    expect(screen.getByTestId('penv-action-new')).toHaveTextContent('New environment');
    expect(screen.getByTestId('penv-action-release')).toHaveTextContent('Record a release');
    openMenu(screen.getByTestId('penv-menu-production'));
    expect(await screen.findByTestId('penv-edit-production')).toHaveTextContent('Edit environment');
    expect(screen.getByTestId('penv-deploy-here-production')).toHaveTextContent('Record a deployment here');
    expect(screen.getByTestId('penv-delete-production')).toHaveTextContent('Delete environment');
  });

  it('shows a read-only role none of them', async () => {
    routes = baseRoutes(VIEWER);
    await renderPage();
    await waitFor(() => expect(calls.some((c) => c.url === '/api/access/permissions/me')).toBe(true));
    expect(screen.queryByTestId('penv-action-deploy')).toBeNull();
    expect(screen.queryByTestId('penv-action-new')).toBeNull();
    expect(screen.queryByTestId('penv-action-release')).toBeNull();
    expect(screen.queryByTestId('penv-menu-production')).toBeNull();
  });

  it('offers New environment, as the primary action, to an empty workspace', async () => {
    routes['/api/pact/environment-topology'] = ok({ environments: [], truncated: false });
    routes['/api/pact/environment-board'] = ok({ environments: [], rows: [], truncated: false, checks: 0, notChecked: 0 });
    render(<EnvironmentsClient />);
    expect(await screen.findByTestId('penv-empty')).toHaveTextContent('Add production and staging so can-i-deploy has somewhere to look');
    expect(await screen.findByTestId('penv-action-new')).toBeInTheDocument();
    expect(screen.queryByTestId('penv-action-deploy')).toBeNull();
  });
});

describe('New environment', () => {
  it('fills the name from the display name, checks the fields, and creates it', async () => {
    routes['POST /api/pact/environments'] = () => ({ status: 201, body: { uuid: 'e-new', name: 'production-eu' } });
    await renderPage();
    fireEvent.click(await screen.findByTestId('penv-action-new'));
    const dialog = await screen.findByTestId('penv-env-dialog');
    fireEvent.click(within(dialog).getByTestId('penv-env-save'));
    expect(await within(dialog).findByText('Give the environment a name.')).toBeInTheDocument();
    fireEvent.change(within(dialog).getByTestId('penv-env-display'), { target: { value: 'Production EU' } });
    expect(within(dialog).getByTestId('penv-env-name')).toHaveValue('production-eu');
    fireEvent.click(within(dialog).getByRole('switch', { name: 'Production' }));
    fireEvent.click(within(dialog).getByRole('switch', { name: 'Contracts required' }));
    fireEvent.change(within(dialog).getByTestId('penv-env-contact'), { target: { value: 'Platform team' } });
    fireEvent.change(within(dialog).getByTestId('penv-env-email'), { target: { value: 'platform@acme.dev' } });
    const command = within(dialog).getByTestId('penv-env-command');
    expect(command).toHaveTextContent('apiome pact create-environment');
    expect(command).toHaveTextContent('--contract-required');
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-environment-new', bodyMarkup());
    fireEvent.click(within(dialog).getByTestId('penv-env-save'));
    expect(await screen.findByTestId('penv-notice')).toHaveTextContent('Production EU is created.');
    const post = calls.find((c) => c.method === 'POST');
    expect(post).toEqual({
      url: '/api/pact/environments',
      method: 'POST',
      body: {
        name: 'production-eu',
        displayName: 'Production EU',
        production: true,
        contractRequired: true,
        contacts: [{ name: 'Platform team', details: { emailAddress: 'platform@acme.dev' } }],
      },
    });
  });

  it('refuses a name another environment has, and puts a 409 under Name', async () => {
    routes['POST /api/pact/environments'] = () => ({ status: 409, body: { success: false, error: 'Another environment is called eu.' } });
    await renderPage();
    fireEvent.click(await screen.findByTestId('penv-action-new'));
    const dialog = await screen.findByTestId('penv-env-dialog');
    fireEvent.change(within(dialog).getByTestId('penv-env-name'), { target: { value: 'staging' } });
    fireEvent.click(within(dialog).getByTestId('penv-env-save'));
    expect(await within(dialog).findByText('Another environment is already called staging.')).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    fireEvent.change(within(dialog).getByTestId('penv-env-name'), { target: { value: 'eu' } });
    fireEvent.click(within(dialog).getByTestId('penv-env-save'));
    expect(await within(dialog).findByText('Another environment is called eu.')).toBeInTheDocument();
  });
});

describe('Edit and delete', () => {
  it('edits from REST’s list and keeps the other contacts', async () => {
    routes['PUT /api/pact/environments/production'] = () => ({ status: 200, body: { uuid: PRODUCTION_UUID } });
    await renderPage();
    openMenu(await screen.findByTestId('penv-menu-production'));
    fireEvent.click(await screen.findByTestId('penv-edit-production'));
    const dialog = await screen.findByTestId('penv-env-dialog');
    expect(within(dialog).getByText('Edit Production')).toBeInTheDocument();
    expect(within(dialog).getByTestId('penv-env-contact')).toHaveValue('Platform team');
    expect(within(dialog).getByTestId('penv-env-kept')).toHaveTextContent('1 other contact is kept as it is.');
    expect(within(dialog).getByTestId('penv-env-command')).toHaveTextContent('No apiome pact command changes an environment yet');
    fireEvent.change(within(dialog).getByTestId('penv-env-display'), { target: { value: 'Production (EU)' } });
    expect(within(dialog).getByTestId('penv-env-name')).toHaveValue('production');
    fireEvent.click(within(dialog).getByTestId('penv-env-save'));
    expect(await screen.findByTestId('penv-notice')).toHaveTextContent('Production (EU) is saved.');
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
      name: 'production',
      displayName: 'Production (EU)',
      production: true,
      contractRequired: true,
      contacts: [{ name: 'Platform team', details: { emailAddress: 'platform@acme.dev' } }, { name: 'On call' }],
    });
  });

  it('blocks deleting an environment with versions running, and deletes an empty one', async () => {
    routes['DELETE /api/pact/environments/qa'] = () => ({ status: 200, body: { deleted: true } });
    await renderPage();
    openMenu(await screen.findByTestId('penv-menu-production'));
    fireEvent.click(await screen.findByTestId('penv-delete-production'));
    const blocked = await screen.findByTestId('penv-delete-dialog');
    expect(within(blocked).getByTestId('penv-delete-blocked')).toHaveTextContent('Production still has 5 versions running.');
    expect(within(blocked).queryByTestId('penv-delete-confirm')).toBeNull();
    fireEvent.click(within(blocked).getByTestId('penv-delete-cancel'));
    await waitFor(() => expect(screen.queryByTestId('penv-delete-dialog')).toBeNull());
    openMenu(screen.getByTestId('penv-menu-qa'));
    fireEvent.click(await screen.findByTestId('penv-delete-qa'));
    const dialog = await screen.findByTestId('penv-delete-dialog');
    fireEvent.click(within(dialog).getByTestId('penv-delete-confirm'));
    expect(await screen.findByTestId('penv-notice')).toHaveTextContent('QA is deleted.');
    expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.url)).toEqual(['/api/pact/environments/qa']);
  });

  it('says why a delete was refused', async () => {
    routes['DELETE /api/pact/environments/qa'] = () => ({ status: 409, body: { success: false, error: 'QA still has 1 version running.' } });
    await renderPage();
    openMenu(await screen.findByTestId('penv-menu-qa'));
    fireEvent.click(await screen.findByTestId('penv-delete-qa'));
    fireEvent.click(within(await screen.findByTestId('penv-delete-dialog')).getByTestId('penv-delete-confirm'));
    expect(await screen.findByTestId('penv-delete-problem')).toHaveTextContent('QA still has 1 version running.');
  });
});

describe('Record a deployment', () => {
  async function openDeploy() {
    await renderPage();
    fireEvent.click(await screen.findByTestId('penv-action-deploy'));
    const dialog = await screen.findByTestId('penv-deploy-dialog');
    await waitFor(() => expect(within(dialog).getByTestId('penv-deploy-service')).not.toBeDisabled());
    return dialog;
  }

  async function fill(dialog: HTMLElement) {
    fireEvent.change(within(dialog).getByTestId('penv-deploy-service'), { target: { value: 'billing-service' } });
    fireEvent.change(within(dialog).getByTestId('penv-deploy-version'), { target: { value: '2.7.0+9f31c20' } });
    fireEvent.change(within(dialog).getByTestId('penv-deploy-environment'), { target: { value: 'production' } });
  }

  it('asks can-i-deploy, shows the reasons for a no, and records only with the tick', async () => {
    routes['POST /api/pact/environments/production/deployments'] = () => ({ status: 201, body: { uuid: 'd-1', verdict: 'no' } });
    const dialog = await openDeploy();
    expect(within(dialog).getByTestId('penv-deploy-waiting')).toHaveTextContent('Choose the service.');
    expect(within(dialog).getByTestId('penv-deploy-record')).toBeDisabled();
    await fill(dialog);
    expect(await within(dialog).findByText('can-i-deploy says no')).toBeInTheDocument();
    expect(within(dialog).getByTestId('penv-deploy-reasons')).toHaveTextContent('needs currency on POST /invoices');
    expect(within(dialog).getByTestId('penv-deploy-replaces')).toHaveTextContent('Replaces 2.3.1.');
    expect(calls.find((c) => c.url.startsWith('/api/pact/can-i-deploy'))?.url).toBe(
      '/api/pact/can-i-deploy?pacticipant=billing-service&version=2.7.0%2B9f31c20&toEnvironment=production',
    );
    expect(within(dialog).getByTestId('penv-deploy-record')).toBeDisabled();
    fireEvent.click(within(dialog).getByTestId('penv-deploy-anyway'));
    expect(within(dialog).getByTestId('penv-deploy-record')).not.toBeDisabled();
    const command = within(dialog).getByTestId('penv-deploy-command');
    expect(command).toHaveTextContent('apiome pact record-deployment');
    expect(command).toHaveTextContent('Record it anyway');
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-record-deployment', bodyMarkup());
    fireEvent.click(within(dialog).getByTestId('penv-deploy-record'));
    expect(await screen.findByTestId('penv-notice')).toHaveTextContent('over a “no” from can-i-deploy. The override is in the audit trail.');
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      pacticipant: 'billing-service',
      version: '2.7.0+9f31c20',
      recordAnyway: true,
    });
  });

  it('records a yes without the tick, and drops the tick when the question changes', async () => {
    routes['/api/pact/can-i-deploy'] = ok(YES);
    routes['POST /api/pact/environments/production/deployments'] = () => ({ status: 201, body: { uuid: 'd-1', verdict: 'yes' } });
    const dialog = await openDeploy();
    await fill(dialog);
    expect(await within(dialog).findByText('can-i-deploy says yes')).toBeInTheDocument();
    expect(within(dialog).queryByTestId('penv-deploy-anyway')).toBeNull();
    fireEvent.change(within(dialog).getByTestId('penv-deploy-instance'), { target: { value: 'eu-west' } });
    await within(dialog).findByText('can-i-deploy says yes');
    fireEvent.click(within(dialog).getByTestId('penv-deploy-record'));
    expect(await screen.findByTestId('penv-notice')).toHaveTextContent('Billing Service 2.7.0+9f31c20 is recorded as deployed to Production.');
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      pacticipant: 'billing-service',
      version: '2.7.0+9f31c20',
      applicationInstance: 'eu-west',
    });
  });

  it('shows the proxy’s refusal, and a can-i-deploy that could not be asked', async () => {
    routes['POST /api/pact/environments/production/deployments'] = () => ({
      status: 409,
      body: { success: false, error: 'can-i-deploy says no.', reasons: ['A new failure.'] },
    });
    const dialog = await openDeploy();
    await fill(dialog);
    fireEvent.click(await within(dialog).findByTestId('penv-deploy-anyway'));
    fireEvent.click(within(dialog).getByTestId('penv-deploy-record'));
    expect(await within(dialog).findByTestId('penv-deploy-problem')).toHaveTextContent('can-i-deploy says no. A new failure.');
    routes['/api/pact/can-i-deploy'] = () => ({ status: 404, body: { success: false, error: 'No version 9.9.9' } });
    fireEvent.change(within(dialog).getByTestId('penv-deploy-version'), { target: { value: '9.9.9' } });
    expect(await within(dialog).findByText('No version 9.9.9')).toBeInTheDocument();
    expect(within(dialog).getByTestId('penv-deploy-record')).toBeDisabled();
  });

  it('starts in the environment the menu names', async () => {
    await renderPage();
    openMenu(await screen.findByTestId('penv-menu-staging'));
    fireEvent.click(await screen.findByTestId('penv-deploy-here-staging'));
    const dialog = await screen.findByTestId('penv-deploy-dialog');
    expect(within(dialog).getByTestId('penv-deploy-environment')).toHaveValue('staging');
  });
});

describe('Record a release', () => {
  it('lists what stays supported and records the release', async () => {
    routes['POST /api/pact/environments/production/releases'] = () => ({ status: 201, body: { uuid: 'r-1' } });
    await renderPage();
    fireEvent.click(await screen.findByTestId('penv-action-release'));
    const dialog = await screen.findByTestId('penv-release-dialog');
    await waitFor(() => expect(within(dialog).getByTestId('penv-release-service')).not.toBeDisabled());
    fireEvent.click(within(dialog).getByTestId('penv-release-record'));
    expect(await within(dialog).findByTestId('penv-release-form-problem')).toHaveTextContent('Choose the service.');
    fireEvent.change(within(dialog).getByTestId('penv-release-service'), { target: { value: 'mobile-app' } });
    fireEvent.change(within(dialog).getByTestId('penv-release-version'), { target: { value: '5.3.0' } });
    fireEvent.change(within(dialog).getByTestId('penv-release-environment'), { target: { value: 'production' } });
    expect(within(dialog).getByTestId('penv-release-supported')).toHaveTextContent('5.2.0');
    expect(within(dialog).getByTestId('penv-release-command')).toHaveTextContent('apiome pact record-release');
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
    fireEvent.click(within(dialog).getByTestId('penv-release-record'));
    expect(await screen.findByTestId('penv-notice')).toHaveTextContent('5.3.0 is recorded as released to Production. 5.2.0 stay supported.');
    expect(calls.find((c) => c.method === 'POST')).toEqual({
      url: '/api/pact/environments/production/releases',
      method: 'POST',
      body: { pacticipant: 'mobile-app', version: '5.3.0' },
    });
  });
});
