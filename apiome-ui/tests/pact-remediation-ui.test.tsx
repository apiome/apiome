/**
 * The **Verification settings** and **Re-publish requests** pages, and the remediation view of the
 * **Verification** page — PFX-6.2 (#6954).
 *
 * Settings page:
 * * the workspace defaults form (cadence with what it does, threshold, window, concurrency, the
 *   requests switch) and the overrides table; axe passes;
 * * **Save** puts the settings and says so; an out-of-range value is refused before anything is
 *   sent; REST's refusal is shown;
 * * **Add override** saves a provider-wide override from the dialog; **Edit** prefills and keeps the
 *   pair; **Remove** deletes one; a deleted target is flagged;
 * * defaults read as defaults; no overrides explains that nothing runs on a schedule; a refused
 *   read offers **Try again**.
 *
 * Requests pages:
 * * the list with each request's pair, pact, state and expiry, narrowed by state through the
 *   address; the empty list says why there is none; axe passes;
 * * a request's overview, who was told, the note; **Acknowledge** posts the note; a closed request
 *   has no form; a refused read offers **Try again**.
 *
 * Verification page: an overdue pact is badged, links to its open request, a skipped scheduled run
 * says why, and the cadence line links to the settings.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-verification-settings`,
 * `pact-republish-requests` and `pact-republish-request`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const replace = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ replace, push: jest.fn() }) }));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-remediation.json';
import verification from './fixtures/pact-verification.json';
import VerificationSettingsClient from '../src/app/components/ade/pactRemediation/VerificationSettingsClient';
import RepublishRequestsClient from '../src/app/components/ade/pactRemediation/RepublishRequestsClient';
import RepublishRequestClient from '../src/app/components/ade/pactRemediation/RepublishRequestClient';
import { CadenceLine, RemediationNotes } from '../src/app/components/ade/pactVerification/VerificationPanels';
import type { VerificationStatusEntry } from '../lib/pact-verification';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const SETTINGS = '/api/pact/verification-settings';
const REQUESTS = '/api/pact/republish-requests';
const [OPEN, ACKNOWLEDGED, EXPIRED] = fixture.requests.requests;

type Answer = { status: number; body: unknown };
let answers: Record<string, (method: string) => Answer>;
let calls: Array<{ url: string; method: string; body?: unknown }>;

/** REST through the proxies: the longest route key the URL starts with answers. */
function installFetch() {
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const key = Object.keys(answers)
      .sort((a, b) => b.length - a.length)
      .find((candidate) => url.startsWith(candidate));
    const { status, body } = key ? answers[key](method) : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

function writes() {
  return calls.filter((call) => call.method !== 'GET');
}

beforeEach(() => {
  replace.mockReset();
  calls = [];
  answers = {
    [SETTINGS]: (method) =>
      method === 'PUT'
        ? { status: 200, body: { ...fixture.settings, cadence: 'hourly', updated_at: '2026-11-26T10:00:00+00:00' } }
        : { status: 200, body: fixture.settings },
    [`${SETTINGS}/overrides`]: (method) =>
      method === 'PUT'
        ? { status: 200, body: fixture.overrides.overrides[0] }
        : { status: 200, body: fixture.overrides },
    [`${SETTINGS}/overrides/`]: () => ({ status: 200, body: {} }),
    '/api/verification-targets': () => ({ status: 200, body: fixture.targets }),
    '/api/pact/pacticipants': () => ({ status: 200, body: fixture.pacticipants }),
    [REQUESTS]: () => ({ status: 200, body: fixture.requests }),
    [`${REQUESTS}/${OPEN.id}`]: (method) =>
      method === 'POST'
        ? {
            status: 200,
            body: { ...OPEN, state: 'acknowledged', note: 'Friday', acknowledged_at: '2026-11-26T10:00:00+00:00' },
          }
        : { status: 200, body: OPEN },
    [`${REQUESTS}/${ACKNOWLEDGED.id}`]: () => ({ status: 200, body: ACKNOWLEDGED }),
    [`${REQUESTS}/${EXPIRED.id}`]: () => ({ status: 200, body: EXPIRED }),
  };
  installFetch();
});

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

describe('Verification settings', () => {
  it('shows the defaults form and the overrides, and passes axe', async () => {
    const { container } = render(<VerificationSettingsClient />);
    expect(await screen.findByTestId('prx-settings-form')).toBeInTheDocument();
    expect(screen.getByLabelText('Verification cadence')).toHaveValue('nightly');
    expect(screen.getByText(/Every 24 hours/)).toHaveTextContent('A pair runs only where an override names');
    expect(screen.getByLabelText('Stale threshold (hours)')).toHaveValue('72');
    expect(screen.getByLabelText(/Ask the consumer to re-publish/)).toBeChecked();
    const table = await screen.findByTestId('prx-overrides-table');
    expect(within(table).getAllByRole('row')).toHaveLength(4);
    const pair = screen.getByTestId(`prx-override-${fixture.overrides.overrides[1].id}`);
    expect(pair).toHaveTextContent('Billing Service');
    expect(pair).toHaveTextContent('Hourly');
    expect(pair).toHaveTextContent('24 h (1 day)');
    expect(screen.getByTestId(`prx-override-${fixture.overrides.overrides[2].id}`)).toHaveTextContent('Deleted');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-verification-settings', liveMarkup(container.firstElementChild!));
  });

  it('lists what Apiome verifies on its own, with the cadence it inherits (PFX-8.15)', async () => {
    render(<VerificationSettingsClient />);
    const table = await screen.findByTestId('prx-schedule-table');
    // Only an override with a live target runs on a schedule: the deleted target and the pair without one do not.
    expect(within(table).getAllByRole('row')).toHaveLength(2);
    const row = screen.getByTestId(`prx-schedule-${fixture.overrides.overrides[0].id}`);
    expect(row).toHaveTextContent('Ledger API');
    expect(row).toHaveTextContent('Every consumer');
    expect(row).toHaveTextContent('Nightly');
    expect(row).toHaveTextContent('(workspace default)');
    fireEvent.click(within(row).getByRole('button', { name: 'Edit the schedule of Ledger API' }));
    expect(await screen.findByTestId('prx-override-dialog')).toHaveTextContent('Edit override');
    expect(screen.getByTestId('pcx-tab-verification')).toHaveTextContent('Verification schedule');
  });

  it('says nothing runs on a schedule without a target', async () => {
    answers[`${SETTINGS}/overrides`] = () => ({ status: 200, body: { overrides: [] } });
    render(<VerificationSettingsClient />);
    expect(await screen.findByTestId('prx-schedule-empty')).toHaveTextContent('Nothing runs on a schedule yet');
  });

  it('saves the settings and says so', async () => {
    render(<VerificationSettingsClient />);
    fireEvent.change(await screen.findByLabelText('Verification cadence'), { target: { value: 'hourly' } });
    fireEvent.change(screen.getByLabelText('Concurrent scheduled runs'), { target: { value: '4' } });
    fireEvent.click(screen.getByTestId('prx-settings-save'));
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
    expect(writes()).toEqual([
      {
        url: SETTINGS,
        method: 'PUT',
        body: {
          cadence: 'hourly',
          stale_threshold_hours: 72,
          max_concurrent_runs: 4,
          request_window_hours: 72,
          republish_requests_enabled: true,
        },
      },
    ]);
  });

  it('refuses an out-of-range value before sending, and shows a refusal from REST', async () => {
    render(<VerificationSettingsClient />);
    fireEvent.change(await screen.findByLabelText('Stale threshold (hours)'), { target: { value: '0' } });
    fireEvent.click(screen.getByTestId('prx-settings-save'));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Stale threshold must be a whole number from 1 to 2160.',
    );
    expect(writes()).toEqual([]);

    answers[SETTINGS] = (method) =>
      method === 'PUT'
        ? { status: 403, body: { success: false, error: 'Permission denied' } }
        : { status: 200, body: fixture.settings };
    fireEvent.change(screen.getByLabelText('Stale threshold (hours)'), { target: { value: '48' } });
    fireEvent.click(screen.getByTestId('prx-settings-save'));
    expect(await screen.findByText('Permission denied')).toBeInTheDocument();
  });

  it('says when the workspace uses the defaults and nothing runs on a schedule', async () => {
    answers[SETTINGS] = () => ({ status: 200, body: fixture.defaults });
    answers[`${SETTINGS}/overrides`] = () => ({ status: 200, body: { overrides: [] } });
    render(<VerificationSettingsClient />);
    expect(await screen.findByTestId('prx-defaults-note')).toHaveTextContent('uses the defaults');
    expect(await screen.findByTestId('prx-overrides-empty')).toHaveTextContent('nothing runs on a schedule');
  });

  it('adds a provider-wide override from the dialog', async () => {
    render(<VerificationSettingsClient />);
    fireEvent.click(await screen.findByTestId('prx-add-override'));
    const dialog = await screen.findByTestId('prx-override-dialog');
    fireEvent.click(within(dialog).getByTestId('prx-override-save'));
    expect(await within(dialog).findByTestId('prx-override-error')).toHaveTextContent('Choose the provider.');
    fireEvent.change(within(dialog).getByLabelText('Provider'), { target: { value: 'orders-api' } });
    await within(dialog).findByRole('option', { name: /Ledger staging/ });
    fireEvent.change(within(dialog).getByLabelText('Verification target for scheduled runs'), {
      target: { value: 'ledger-staging' },
    });
    fireEvent.change(within(dialog).getByLabelText('Cadence'), { target: { value: 'on-publish' } });
    fireEvent.click(within(dialog).getByTestId('prx-override-save'));
    await waitFor(() => expect(screen.queryByTestId('prx-override-dialog')).not.toBeInTheDocument());
    expect(writes()).toEqual([
      {
        url: `${SETTINGS}/overrides`,
        method: 'PUT',
        body: { provider: 'orders-api', cadence: 'on-publish', target_ref: 'ledger-staging' },
      },
    ]);
  });

  it('edits an override keeping its pair, and removes one', async () => {
    render(<VerificationSettingsClient />);
    const pair = fixture.overrides.overrides[1];
    fireEvent.click(await screen.findByRole('button', { name: 'Edit the override of Ledger API ← Billing Service' }));
    const dialog = await screen.findByTestId('prx-override-dialog');
    expect(within(dialog).getByLabelText('Provider')).toBeDisabled();
    expect(within(dialog).getByLabelText(/Consumer/)).toHaveValue('billing-service');
    expect(within(dialog).getByLabelText('Stale threshold (hours)')).toHaveValue('24');
    fireEvent.change(within(dialog).getByLabelText('Stale threshold (hours)'), { target: { value: '12' } });
    fireEvent.click(within(dialog).getByTestId('prx-override-save'));
    await waitFor(() => expect(screen.queryByTestId('prx-override-dialog')).not.toBeInTheDocument());
    expect(writes()[0].body).toEqual({
      provider: 'ledger-api',
      consumer: 'billing-service',
      cadence: 'hourly',
      stale_threshold_hours: 12,
    });

    fireEvent.click(await screen.findByTestId(`prx-remove-${pair.id}`));
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()[1]).toEqual({ url: `${SETTINGS}/overrides/${pair.id}`, method: 'DELETE', body: undefined });
  });

  it('offers Try again when a section cannot be read', async () => {
    answers[`${SETTINGS}/overrides`] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<VerificationSettingsClient />);
    expect(await screen.findByText('The overrides could not be read')).toBeInTheDocument();
    answers[`${SETTINGS}/overrides`] = () => ({ status: 200, body: fixture.overrides });
    fireEvent.click(screen.getByRole('button', { name: /Try again/ }));
    expect(await screen.findByTestId('prx-overrides-table')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Requests
// ---------------------------------------------------------------------------

describe('Re-publish requests', () => {
  it('lists the requests with their state, and passes axe', async () => {
    const { container } = render(<RepublishRequestsClient state="all" />);
    const table = await screen.findByTestId('prx-requests-table');
    expect(within(table).getAllByRole('row')).toHaveLength(4);
    const open = screen.getByTestId(`prx-request-${OPEN.id}`);
    expect(open).toHaveTextContent('Orders UI → Ledger API');
    expect(open).toHaveTextContent('Requested');
    expect(within(open).getByRole('link', { name: 'Orders UI → Ledger API' })).toHaveAttribute(
      'href',
      `/ade/dashboard/pacts/republish-requests/${OPEN.id}`,
    );
    expect(screen.getByTestId(`prx-request-${EXPIRED.id}`)).toHaveTextContent('Expired');
    expect(screen.getByTestId(`prx-request-${EXPIRED.id}`)).toHaveTextContent('Closed');
    expect(calls[0].url).toBe(REQUESTS);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-republish-requests', liveMarkup(container.firstElementChild!));
  });

  it('narrows by state through the address', async () => {
    render(<RepublishRequestsClient state="open" />);
    await screen.findByTestId('prx-requests-table');
    expect(calls[0].url).toBe(`${REQUESTS}?state=open`);
    fireEvent.change(screen.getByTestId('prx-state-filter'), { target: { value: 'expired' } });
    expect(replace).toHaveBeenCalledWith('/ade/dashboard/pacts/republish-requests?state=expired');
  });

  it('says why the list is empty', async () => {
    answers[REQUESTS] = () => ({ status: 200, body: { requests: [], next_cursor: null } });
    render(<RepublishRequestsClient state="open" />);
    expect(await screen.findByText('No open re-publish requests')).toBeInTheDocument();
  });

  it('shows a request, who was told, and acknowledges it with a note', async () => {
    const { container } = render(<RepublishRequestClient id={ACKNOWLEDGED.id} />);
    expect(await screen.findByTestId('prx-facts')).toHaveTextContent('24 h (1 day)');
    expect(screen.getByTestId('prx-note-text')).toHaveTextContent(
      'Re-publishing from the main branch build on Friday.',
    );
    expect(screen.getByTestId('prx-notified-facts')).toHaveTextContent("Sent to the owner team's inbox.");
    expect(screen.getByTestId('prx-acknowledge')).toHaveTextContent('Update note');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-republish-request', liveMarkup(container.firstElementChild!));
  });

  it('posts the acknowledgement and shows the new state', async () => {
    render(<RepublishRequestClient id={OPEN.id} />);
    fireEvent.change(await screen.findByLabelText('Note (optional)'), { target: { value: ' Friday ' } });
    fireEvent.click(screen.getByTestId('prx-acknowledge'));
    expect(await screen.findByTestId('prx-note-text')).toHaveTextContent('Friday');
    expect(writes()).toEqual([{ url: `${REQUESTS}/${OPEN.id}/acknowledge`, method: 'POST', body: { note: 'Friday' } }]);
  });

  it('has no form once closed, and says the escalation reached nobody linked', async () => {
    render(<RepublishRequestClient id={EXPIRED.id} />);
    expect(await screen.findByTestId('prx-notified-facts')).toHaveTextContent('Escalation');
    expect(screen.getByTestId('prx-notified-facts')).toHaveTextContent('Unowned findings report');
    expect(screen.queryByTestId('prx-acknowledge-form')).not.toBeInTheDocument();
  });

  it('offers Try again when the request cannot be read', async () => {
    answers[`${REQUESTS}/${OPEN.id}`] = () => ({ status: 404, body: { success: false, error: 'no such request' } });
    render(<RepublishRequestClient id={OPEN.id} />);
    expect(await screen.findByText('no such request')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Try again/ })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// The Verification page's remediation view
// ---------------------------------------------------------------------------

describe('the Verification page', () => {
  const entries = verification.status.pacts as unknown as VerificationStatusEntry[];
  const entry = (consumer: string) => entries.find((item) => item.consumer === consumer)!;

  it('badges an overdue pact and links its open request', () => {
    render(<RemediationNotes entry={entry('orders-ui')} />);
    expect(screen.getByTestId('pvx-overdue')).toHaveTextContent('Overdue');
    expect(screen.getByTestId('pvx-republish-link')).toHaveAttribute(
      'href',
      `/ade/dashboard/pacts/republish-requests/${OPEN.id}`,
    );
    expect(screen.getByTestId('pvx-republish-link')).toHaveTextContent('Re-publish requested');
  });

  it('says why a scheduled run did not happen, and shows nothing for a healthy pact', () => {
    const { container, rerender } = render(<RemediationNotes entry={entry('reporting-job')} />);
    expect(screen.getByTestId('pvx-schedule-note')).toHaveTextContent('Scheduled run skipped: no provider version');
    rerender(<RemediationNotes entry={entry('billing-service')} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the cadence and threshold with a link to the settings', () => {
    render(<CadenceLine settings={verification.status.settings as never} />);
    const line = screen.getByTestId('pvx-cadence');
    expect(line).toHaveTextContent('Verification cadence: Nightly (workspace default) · stale after 72 h (3 days)');
    expect(line).toHaveTextContent('scheduled runs replay against ledger-staging');
    expect(within(line).getByRole('link', { name: 'Verification settings' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/settings?tab=verification',
    );
  });
});
