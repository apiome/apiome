/**
 * Deprecating a type from its detail page (#3482): the Deprecate dialog, the notice above the
 * schema, Edit deprecation and Restore.
 *
 * `fetch` is routed by URL and method so each test states exactly which calls it expects — the
 * detail read, the replacement list, and the lifecycle write.
 */

import React from 'react';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';

jest.mock('next/navigation', () => ({
  useParams: () => ({ id: 'prim-2' }),
  useRouter: () => ({ push: jest.fn() }),
}));

// Monaco needs workers jsdom has no use for; the schema pane is not what this suite is about.
jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: (props: { value?: string }) => <textarea readOnly value={props.value ?? ''} />,
}));

// Radix Dialog needs a few browser APIs jsdom doesn't implement.
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  if (!Element.prototype.hasPointerCapture) Element.prototype.hasPointerCapture = () => false;
  if (!Element.prototype.setPointerCapture) Element.prototype.setPointerCapture = () => {};
  if (!Element.prototype.releasePointerCapture) Element.prototype.releasePointerCapture = () => {};
  Element.prototype.scrollIntoView = () => {};
});

import PrimitiveDetailClient from '../src/app/ade/dashboard/primitives/[id]/PrimitiveDetailClient';
import { DeprecationNotice } from '../src/app/components/ade/primitives/detail';

const MONEY = {
  id: 'prim-2',
  name: 'money',
  description: 'A monetary amount with a currency.',
  category: 'object',
  is_system: false,
  namespace: 'tenant/acme/v1/types',
  schema_id: 'https://api.apiome.dev/types/tenant/acme/v1/types/money',
  base_uri: 'https://api.apiome.dev/types/tenant/acme/v1/types/',
  draft: '2020-12',
  source: 'human',
  usage_count: 2,
  created_at: '2026-06-18T09:00:00.000Z',
  refs: [],
  dependents: [{ id: 'p-invoice', name: 'invoice', scope: 'tenant', namespace: 'tenant/acme/v1/types' }],
  schema: { type: 'object', properties: { amount: { type: 'string' } } },
};

const DEPRECATED_MONEY = {
  ...MONEY,
  deprecated: true,
  deprecated_at: '2026-11-13T12:00:00Z',
  sunset_date: '2099-01-31',
  deprecation_message: 'Use money-v2.',
  replacement_id: 'prim-9',
  replacement: { id: 'prim-9', name: 'money-v2', schema_id: 'https://x/money-v2' },
};

const TYPES = [
  MONEY,
  { id: 'prim-9', name: 'money-v2', namespace: 'tenant/acme/v2/types' },
  { id: 'prim-8', name: 'old-money', namespace: 'tenant/acme/v0/types', deprecated: true },
];

interface WriteReply {
  ok?: boolean;
  body: Record<string, unknown>;
}

/**
 * Route `fetch` by URL: the detail read answers `detail`, the list answers `TYPES`, and the
 * lifecycle endpoint answers `write`.
 */
function mockFetch(detail: unknown, write?: WriteReply) {
  const fetchMock = jest.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/deprecate')) {
      return { ok: write?.ok ?? true, json: async () => write?.body ?? {} };
    }
    if (url === '/api/primitives') {
      return { ok: true, json: async () => ({ success: true, primitives: TYPES }) };
    }
    void init;
    return { ok: true, json: async () => ({ success: true, primitive: detail }) };
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

/** The lifecycle calls among everything `fetch` was asked. */
const lifecycleCalls = (fetchMock: jest.Mock) =>
  fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/deprecate'));

async function renderDetail(detail: unknown, write?: WriteReply) {
  const fetchMock = mockFetch(detail, write);
  render(<PrimitiveDetailClient />);
  await waitFor(() =>
    expect(screen.getByRole('heading', { level: 1, name: /money/ })).toBeInTheDocument()
  );
  return fetchMock;
}

afterEach(() => jest.restoreAllMocks());

