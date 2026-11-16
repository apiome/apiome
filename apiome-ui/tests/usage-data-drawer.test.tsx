/**
 * The **Usage data** drawer and the consumer erase section, rendered — RDG-5.4 (#5789).
 *
 * Against a mocked `global.fetch` returning the proxies' `{success, data}` envelopes:
 *
 *   - the drawer reads retention and sources when it opens, and shows the tier caps;
 *   - a retention value above the cap disables **Save retention** with the cap named, and a lower
 *     one is sent with `PUT /api/usage/:retention`;
 *   - **Sample bodies…** opens a form whose **Start sampling** stays disabled until the
 *     acknowledgement is ticked, and then sends the sentence REST requires;
 *   - an agent toolset uses the same words, and **Stop sampling** sends `rate: 0`;
 *   - the export is a download link inside REST's bounds;
 *   - a viewer without the permissions sees every control disabled, with the reason as its title;
 *   - **Erase usage identity** in the bindings drawer needs its acknowledgement and calls
 *     `DELETE …/bindings?erase=true`.
 *
 * The documentation screenshot `runtime-sources-retention` is captured from the dump at the end:
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/usage-data-drawer.test.tsx -t "docs fixtures"`.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { UsageDataDrawer } from '../src/app/components/ade/usage';
import type { UsageRetention, UsageSourceList } from '../src/app/components/ade/usage';
import ConsumerBindingsDrawer, {
  ERASE_ACKNOWLEDGEMENT,
} from '../src/app/components/ade/consumers/ConsumerBindingsDrawer';
import type { ConsumerSummary } from '../src/app/components/ade/consumers/consumersModel';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const ACK = 'I understand that sampled request and response bodies are stored, after redaction, for up to 7 days.';

const RETENTION: UsageRetention = {
  caps: { hourlyDays: 30, rollupDays: 395 },
  setting: { hourlyDays: null, rollupDays: 90 },
  effective: { hourlyDays: 30, rollupDays: 90 },
  sampleRetentionDays: 7,
  updatedAt: '2026-11-10T08:00:00Z',
};

const SOURCES: UsageSourceList = {
  acknowledgement: ACK,
  sources: [
    {
      id: 's-otlp',
      kind: 'otlp',
      environment: 'prod',
      enabled: true,
      samplingRate: 0.25,
      fieldCapture: true,
      bodySamples: { rate: 0, until: null, open: false, maxRate: 0.05, maxWindowDays: 7, retentionDays: 7 },
      lastReceivedAt: '2026-11-16T09:00:00Z',
    },
    {
      id: 's-har',
      kind: 'har',
      environment: 'staging',
      enabled: true,
      samplingRate: 1,
      fieldCapture: false,
      bodySamples: { rate: 0.02, until: '2026-11-19T12:00:00Z', open: true, maxRate: 0.05, maxWindowDays: 7, retentionDays: 7 },
      lastReceivedAt: null,
    },
  ],
  agentToolsets: [
    {
      id: 'ts-1',
      versionId: 'v1',
      versionLabel: '1.2.0',
      enabled: true,
      bodySamples: { rate: 0.1, until: '2026-11-18T09:00:00Z', open: true, maxRate: 1, maxWindowDays: 7, retentionDays: 7 },
    },
  ],
};

type Call = { url: string; method: string; body: unknown };

/** Mock fetch: answer the usage proxy by path and record every call. */
function mockFetch(): Call[] {
  const calls: Call[] = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const ok = (data: unknown) => ({ status: 200, json: async () => ({ success: true, data }) }) as Response;
    if (url === '/api/usage/:retention') return ok(RETENTION);
    if (url === '/api/usage/pets/sources') return ok(SOURCES);
    if (url.startsWith('/api/usage/pets/sources/')) return ok(SOURCES.sources[0]);
    if (url.startsWith('/api/usage/:toolsets/')) return ok(SOURCES.agentToolsets[0]);
    if (url.includes('/bindings?erase=true')) return ok({ consumer: 'billing-service', erased: true, bindings: 2, calls: 30 });
    if (url.endsWith('/bindings')) return ok({ bindings: [] });
    if (url.includes('/runtime')) {
      return ok({
        consumer_id: 'c1', slug: 'billing-service', name: 'Billing', contract_state: 'undeclared',
        since_day: '2026-10-18', until_day: '2026-11-16',
        summary: { declared_and_used: 0, declared_unused: 0, used_undeclared: 0, calls: 0, last_seen_day: null },
        declared_and_used: [], declared_unused: [], used_undeclared: [],
      });
    }
    return { status: 404, json: async () => ({ success: false, error: 'not mocked' }) } as Response;
  }) as typeof fetch;
  return calls;
}

