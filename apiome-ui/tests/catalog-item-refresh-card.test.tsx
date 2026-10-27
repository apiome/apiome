/**
 * The Live refresh card and its dialog on a catalog item's Provenance tab (MFI-31.1, #4398).
 *
 * Pins: the card fetches only once its tab is shown; an unset item offers **Set up refresh…**;
 * a failed check shows its reason without hiding the rest; **Check now** posts and shows the new
 * outcome; **Turn off** deletes and re-reads; a viewer sees the facts but no buttons; the dialog
 * sends the PUT body REST expects (keeping a stored credential unless a new one is typed) and
 * shows a refusal instead of closing. Plus axe on the card and the dialog.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import { CatalogItemRefreshCard } from '../src/app/components/ade/catalog/detail/CatalogItemRefreshCard';
import { CatalogRefreshDialog } from '../src/app/components/ade/catalog/detail/CatalogRefreshDialog';
import type { CatalogRefresh } from '../src/app/components/ade/catalog/detail/catalogRefreshModel';

const AXE_OPTIONS = {
  rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
} as const;

const ITEM = { id: 'item-1', name: 'Countries GraphQL' };
const URL = '/api/catalog/item-1/refresh';

const OFF: CatalogRefresh = {
  itemId: 'item-1',
  configured: false,
  cadence: 'off',
  adapter: null,
  endpoint: null,
  options: {},
  authType: 'none',
  hasCredential: false,
  status: 'never',
  lastCheckedAt: null,
  lastSuccessAt: null,
  lastFailureAt: null,
  lastError: null,
  lastFingerprint: null,
  consecutiveFailures: 0,
  nextCheckAt: null,
  tenantEnabled: true,
  adapters: ['graphql', 'grpc'],
};

const DAILY: CatalogRefresh = {
  ...OFF,
  configured: true,
  cadence: 'daily',
  adapter: 'graphql',
  endpoint: 'https://countries.example.com/graphql',
  status: 'unchanged',
  lastCheckedAt: '2026-10-27T10:00:00Z',
  nextCheckAt: '2026-10-28T10:00:00Z',
  authType: 'bearer',
  hasCredential: true,
};

type Route = (init?: RequestInit) => { status?: number; body: unknown };

/** Mock the BFF: `routes[`${method} ${url}`]` answers each call; every call is recorded. */
function mockFetch(routes: Record<string, Route>) {
  const calls: Array<{ method: string; url: string; body?: unknown }> = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    const url = String(input);
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const route = routes[`${method} ${url}`];
    const answer = route ? route(init) : { status: 404, body: { success: false, error: 'not mocked' } };
    const status = answer.status ?? 200;
    return { ok: status < 400, status, json: async () => answer.body } as Response;
  }) as unknown as typeof fetch;
  return calls;
}

beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
  Element.prototype.hasPointerCapture = jest.fn(() => false);
});

afterEach(() => jest.restoreAllMocks());

