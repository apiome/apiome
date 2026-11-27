/**
 * The **Webhooks** pages — PFX-5.6 (#6950).
 *
 * Webhooks page:
 * * every webhook with its scope, events, target, state and newest delivery, and the workspace's
 *   recent deliveries; axe passes;
 * * the **Status** filter and **Load more** page the deliveries;
 * * **New webhook** checks the form, tests it unsaved, creates it and opens it; a refusal shows
 *   REST's message;
 * * an empty workspace shows the CLI command; a refused read offers **Try again**.
 *
 * Webhook page:
 * * the overview, the request (secrets redacted) and the webhook's delivery log; axe passes;
 * * **Test** shows the outcome; **Disable** puts the webhook back with every secret kept;
 *   **Edit** saves the form; **Delete** asks first, then returns to the list.
 *
 * Delivery page:
 * * the overview and each attempt's log (failed ones open), **Copy**; axe passes;
 * * **Redeliver** queues a new delivery and links it; a refusal shows REST's reason; an
 *   unfinished delivery cannot be redelivered.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-webhooks`, `pact-webhook-detail`
 * and `pact-webhook-delivery`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const push = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: jest.fn() }) }));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-webhooks.json';
import WebhooksClient from '../src/app/components/ade/pactWebhooks/WebhooksClient';
import WebhookDetailClient from '../src/app/components/ade/pactWebhooks/WebhookDetailClient';
import DeliveryDetailClient from '../src/app/components/ade/pactWebhooks/DeliveryDetailClient';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const BASE = '/api/pact/webhooks';
const [HTTP] = fixture.webhooks;
const DELIVERY = fixture.detail.id;
const REDACTED = '**********';

type Answer = { status: number; body: unknown };
let answers: Record<string, () => Answer>;
let calls: Array<{ url: string; method: string; body?: unknown }>;

/** REST through the proxies: the longest route key the URL starts with (and the method) answers. */
function installFetch() {
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const key = Object.keys(answers)
      .sort((a, b) => b.length - a.length)
      .find((candidate) => {
        const [verb, prefix] = candidate.includes(' ') ? candidate.split(' ') : ['GET', candidate];
        return verb === method && url.startsWith(prefix);
      });
    const { status, body } = key ? answers[key]() : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  push.mockReset();
  calls = [];
  answers = {
    [BASE]: () => ({ status: 200, body: { webhooks: fixture.webhooks, latest: fixture.latest } }),
    [`${BASE}/deliveries`]: () => ({ status: 200, body: fixture.deliveries }),
    [`${BASE}/deliveries?cursor=`]: () => ({
      status: 200,
      body: { deliveries: [{ ...fixture.deliveries.deliveries[2], id: 'b0b0b0b0-0000-4000-8000-000000000001' }], nextCursor: null },
    }),
    [`${BASE}/deliveries?status=failure`]: () => ({
      status: 200,
      body: { deliveries: [fixture.deliveries.deliveries[0]], nextCursor: null },
    }),
    [`${BASE}/${HTTP.uuid}`]: () => ({ status: 200, body: HTTP }),
    [`${BASE}/deliveries/${DELIVERY}`]: () => ({ status: 200, body: fixture.detail }),
  };
  installFetch();
});

const gets = () => calls.filter((call) => call.method === 'GET').map((call) => call.url);

