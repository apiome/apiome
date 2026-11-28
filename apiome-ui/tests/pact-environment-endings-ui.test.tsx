/**
 * Ending a deployment or a release from the Environments board — PFX-8.13 (#7310).
 *
 * * **Record an undeployment** from an environment's column menu: the services running there, the
 *   instance, the command block, the POST it sends, the status line; a refusal stays in the dialog;
 * * **End support** from a release on the board: the confirmation, the command, the POST;
 * * **Record a release**: unticking a release that stays supported ends its support after recording;
 * * a role without `pacts:edit` gets neither action; a read-only role sees no header or cell actions.
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

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const EDITOR = { is_admin: false, permissions: ['pacts:view', 'pacts:create', 'pacts:edit', 'pacts:delete'] };
const RECORDER = { is_admin: false, permissions: ['pacts:view', 'pacts:create'] };
const VIEWER = { is_admin: false, permissions: ['pacts:view'] };

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
    '/api/pact/pacticipants': ok({
      pacticipants: [{ id: 'p-2', slug: 'mobile-app', name: 'Mobile App', labels: [] }],
      next_cursor: null,
    }),
    '/api/pact/pacticipants/mobile-app/versions': ok({
      versions: [{ id: 'v-2', pacticipant_id: 'p-2', number: '5.3.0', seq: 4, branches: ['main'], tags: [] }],
      next_cursor: null,
    }),
  };
}

beforeEach(() => {
  calls = [];
  routes = baseRoutes();
  installFetch();
});

/** Radix `DropdownMenu.Trigger` opens on `pointerdown`, which jsdom does not synthesise. */
function openMenu(trigger: HTMLElement) {
  fireEvent.keyDown(trigger, { key: 'Enter' });
}

async function renderPage() {
  const result = render(<EnvironmentsClient />);
  await screen.findByTestId('penv-board');
  return result;
}

const posts = () => calls.filter((call) => call.method === 'POST');

describe('Record an undeployment', () => {
  it('ends the chosen service and instance from the column menu', async () => {
    routes['POST /api/pact/environments/production/undeployments'] = () => ({
      status: 200,
      body: { undeployed: [{ uuid: 'd2', version: '1.4.2', applicationInstance: 'us-east' }] },
    });
    await renderPage();
    await screen.findByTestId('penv-action-deploy');
    openMenu(screen.getByTestId('penv-menu-production'));
    fireEvent.click(await screen.findByTestId('penv-undeploy-production'));
    const dialog = await screen.findByTestId('penv-undeploy-dialog');
    const service = within(dialog).getByTestId('penv-undeploy-service');
    expect(within(service).getAllByRole('option').map((option) => option.textContent)).toEqual([
      'Billing Service',
      'Ledger API',
      'Reporting Job',
    ]);
    fireEvent.change(service, { target: { value: 'reporting-job' } });
    const instance = within(dialog).getByTestId('penv-undeploy-instance');
    expect(instance).toHaveValue('eu-west');
    fireEvent.change(instance, { target: { value: 'us-east' } });
    expect(within(dialog).getByTestId('penv-undeploy-command')).toHaveTextContent(
      'apiome pact record-undeployment \\ --pacticipant reporting-job \\ --environment production \\ --application-instance us-east',
    );
    expect(await axe(dialog, AXE_OPTIONS)).toHaveNoViolations();
    fireEvent.click(within(dialog).getByTestId('penv-undeploy-record'));
    expect(await screen.findByTestId('penv-notice')).toHaveTextContent(
      'Reporting Job 1.4.2 is recorded as no longer deployed to Production (us-east).',
    );
    expect(posts()).toEqual([
      expect.objectContaining({
        url: '/api/pact/environments/production/undeployments',
        body: { pacticipant: 'reporting-job', applicationInstance: 'us-east' },
      }),
    ]);
  });

  it('keeps a refusal in the dialog, and is not offered where nothing runs', async () => {
    routes['POST /api/pact/environments/production/undeployments'] = () => ({
      status: 404,
      body: { success: false, error: 'Billing Service is not currently deployed to production environment. Cannot record undeployment.' },
    });
    await renderPage();
    openMenu(screen.getByTestId('penv-menu-qa'));
    await screen.findByTestId('penv-edit-qa');
    expect(screen.queryByTestId('penv-undeploy-qa')).toBeNull();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
    openMenu(screen.getByTestId('penv-menu-production'));
    fireEvent.click(await screen.findByTestId('penv-undeploy-production'));
    const dialog = await screen.findByTestId('penv-undeploy-dialog');
    fireEvent.click(within(dialog).getByTestId('penv-undeploy-record'));
    expect(await within(dialog).findByTestId('penv-undeploy-problem')).toHaveTextContent('is not currently deployed');
    expect(screen.queryByTestId('penv-notice')).toBeNull();
  });
});