const ALL = () => true;

async function openDrawer(can: (permission: string) => boolean = ALL) {
  const calls = mockFetch();
  const user = userEvent.setup();
  render(<UsageDataDrawer open onOpenChange={() => undefined} projectRef="pets" can={can} />);
  const drawer = await screen.findByTestId('usage-data-drawer');
  await within(drawer).findByText(/Your tier keeps hourly counters for 30 days/);
  await within(drawer).findByTestId('source-s-otlp');
  return { user, drawer, calls };
}

describe('the usage data drawer', () => {
  it('reads retention and sources when it opens and shows the caps and settings', async () => {
    const { drawer, calls } = await openDrawer();
    expect(calls.map((call) => call.url)).toEqual(expect.arrayContaining(['/api/usage/:retention', '/api/usage/pets/sources']));
    expect(within(drawer).getByLabelText('Daily rollups (days)')).toHaveValue('90');
    expect(within(drawer).getByText('Applies: 90 days')).toBeInTheDocument();
    expect(within(drawer).getByText('Head sampling 25 %')).toBeInTheDocument();
    expect(within(drawer).getByTestId('source-s-har')).toHaveTextContent('2 % until 19 Nov 2026, 12:00 UTC');
    expect(within(drawer).getByTestId('toolset-ts-1')).toHaveTextContent('Version 1.2.0');
    expect(within(drawer).getByTestId('toolset-ts-1')).toHaveTextContent('at most 100 % for 7 days');
  });

  it('refuses retention above the cap with the cap named, and saves a lower value', async () => {
    const { user, drawer, calls } = await openDrawer();
    const hourly = within(drawer).getByLabelText('Hourly counters (days)');
    await user.type(hourly, '31');
    const save = within(drawer).getByRole('button', { name: 'Save retention' });
    expect(save).toBeDisabled();
    expect(save).toHaveAttribute('title', "Hourly retention may be at most 30 days on this workspace's tier.");
    await user.clear(hourly);
    await user.type(hourly, '7');
    await user.click(save);
    await waitFor(() => expect(calls.some((call) => call.method === 'PUT')).toBe(true));
    expect(calls.find((call) => call.method === 'PUT')).toEqual({
      url: '/api/usage/:retention',
      method: 'PUT',
      body: { hourlyDays: 7, rollupDays: 90 },
    });
  });

  it('opens body samples only after the acknowledgement is ticked, and sends the sentence', async () => {
    const { user, drawer, calls } = await openDrawer();
    const source = within(drawer).getByTestId('source-s-otlp');
    await user.click(within(source).getByRole('button', { name: 'Sample bodies…' }));
    const form = within(source).getByTestId('source-s-otlp-form');
    const start = within(form).getByRole('button', { name: 'Start sampling' });
    expect(start).toBeDisabled();
    expect(start).toHaveAttribute('title', 'Tick the acknowledgement first.');
    await user.clear(within(form).getByLabelText('Rate (%)'));
    await user.type(within(form).getByLabelText('Rate (%)'), '6');
    expect(start).toHaveAttribute('title', 'Enter a rate above 0 and at most 5 %.');
    await user.clear(within(form).getByLabelText('Rate (%)'));
    await user.type(within(form).getByLabelText('Rate (%)'), '5');
    await user.click(within(form).getByRole('checkbox', { name: ACK }));
    expect(start).toBeEnabled();
    await user.click(start);
    await waitFor(() => expect(calls.some((call) => call.method === 'PATCH')).toBe(true));
    const patch = calls.find((call) => call.method === 'PATCH') as Call;
    expect(patch.url).toBe('/api/usage/pets/sources/s-otlp');
    expect(patch.body).toMatchObject({ bodySamples: { rate: 0.05, acknowledgement: ACK } });
  });

  it('stops a toolset window with rate 0, and toggles field capture on a source', async () => {
    const { user, drawer, calls } = await openDrawer();
    await user.click(within(within(drawer).getByTestId('toolset-ts-1')).getByRole('button', { name: 'Stop sampling' }));
    await waitFor(() => expect(calls.some((call) => call.url === '/api/usage/:toolsets/ts-1/body-samples')).toBe(true));
    expect(calls.find((call) => call.url === '/api/usage/:toolsets/ts-1/body-samples')?.body).toEqual({ rate: 0 });
    await user.click(within(within(drawer).getByTestId('source-s-har')).getByRole('switch'));
    await waitFor(() => expect(calls.some((call) => call.url === '/api/usage/pets/sources/s-har')).toBe(true));
    expect(calls.find((call) => call.url === '/api/usage/pets/sources/s-har')?.body).toEqual({ fieldCapture: true });
  });

  it('offers the export as a download link inside the REST bounds', async () => {
    const { user, drawer } = await openDrawer();
    await user.selectOptions(within(drawer).getByLabelText('Format'), 'json');
    const days = within(drawer).getByLabelText('Last (days)');
    await user.clear(days);
    await user.type(days, '90');
    expect(within(drawer).getByTestId('usage-export-link')).toHaveAttribute('href', '/api/usage/pets/export?format=json&days=90');
    await user.clear(days);
    await user.type(days, '800');
    expect(within(drawer).getByRole('button', { name: 'Download export' })).toHaveAttribute('title', 'Enter 1 to 730 days.');
  });

  it('shows a viewer every control disabled with the reason', async () => {
    const { drawer } = await openDrawer(() => false);
    expect(within(drawer).getByRole('button', { name: 'Save retention' })).toHaveAttribute(
      'title',
      'Only an Owner or Admin can change retention.',
    );
    expect(within(drawer).getByLabelText('Hourly counters (days)')).toBeDisabled();
    expect(within(within(drawer).getByTestId('source-s-otlp')).getByRole('button', { name: 'Sample bodies…' })).toHaveAttribute(
      'title',
      'You need projects:edit to sample bodies.',
    );
    expect(within(within(drawer).getByTestId('toolset-ts-1')).getByRole('button', { name: 'Stop sampling' })).toBeDisabled();
    expect(within(drawer).getByRole('button', { name: 'Download export' })).toBeDisabled();
  });
});