describe('Webhooks page', () => {
  it('lists every webhook with its newest delivery, and the recent deliveries', async () => {
    const { container } = render(<WebhooksClient />);
    const table = await screen.findByTestId('pwx-webhooks-table');
    expect(screen.getByTestId('pwx-count')).toHaveTextContent('3 webhooks · 2 enabled');
    const http = within(table).getByTestId(`pwx-webhook-${HTTP.uuid}`);
    expect(http).toHaveTextContent('Provider Ledger API');
    expect(http).toHaveTextContent('Contract requiring verification published');
    expect(http).toHaveTextContent('POST ci.example.com');
    expect(http).toHaveTextContent('Signed');
    expect(within(http).getByTestId('pwx-status')).toHaveTextContent('Failed');
    expect(within(http).getByRole('link', { name: 'Verify Ledger API when a pact changes' })).toHaveAttribute(
      'href',
      `/ade/dashboard/pacts/webhooks/${HTTP.uuid}`,
    );
    const github = within(table).getByTestId(`pwx-webhook-${fixture.webhooks[1].uuid}`);
    expect(github).toHaveTextContent('Billing Service → Ledger API');
    expect(github).toHaveTextContent('GitHub Actions · acme/billing-service');
    const plain = within(table).getByTestId(`pwx-webhook-${fixture.webhooks[2].uuid}`);
    expect(plain).toHaveTextContent('All pacts');
    expect(plain).toHaveTextContent('Disabled');
    expect(plain).toHaveTextContent('Never fired');

    const log = await screen.findByTestId('pwx-deliveries-table');
    expect(within(log).getAllByRole('row')).toHaveLength(4);
    const retrying = within(log).getByTestId(`pwx-delivery-${fixture.deliveries.deliveries[1].id}`);
    expect(retrying).toHaveTextContent('Retrying');
    expect(retrying).toHaveTextContent('Mobile App → Ledger API · 8b1f0c2d9e3a');
    expect(retrying).toHaveTextContent('2 (2 left)');
    expect(retrying).toHaveTextContent('Redelivery');
    expect(gets()).toEqual([BASE, `${BASE}/deliveries`]);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-webhooks', liveMarkup(container.firstElementChild!));
  });

  it('narrows the deliveries by status and loads more', async () => {
    render(<WebhooksClient />);
    fireEvent.click(await screen.findByTestId('pwx-deliveries-more'));
    expect(await screen.findByTestId('pwx-delivery-b0b0b0b0-0000-4000-8000-000000000001')).toBeInTheDocument();
    expect(gets()).toContain(`${BASE}/deliveries?cursor=${fixture.deliveries.nextCursor}`);
    expect(screen.queryByTestId('pwx-deliveries-more')).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId('pwx-status-filter'), { target: { value: 'failure' } });
    await waitFor(() => expect(screen.getAllByTestId(/^pwx-delivery-/)).toHaveLength(1));
    expect(gets()).toContain(`${BASE}/deliveries?status=failure`);
  });

  it('creates a webhook: checks the form, tests it unsaved, then opens it', async () => {
    answers[`POST ${BASE}/execute`] = () => ({ status: 200, body: fixture.test });
    answers[`POST ${BASE}`] = () => ({ status: 200, body: { ...HTTP, uuid: '11111111-2222-4333-8444-555555555555' } });
    render(<WebhooksClient />);
    fireEvent.click(await screen.findByTestId('pwx-new'));
    const editor = await screen.findByTestId('pwx-editor');
    expect(within(editor).getByTestId('pwx-editor-problem')).toHaveTextContent('Enter the http(s) URL to send to.');
    expect(within(editor).getByTestId('pwx-editor-save')).toBeDisabled();

    fireEvent.change(within(editor).getByLabelText('URL'), { target: { value: 'https://ci.example.com/hooks/verify-pact' } });
    fireEvent.change(within(editor).getByLabelText('Provider (optional)'), { target: { value: 'Ledger API' } });
    fireEvent.click(within(editor).getByLabelText('Contract published'));
    fireEvent.change(within(editor).getByLabelText('Signing secret (optional, 16 characters or more)'), {
      target: { value: 'a-shared-secret-of-16' },
    });
    expect(within(editor).queryByTestId('pwx-editor-problem')).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(within(editor).getByTestId('pwx-editor-test'));
    });
    const outcome = await within(editor).findByTestId('pwx-test-outcome');
    expect(outcome).toHaveTextContent('Test succeeded');
    expect(outcome).toHaveTextContent('HTTP 200');

    await act(async () => {
      fireEvent.click(within(editor).getByTestId('pwx-editor-save'));
    });
    await waitFor(() => expect(push).toHaveBeenCalledWith('/ade/dashboard/pacts/webhooks/11111111-2222-4333-8444-555555555555'));
    const posted = calls.filter((call) => call.method === 'POST');
    expect(posted.map((call) => call.url)).toEqual([`${BASE}/execute`, BASE]);
    expect(posted[1].body).toEqual({
      events: [{ name: 'contract_requiring_verification_published' }, { name: 'contract_published' }],
      enabled: true,
      provider: { name: 'Ledger API' },
      request: {
        method: 'POST',
        url: 'https://ci.example.com/hooks/verify-pact',
        headers: { 'Content-Type': 'application/json' },
        body: { pactUrl: '${pactbroker.pactUrl}' },
      },
      signingSecret: 'a-shared-secret-of-16',
    });
  });

  it('shows REST’s refusal of a new webhook and keeps the form', async () => {
    answers[`POST ${BASE}`] = () => ({
      status: 422,
      body: { success: false, error: '/request/url: the host resolves to a private address' },
    });
    render(<WebhooksClient />);
    fireEvent.click(await screen.findByTestId('pwx-new'));
    const editor = await screen.findByTestId('pwx-editor');
    fireEvent.change(within(editor).getByLabelText('URL'), { target: { value: 'https://10.0.0.1/hook' } });
    await act(async () => {
      fireEvent.click(within(editor).getByTestId('pwx-editor-save'));
    });
    expect(await within(editor).findByTestId('pwx-editor-error')).toHaveTextContent('private address');
    expect(push).not.toHaveBeenCalled();
  });

  it('switches the editor to a GitHub Actions target', async () => {
    answers[`POST ${BASE}`] = () => ({ status: 200, body: fixture.webhooks[1] });
    render(<WebhooksClient />);
    fireEvent.click(await screen.findByTestId('pwx-new'));
    const editor = await screen.findByTestId('pwx-editor');
    fireEvent.click(within(editor).getByLabelText('A GitHub Actions workflow (repository_dispatch)'));
    fireEvent.change(within(editor).getByLabelText('Repository'), { target: { value: 'acme/ledger-api' } });
    expect(within(editor).getByTestId('pwx-editor-problem')).toHaveTextContent('Enter a GitHub token');
    fireEvent.change(within(editor).getByLabelText('GitHub token'), { target: { value: 'ghp_token' } });
    await act(async () => {
      fireEvent.click(within(editor).getByTestId('pwx-editor-save'));
    });
    const created = calls.find((call) => call.method === 'POST');
    expect(created?.body).toMatchObject({
      target: { type: 'github_repository_dispatch', repository: 'acme/ledger-api', token: 'ghp_token' },
    });
    expect(created?.body).not.toHaveProperty('request');
  });

  it('shows the CLI command for an empty workspace, and Try again for a refused read', async () => {
    answers[BASE] = () => ({ status: 200, body: { webhooks: [], latest: {} } });
    const { unmount } = render(<WebhooksClient />);
    expect(await screen.findByText('No webhooks yet')).toBeInTheDocument();
    expect(screen.getByLabelText('Create a webhook')).toHaveTextContent('apiome pact create-webhook');
    expect(screen.queryByTestId('pwx-log')).not.toBeInTheDocument();
    unmount();

    answers[BASE] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<WebhooksClient />);
    expect(await screen.findByText('Permission denied')).toBeInTheDocument();
    answers[BASE] = () => ({ status: 200, body: { webhooks: fixture.webhooks, latest: fixture.latest } });
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByTestId('pwx-webhooks-table')).toBeInTheDocument();
  });
});