describe('deprecating a type', () => {
  it('opens the dialog with three optional fields and the advisory', async () => {
    await renderDetail(MONEY);

    fireEvent.click(screen.getByTestId('primitive-detail-deprecate'));

    const dialog = await screen.findByRole('dialog', { name: 'Deprecate money' });
    expect(within(dialog).getByLabelText('Sunset date')).toHaveValue('');
    expect(within(dialog).getByLabelText('Message')).toHaveValue('');
    expect(within(dialog).getByLabelText('Replacement type')).toHaveValue('');
    expect(dialog).toHaveTextContent('existing bindings keep working');
  });

  it('offers every other active type as a replacement — not itself, not a deprecated one', async () => {
    await renderDetail(MONEY);
    fireEvent.click(screen.getByTestId('primitive-detail-deprecate'));

    const select = await screen.findByTestId('deprecate-replacement');
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(2));
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'No replacement',
      'money-v2 — tenant/acme/v2/types',
    ]);
  });

  it('sends the details, then shows the badge, the notice and Restore', async () => {
    const fetchMock = await renderDetail(MONEY, {
      body: { success: true, primitive: DEPRECATED_MONEY },
    });
    fireEvent.click(screen.getByTestId('primitive-detail-deprecate'));

    const select = await screen.findByTestId('deprecate-replacement');
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(2));
    fireEvent.change(screen.getByTestId('deprecate-sunset-date'), {
      target: { value: '2099-01-31' },
    });
    fireEvent.change(screen.getByTestId('deprecate-message'), {
      target: { value: '  Use money-v2.  ' },
    });
    fireEvent.change(select, { target: { value: 'prim-9' } });
    fireEvent.click(screen.getByTestId('deprecate-submit'));

    await waitFor(() => expect(lifecycleCalls(fetchMock)).toHaveLength(1));
    const [url, init] = lifecycleCalls(fetchMock)[0];
    expect(url).toBe('/api/primitives/prim-2/deprecate');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      sunset_date: '2099-01-31',
      message: 'Use money-v2.',
      replacement_id: 'prim-9',
    });

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByTestId('primitive-detail-badge-deprecated')).toHaveTextContent('deprecated');
    const notice = screen.getByTestId('primitive-detail-deprecation');
    expect(notice).toHaveTextContent('Deprecated — sunset on 2099-01-31');
    expect(notice).toHaveTextContent('Use money-v2.');
    expect(screen.getByTestId('primitive-detail-replacement')).toHaveAttribute(
      'href',
      '/ade/dashboard/primitives/prim-9'
    );
    expect(screen.getByTestId('primitive-detail-meta-lifecycle')).toHaveTextContent(
      'deprecated · sunset 2099-01-31'
    );
    expect(screen.getByTestId('primitive-detail-restore')).toBeEnabled();
    expect(screen.queryByTestId('primitive-detail-deprecate')).not.toBeInTheDocument();
    // The write's answer carries no dependents; the ones on screen must survive it.
    expect(screen.getByRole('table', { name: 'Dependents' })).toHaveTextContent('invoice');
  });

  it('deprecates with no details at all', async () => {
    const fetchMock = await renderDetail(MONEY, {
      body: { success: true, primitive: { ...MONEY, deprecated: true, deprecated_at: 'x' } },
    });
    fireEvent.click(screen.getByTestId('primitive-detail-deprecate'));
    fireEvent.click(await screen.findByTestId('deprecate-submit'));

    await waitFor(() => expect(lifecycleCalls(fetchMock)).toHaveLength(1));
    expect(JSON.parse(lifecycleCalls(fetchMock)[0][1].body)).toEqual({
      sunset_date: null,
      message: null,
      replacement_id: null,
    });
    await waitFor(() =>
      expect(screen.getByTestId('primitive-detail-deprecation')).toHaveTextContent('Deprecated')
    );
  });

  it('blocks a past sunset date before anything is sent', async () => {
    const fetchMock = await renderDetail(MONEY);
    fireEvent.click(screen.getByTestId('primitive-detail-deprecate'));

    fireEvent.change(await screen.findByTestId('deprecate-sunset-date'), {
      target: { value: '2001-01-01' },
    });

    expect(screen.getByText('The sunset date cannot be in the past.')).toBeInTheDocument();
    const submit = screen.getByTestId('deprecate-submit');
    expect(submit).toBeDisabled();
    expect(submit).toHaveAttribute('title', 'Fix the highlighted fields first');
    fireEvent.click(submit);
    expect(lifecycleCalls(fetchMock)).toHaveLength(0);
  });

  it('keeps the dialog open and says why when the server refuses', async () => {
    await renderDetail(MONEY, {
      ok: false,
      body: { success: false, error: "Replacement type 'old-money' is itself deprecated" },
    });
    fireEvent.click(screen.getByTestId('primitive-detail-deprecate'));
    fireEvent.click(await screen.findByTestId('deprecate-submit'));

    expect(await screen.findByTestId('deprecate-error')).toHaveTextContent('itself deprecated');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.queryByTestId('primitive-detail-deprecation')).not.toBeInTheDocument();
  });

  it('closes on Cancel without writing', async () => {
    const fetchMock = await renderDetail(MONEY);
    fireEvent.click(screen.getByTestId('primitive-detail-deprecate'));

    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(lifecycleCalls(fetchMock)).toHaveLength(0);
  });
});