describe('CatalogItemRefreshCard', () => {
  it('does not fetch until its tab is shown', async () => {
    const calls = mockFetch({ [`GET ${URL}`]: () => ({ body: OFF }) });
    const { rerender } = render(<CatalogItemRefreshCard item={ITEM} active={false} canEdit />);
    expect(calls).toEqual([]);
    rerender(<CatalogItemRefreshCard item={ITEM} active canEdit />);
    await screen.findByTestId('catalog-detail-refresh-facts');
    expect(calls).toHaveLength(1);
  });

  it('offers set-up on an item without a setting, with no check or turn-off', async () => {
    mockFetch({ [`GET ${URL}`]: () => ({ body: OFF }) });
    render(<CatalogItemRefreshCard item={ITEM} active canEdit />);
    expect(await screen.findByTestId('catalog-detail-refresh-status')).toHaveTextContent('Off');
    expect(screen.getByTestId('catalog-detail-refresh-edit')).toHaveTextContent('Set up refresh…');
    expect(screen.queryByTestId('catalog-detail-refresh-check')).toBeNull();
    expect(screen.queryByTestId('catalog-detail-refresh-off')).toBeNull();
  });

  it('shows a configured setting without ever showing the credential', async () => {
    mockFetch({ [`GET ${URL}`]: () => ({ body: DAILY }) });
    render(<CatalogItemRefreshCard item={ITEM} active canEdit />);
    const facts = await screen.findByTestId('catalog-detail-refresh-facts');
    expect(facts).toHaveTextContent('GraphQL introspection');
    expect(facts).toHaveTextContent('https://countries.example.com/graphql');
    expect(facts).toHaveTextContent('Daily');
    expect(facts).toHaveTextContent('Stored (encrypted)');
    expect(screen.getByTestId('catalog-detail-refresh-status')).toHaveTextContent('Up to date');
    expect(screen.getByTestId('catalog-detail-refresh-edit')).toHaveTextContent('Edit refresh…');
  });

  it('reports a failed check with its reason and the backoff', async () => {
    mockFetch({
      [`GET ${URL}`]: () => ({
        body: { ...DAILY, status: 'failed', lastError: 'Connection refused', consecutiveFailures: 3 },
      }),
    });
    render(<CatalogItemRefreshCard item={ITEM} active canEdit />);
    expect(await screen.findByTestId('catalog-detail-refresh-status')).toHaveTextContent('Last check failed');
    const failure = screen.getByTestId('catalog-detail-refresh-failure');
    expect(failure).toHaveTextContent('Connection refused');
    expect(failure).toHaveTextContent('3 failed checks in a row');
  });

  it('checks now and shows the new outcome', async () => {
    const calls = mockFetch({
      [`GET ${URL}`]: () => ({ body: DAILY }),
      [`POST ${URL}/check`]: () => ({ body: { ...DAILY, status: 'changed' } }),
    });
    render(<CatalogItemRefreshCard item={ITEM} active canEdit />);
    fireEvent.click(await screen.findByTestId('catalog-detail-refresh-check'));
    await waitFor(() =>
      expect(screen.getByTestId('catalog-detail-refresh-status')).toHaveTextContent('Source changed')
    );
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([`GET ${URL}`, `POST ${URL}/check`]);
  });

  it('shows a refused check without losing the facts', async () => {
    mockFetch({
      [`GET ${URL}`]: () => ({ body: DAILY }),
      [`POST ${URL}/check`]: () => ({ status: 409, body: { success: false, error: 'Catalog refresh is switched off for this workspace.' } }),
    });
    render(<CatalogItemRefreshCard item={ITEM} active canEdit />);
    fireEvent.click(await screen.findByTestId('catalog-detail-refresh-check'));
    expect(await screen.findByTestId('catalog-detail-refresh-action-error')).toHaveTextContent('switched off');
    expect(screen.getByTestId('catalog-detail-refresh-facts')).toBeInTheDocument();
  });

  it('turns refresh off and re-reads', async () => {
    let configured = true;
    const calls = mockFetch({
      [`GET ${URL}`]: () => ({ body: configured ? DAILY : OFF }),
      [`DELETE ${URL}`]: () => {
        configured = false;
        return { body: {} };
      },
    });
    render(<CatalogItemRefreshCard item={ITEM} active canEdit />);
    fireEvent.click(await screen.findByTestId('catalog-detail-refresh-off'));
    await waitFor(() => expect(screen.getByTestId('catalog-detail-refresh-edit')).toHaveTextContent('Set up refresh…'));
    expect(calls.map((c) => c.method)).toEqual(['GET', 'DELETE', 'GET']);
  });

  it('gives a viewer the facts and no buttons', async () => {
    mockFetch({ [`GET ${URL}`]: () => ({ body: DAILY }) });
    render(<CatalogItemRefreshCard item={ITEM} active canEdit={false} />);
    await screen.findByTestId('catalog-detail-refresh-facts');
    expect(screen.queryByTestId('catalog-detail-refresh-edit')).toBeNull();
    expect(screen.queryByTestId('catalog-detail-refresh-check')).toBeNull();
  });

  it('says the workspace paused refresh, and offers no check', async () => {
    mockFetch({ [`GET ${URL}`]: () => ({ body: { ...DAILY, tenantEnabled: false } }) });
    render(<CatalogItemRefreshCard item={ITEM} active canEdit />);
    expect(await screen.findByTestId('catalog-detail-refresh-status')).toHaveTextContent('Paused for workspace');
    expect(screen.queryByTestId('catalog-detail-refresh-check')).toBeNull();
  });

  it('has no axe violations', async () => {
    mockFetch({ [`GET ${URL}`]: () => ({ body: { ...DAILY, status: 'failed', lastError: 'boom', consecutiveFailures: 1 } }) });
    const { container } = render(<CatalogItemRefreshCard item={ITEM} active canEdit />);
    await screen.findByTestId('catalog-detail-refresh-facts');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});

describe('CatalogRefreshDialog', () => {
  function renderDialog(refresh: CatalogRefresh | null = OFF) {
    const onSaved = jest.fn();
    const onOpenChange = jest.fn();
    render(<CatalogRefreshDialog open item={ITEM} refresh={refresh} onSaved={onSaved} onOpenChange={onOpenChange} />);
    return { onSaved, onOpenChange };
  }

  it('saves a new GraphQL setting with no credential', async () => {
    const calls = mockFetch({ [`PUT ${URL}`]: () => ({ body: DAILY }) });
    const { onSaved, onOpenChange } = renderDialog();
    fireEvent.change(screen.getByTestId('catalog-refresh-endpoint'), {
      target: { value: 'https://countries.example.com/graphql' },
    });
    fireEvent.click(screen.getByTestId('catalog-refresh-save'));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(DAILY));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(calls[0].body).toEqual({
      cadence: 'daily',
      adapter: 'graphql',
      endpoint: 'https://countries.example.com/graphql',
      options: {},
      credential: null,
    });
  });

  it('keeps a stored credential unless a new one is typed', async () => {
    const calls = mockFetch({ [`PUT ${URL}`]: () => ({ body: DAILY }) });
    renderDialog(DAILY);
    expect(screen.getByTestId('catalog-refresh-auth')).toHaveTextContent('Keep current credential');
    expect(screen.queryByTestId('catalog-refresh-secret')).toBeNull();
    fireEvent.click(screen.getByTestId('catalog-refresh-save'));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).not.toHaveProperty('credential');
  });

  it('catches an empty endpoint without calling REST', () => {
    const calls = mockFetch({});
    renderDialog();
    fireEvent.click(screen.getByTestId('catalog-refresh-save'));
    expect(screen.getByTestId('catalog-refresh-error')).toHaveTextContent('Enter the endpoint');
    expect(calls).toEqual([]);
  });

  it('shows a REST refusal and stays open', async () => {
    mockFetch({
      [`PUT ${URL}`]: () => ({ status: 422, body: { success: false, error: 'credentials in URL are not allowed' } }),
    });
    const { onSaved, onOpenChange } = renderDialog();
    fireEvent.change(screen.getByTestId('catalog-refresh-endpoint'), { target: { value: 'https://a.example.com' } });
    fireEvent.click(screen.getByTestId('catalog-refresh-save'));
    expect(await screen.findByTestId('catalog-refresh-error')).toHaveTextContent('credentials in URL');
    expect(onSaved).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it('has no axe violations', async () => {
    mockFetch({});
    renderDialog(DAILY);
    const dialog = screen.getByTestId('catalog-refresh-dialog');
    expect(await axe(dialog, AXE_OPTIONS)).toHaveNoViolations();
  });
});