describe('Webhook page', () => {
  it('shows the webhook, its request with secrets redacted, and its delivery log', async () => {
    const { container } = render(<WebhookDetailClient id={HTTP.uuid} />);
    const overview = await screen.findByTestId('pwx-overview');
    expect(overview).toHaveTextContent('Provider Ledger API');
    expect(overview).toHaveTextContent(`POST ${HTTP.request.url}`);
    expect(overview).toHaveTextContent('X-Apiome-Signature (HMAC-SHA256)');
    expect(screen.getByTestId('pwx-state')).toHaveTextContent('Enabled');
    expect(screen.getByLabelText('Request headers')).toHaveTextContent(`Authorization: ${REDACTED}`);
    expect(screen.getByLabelText('Request body')).toHaveTextContent('${pactbroker.pactUrl}');
    await screen.findByTestId('pwx-deliveries-table');
    expect(gets()).toEqual([`${BASE}/${HTTP.uuid}`, `${BASE}/deliveries?webhook=${HTTP.uuid}`]);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-webhook-detail', liveMarkup(container.firstElementChild!));
  });

  it('tests the webhook and shows what came back; a rate limit shows REST’s message', async () => {
    answers[`POST ${BASE}/${HTTP.uuid}/execute`] = () => ({ status: 200, body: { ...fixture.test, success: false, response: { status: 500, body: 'down' } } });
    render(<WebhookDetailClient id={HTTP.uuid} />);
    const pwx_test = await screen.findByTestId('pwx-test');
    await act(async () => {
      fireEvent.click(pwx_test);
    });
    const panel = await screen.findByTestId('pwx-test-panel');
    expect(panel).toHaveTextContent('Test failed');
    expect(panel).toHaveTextContent('HTTP 500');
    expect(within(panel).getByLabelText('Response body')).toHaveTextContent('down');

    answers[`POST ${BASE}/${HTTP.uuid}/execute`] = () => ({
      status: 429,
      body: { success: false, error: 'this workspace may test webhooks 30 times per 60 seconds; retry later' },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('pwx-test'));
    });
    expect(await screen.findByTestId('pwx-action-error')).toHaveTextContent('30 times per 60 seconds');
  });

  it('disables the webhook with every stored secret kept', async () => {
    answers[`PUT ${BASE}/${HTTP.uuid}`] = () => ({ status: 200, body: { ...HTTP, enabled: false } });
    render(<WebhookDetailClient id={HTTP.uuid} />);
    // PFX-8.1 (#7298): Enable / Disable and Delete live in the header's ⋯ menu (action cap).
    await screen.findByTestId('pwx-test');
    fireEvent.keyDown(screen.getByRole('button', { name: 'More actions' }), { key: 'Enter' });
    const pwx_toggle = await screen.findByTestId('page-header-overflow-toggle');
    expect(pwx_toggle).toHaveTextContent('Disable');
    await act(async () => {
      fireEvent.click(pwx_toggle);
    });
    expect(await screen.findByTestId('pwx-state')).toHaveTextContent('Disabled');
    fireEvent.keyDown(screen.getByRole('button', { name: 'More actions' }), { key: 'Enter' });
    expect(await screen.findByTestId('page-header-overflow-toggle')).toHaveTextContent('Enable');
    const put = calls.find((call) => call.method === 'PUT');
    expect(put?.body).toMatchObject({
      enabled: false,
      signingSecret: REDACTED,
      request: { headers: { Authorization: REDACTED } },
    });
  });

  it('edits the webhook without a Test of unsaved changes', async () => {
    answers[`PUT ${BASE}/${HTTP.uuid}`] = () => ({ status: 200, body: { ...HTTP, description: 'Renamed' } });
    render(<WebhookDetailClient id={HTTP.uuid} />);
    fireEvent.click(await screen.findByTestId('pwx-edit'));
    const editor = await screen.findByTestId('pwx-editor');
    expect(within(editor).queryByTestId('pwx-editor-test')).not.toBeInTheDocument();
    expect(within(editor).getByLabelText('Signing secret (optional, 16 characters or more)')).toHaveAttribute(
      'placeholder',
      'Stored — type to replace',
    );
    fireEvent.change(within(editor).getByLabelText('Description (optional)'), { target: { value: 'Renamed' } });
    await act(async () => {
      fireEvent.click(within(editor).getByTestId('pwx-editor-save'));
    });
    await waitFor(() => expect(screen.queryByTestId('pwx-editor')).not.toBeInTheDocument());
    expect(calls.find((call) => call.method === 'PUT')?.body).toMatchObject({ description: 'Renamed', signingSecret: REDACTED });
  });

  it('removes a stored secret only when asked', async () => {
    answers[`PUT ${BASE}/${HTTP.uuid}`] = () => ({ status: 200, body: { ...HTTP, signed: false } });
    render(<WebhookDetailClient id={HTTP.uuid} />);
    fireEvent.click(await screen.findByTestId('pwx-edit'));
    const editor = await screen.findByTestId('pwx-editor');
    fireEvent.click(within(editor).getByRole('button', { name: 'Remove it' }));
    await act(async () => {
      fireEvent.click(within(editor).getByTestId('pwx-editor-save'));
    });
    await waitFor(() => expect(calls.some((call) => call.method === 'PUT')).toBe(true));
    expect(calls.find((call) => call.method === 'PUT')?.body).not.toHaveProperty('signingSecret');
  });

  it('asks before deleting, then returns to the list', async () => {
    answers[`DELETE ${BASE}/${HTTP.uuid}`] = () => ({ status: 200, body: {} });
    render(<WebhookDetailClient id={HTTP.uuid} />);
    await screen.findByTestId('pwx-test');
    fireEvent.keyDown(screen.getByRole('button', { name: 'More actions' }), { key: 'Enter' });
    fireEvent.click(await screen.findByTestId('page-header-overflow-delete'));
    const confirm = await screen.findByTestId('pwx-delete-confirm');
    expect(confirm).toHaveTextContent('Its queued deliveries, its delivery log and their execution logs are deleted');
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false);
    await act(async () => {
      fireEvent.click(within(confirm).getByTestId('pwx-delete-confirm-action'));
    });
    await waitFor(() => expect(push).toHaveBeenCalledWith('/ade/dashboard/pacts/webhooks'));
  });

  it('offers Try again when the webhook cannot be read', async () => {
    answers[`${BASE}/${HTTP.uuid}`] = () => ({ status: 404, body: { success: false, error: 'no webhook in this workspace' } });
    render(<WebhookDetailClient id={HTTP.uuid} />);
    expect(await screen.findByText('no webhook in this workspace')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
    expect(screen.queryByTestId('pwx-test')).not.toBeInTheDocument();
  });
});