const BILLING = {
  consumer: { id: 'c1', slug: 'billing-service', name: 'Billing Service' },
  contract: null,
  runtime: null,
} as unknown as ConsumerSummary;

describe('erasing a consumer usage identity', () => {
  function renderBindings(onErase: (slug: string) => Promise<string | null>, canDelete = true) {
    mockFetch();
    render(
      <ConsumerBindingsDrawer
        open
        onOpenChange={() => undefined}
        summary={BILLING}
        loadBindings={async () => []}
        loadRuntime={async () =>
          ({
            consumer_id: 'c1', slug: 'billing-service', name: 'Billing', contract_state: 'undeclared',
            since_day: '2026-10-18', until_day: '2026-11-16',
            summary: { declared_and_used: 0, declared_unused: 0, used_undeclared: 0, calls: 0, last_seen_day: null },
            declared_and_used: [], declared_unused: [], used_undeclared: [],
          }) as never
        }
        onCreate={async () => null}
        onDelete={async () => null}
        onAddToContract={async () => null}
        canCreate
        canDelete={canDelete}
        canEdit
        onErase={onErase}
      />,
    );
  }

  it('needs its acknowledgement, then erases', async () => {
    const erase = jest.fn(async () => null);
    const user = userEvent.setup();
    renderBindings(erase);
    const section = await screen.findByTestId('consumer-erase');
    const button = within(section).getByRole('button', { name: 'Erase usage identity' });
    expect(button).toBeDisabled();
    await user.click(within(section).getByRole('checkbox', { name: ERASE_ACKNOWLEDGEMENT }));
    await user.click(button);
    expect(erase).toHaveBeenCalledWith('billing-service');
    expect(await within(section).findByText('Erased. Its calls now count as anonymous.')).toBeInTheDocument();
  });

  it('is absent for a viewer who cannot delete bindings', async () => {
    renderBindings(async () => null, false);
    await screen.findByTestId('consumer-bindings-drawer');
    expect(screen.queryByTestId('consumer-erase')).not.toBeInTheDocument();
  });
});

describe('the docs fixtures', () => {
  it('renders the usage data drawer with a body-sample window being opened', async () => {
    const { user, drawer } = await openDrawer();
    await user.type(within(drawer).getByLabelText('Hourly counters (days)'), '14');
    await user.click(within(within(drawer).getByTestId('source-s-otlp')).getByRole('button', { name: 'Sample bodies…' }));
    writeA11yFixture('runtime-sources-retention', liveMarkup(drawer));
  });
});