describe('a deprecated type', () => {
  it('shows the notice, the badge and Restore on load', async () => {
    await renderDetail(DEPRECATED_MONEY);

    expect(screen.getByTestId('primitive-detail-badge-deprecated')).toBeInTheDocument();
    expect(screen.getByTestId('primitive-detail-deprecation')).toHaveAttribute(
      'data-sunset-passed',
      'false'
    );
    expect(screen.getByTestId('primitive-detail-restore')).toHaveTextContent('Restore');
    expect(screen.getByTestId('primitive-detail-edit-deprecation')).toBeInTheDocument();
  });

  it('opens Edit deprecation pre-filled, keeping the stored replacement selected', async () => {
    await renderDetail(DEPRECATED_MONEY);

    fireEvent.click(screen.getByTestId('primitive-detail-edit-deprecation'));

    const dialog = await screen.findByRole('dialog', { name: 'Edit deprecation' });
    expect(within(dialog).getByLabelText('Sunset date')).toHaveValue('2099-01-31');
    expect(within(dialog).getByLabelText('Message')).toHaveValue('Use money-v2.');
    expect(within(dialog).getByLabelText('Replacement type')).toHaveValue('prim-9');
    expect(within(dialog).getByTestId('deprecate-submit')).toHaveTextContent('Save changes');
  });

  it('restores with one DELETE and clears every trace of the deprecation', async () => {
    const fetchMock = await renderDetail(DEPRECATED_MONEY, {
      body: { success: true, primitive: MONEY },
    });

    fireEvent.click(screen.getByTestId('primitive-detail-restore'));

    await waitFor(() => expect(lifecycleCalls(fetchMock)).toHaveLength(1));
    const [url, init] = lifecycleCalls(fetchMock)[0];
    expect(url).toBe('/api/primitives/prim-2/deprecate');
    expect(init.method).toBe('DELETE');
    await waitFor(() =>
      expect(screen.queryByTestId('primitive-detail-deprecation')).not.toBeInTheDocument()
    );
    expect(screen.queryByTestId('primitive-detail-badge-deprecated')).not.toBeInTheDocument();
    expect(screen.getByTestId('primitive-detail-deprecate')).toBeEnabled();
    expect(screen.getByTestId('primitive-detail-meta-lifecycle')).toHaveTextContent('active');
  });

  it('says why when a restore fails, and stays deprecated', async () => {
    await renderDetail(DEPRECATED_MONEY, {
      ok: false,
      body: { success: false, error: 'Permission denied' },
    });

    fireEvent.click(screen.getByTestId('primitive-detail-restore'));

    expect(await screen.findByTestId('primitive-detail-lifecycle-error')).toHaveTextContent(
      'Permission denied'
    );
    expect(screen.getByTestId('primitive-detail-deprecation')).toBeInTheDocument();
  });
});

describe('DeprecationNotice', () => {
  const base = {
    title: 'Deprecated',
    message: 'This type is being retired.',
    advisory: 'It still resolves and validates, and existing bindings keep working.',
    sunsetPassed: false,
    replacement: null,
  };

  it('draws no replacement line when none was named', () => {
    render(<DeprecationNotice notice={base} />);

    expect(screen.getByTestId('primitive-detail-deprecation')).toHaveTextContent(base.advisory);
    expect(screen.queryByTestId('primitive-detail-replacement')).not.toBeInTheDocument();
  });

  it('marks a passed sunset date', () => {
    render(
      <DeprecationNotice
        notice={{ ...base, title: 'Deprecated — sunset passed on 2026-11-12', sunsetPassed: true }}
      />
    );

    expect(screen.getByTestId('primitive-detail-deprecation')).toHaveAttribute(
      'data-sunset-passed',
      'true'
    );
    expect(screen.getByText('Deprecated — sunset passed on 2026-11-12')).toBeInTheDocument();
  });
});