describe('Delivery page', () => {
  it('shows the delivery and every attempt’s log, failed ones open, with Copy', async () => {
    const clipboard = jest.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText: clipboard } });
    const { container } = render(<DeliveryDetailClient id={DELIVERY} />);
    const overview = await screen.findByTestId('pwx-delivery-overview');
    expect(within(overview).getByTestId('pwx-status')).toHaveTextContent('Failed');
    expect(within(overview).getByRole('link', { name: 'Billing Service → Ledger API' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/billing-service/pacts/ledger-api?version=2.4.0',
    );
    expect(within(overview).getByRole('link', { name: 'POST ci.example.com' })).toHaveAttribute(
      'href',
      `/ade/dashboard/pacts/webhooks/${HTTP.uuid}`,
    );
    const attempts = screen.getByTestId('pwx-attempts');
    expect(within(attempts).getAllByRole('listitem')).toHaveLength(4);
    expect(within(attempts).getByLabelText('Log of attempt 4')).toHaveTextContent('moved to the dead-letter list');
    expect(attempts.querySelectorAll('details[open]')).toHaveLength(4);
    expect(screen.getByTestId('pwx-redeliver')).toBeEnabled();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-webhook-delivery', liveMarkup(container.firstElementChild!));

    await act(async () => {
      fireEvent.click(screen.getByTestId('pwx-log-copy'));
    });
    expect(clipboard).toHaveBeenCalledWith(expect.stringContaining('--- Attempt 4 · HTTP 500 ---'));
    expect(screen.getByText('The log is copied.')).toBeInTheDocument();
  });

  it('redelivers and links the new delivery; a refusal shows REST’s reason', async () => {
    const created = { ...fixture.deliveries.deliveries[0], id: 'c0c0c0c0-0000-4000-8000-000000000002', status: 'not_run', triggerType: 'user' };
    answers[`POST ${BASE}/deliveries/${DELIVERY}/redeliver`] = () => ({ status: 200, body: created });
    render(<DeliveryDetailClient id={DELIVERY} />);
    const pwx_redeliver = await screen.findByTestId('pwx-redeliver');
    await act(async () => {
      fireEvent.click(pwx_redeliver);
    });
    const done = await screen.findByTestId('pwx-redelivered');
    expect(within(done).getByRole('link', { name: 'Open the new delivery' })).toHaveAttribute(
      'href',
      `/ade/dashboard/pacts/webhooks/deliveries/${created.id}`,
    );

    answers[`POST ${BASE}/deliveries/${DELIVERY}/redeliver`] = () => ({
      status: 409,
      body: { success: false, error: 'the webhook is disabled; enable it before redelivering' },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('pwx-redeliver'));
    });
    expect(await screen.findByTestId('pwx-redeliver-error')).toHaveTextContent('enable it before redelivering');
  });

  it('cannot redeliver a delivery that is still queued, and says it is not sent yet', async () => {
    answers[`${BASE}/deliveries/${DELIVERY}`] = () => ({
      status: 200,
      body: { ...fixture.detail, status: 'not_run', attemptsMade: 0, attemptsRemaining: 4, executions: [] },
    });
    render(<DeliveryDetailClient id={DELIVERY} />);
    expect(await screen.findByTestId('pwx-not-sent')).toBeInTheDocument();
    expect(screen.getByTestId('pwx-redeliver')).toBeDisabled();
  });
});