describe('End support', () => {
  it('ends a release from the Released to users column', async () => {
    routes['POST /api/pact/environments/production/support-ended'] = () => ({ status: 200, body: { ended: 1 } });
    await renderPage();
    fireEvent.click(await screen.findByTestId('penv-end-mobile-app-5.2.0'));
    const dialog = await screen.findByTestId('penv-end-dialog');
    expect(dialog).toHaveTextContent('End support for Mobile App 5.2.0?');
    expect(within(dialog).getByTestId('penv-end-command')).toHaveTextContent(
      'apiome pact record-support-ended \\ --pacticipant mobile-app \\ --version 5.2.0 \\ --environment production',
    );
    expect(await axe(dialog, AXE_OPTIONS)).toHaveNoViolations();
    fireEvent.click(within(dialog).getByTestId('penv-end-confirm'));
    expect(await screen.findByTestId('penv-notice')).toHaveTextContent('Support for Mobile App 5.2.0 in production has ended.');
    expect(posts()[0].body).toEqual({ pacticipant: 'mobile-app', version: '5.2.0' });
  });

  it('ends the support of a release unticked in Record a release', async () => {
    routes['POST /api/pact/environments/production/releases'] = () => ({ status: 201, body: { uuid: 'r-new' } });
    routes['POST /api/pact/environments/production/support-ended'] = () => ({ status: 200, body: { ended: 1 } });
    await renderPage();
    fireEvent.click(await screen.findByTestId('penv-action-release'));
    const dialog = await screen.findByTestId('penv-release-dialog');
    await waitFor(() => expect(within(dialog).getByTestId('penv-release-service')).not.toBeDisabled());
    fireEvent.change(within(dialog).getByTestId('penv-release-service'), { target: { value: 'mobile-app' } });
    fireEvent.change(within(dialog).getByLabelText('Version'), { target: { value: '5.3.0' } });
    fireEvent.change(within(dialog).getByLabelText('Environment'), { target: { value: 'production' } });
    const keep = await within(dialog).findByTestId('penv-release-keep-5.2.0');
    expect(keep).toBeChecked();
    fireEvent.click(keep);
    expect(within(dialog).getByTestId('penv-release-end-command-5.2.0')).toHaveTextContent('apiome pact record-support-ended');
    fireEvent.click(within(dialog).getByTestId('penv-release-record'));
    expect(await screen.findByTestId('penv-notice')).toHaveTextContent('Support for 5.2.0 has ended.');
    expect(posts().map((call) => call.url)).toEqual([
      '/api/pact/environments/production/releases',
      '/api/pact/environments/production/support-ended',
    ]);
  });
});

describe('roles', () => {
  it('gives a role without pacts:edit no way to end anything', async () => {
    routes = baseRoutes(RECORDER);
    await renderPage();
    await screen.findByTestId('penv-action-deploy');
    expect(screen.queryByTestId('penv-end-mobile-app-5.2.0')).toBeNull();
    openMenu(screen.getByTestId('penv-menu-production'));
    await screen.findByTestId('penv-deploy-here-production');
    expect(screen.queryByTestId('penv-undeploy-production')).toBeNull();
  });

  it('hides the header and cell actions from a read-only role', async () => {
    routes = baseRoutes(VIEWER);
    await renderPage();
    await waitFor(() => expect(calls.some((call) => call.url === '/api/access/permissions/me')).toBe(true));
    expect(screen.queryByTestId('penv-action-deploy')).toBeNull();
    expect(screen.queryByTestId('penv-menu-production')).toBeNull();
    expect(screen.queryByTestId('penv-first-orders-ui')).toBeNull();
    expect(screen.getByTestId('penv-row-orders-ui')).toHaveTextContent('Never deployed');
    const next = screen.getByTestId('penv-next-ledger-api-production');
    expect(within(next).queryByRole('button')).toBeNull();
    expect(within(next).getByRole('link')).toHaveAttribute('href', expect.stringContaining('/simulate?pacticipant=ledger-api'));
  });
});
