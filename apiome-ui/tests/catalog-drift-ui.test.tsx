/**
 * The catalog drift surfaces (MFI-31.3, #4400): the card/row chip, the item banner, "What changed"
 * on the Versions pane, and the Drift alerts dialog.
 *
 * Pins: the chip names the severity and links to the drift; the banner opens the drift and its
 * Dismiss posts (and is absent for a viewer); the panel is lazy, shows the classified changes worst
 * first, ticks the two versions for the diff on a drift link, and draws nothing without drift; the
 * dialog loads the settings, says email is not sent yet, shows the digest-only option only in
 * digest mode, and saves. Plus axe on each.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import { DriftBadge } from '../src/app/components/ade/catalog/CatalogBadges';
import { CatalogDriftAlertsDialog } from '../src/app/components/ade/catalog/CatalogDriftAlertsDialog';
import { CatalogDriftBanner } from '../src/app/components/ade/catalog/detail/CatalogDriftBanner';
import { CatalogDriftPanel } from '../src/app/components/ade/catalog/detail/CatalogDriftPanel';
import {
  DEFAULT_DRIFT_SETTINGS,
  type CatalogDriftBadgeData,
  type CatalogDriftEvent,
} from '../src/app/components/ade/catalog/catalogDriftModel';

const AXE_OPTIONS = {
  rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
} as const;

const BADGE: CatalogDriftBadgeData = {
  eventId: 'e-1',
  severity: 'breaking',
  versionId: 'v-2',
  versionLabel: '2026-10-28T12:00Z',
  changeCount: 2,
  counts: { safe: 1, dangerous: 0, breaking: 1 },
  trigger: 'sweep',
  detectedAt: '2026-10-28T12:00:00Z',
  link: '/ade/dashboard/catalog/item-1?tab=versions&drift=e-1',
};

const EVENT: CatalogDriftEvent = {
  ...BADGE,
  parentVersionId: 'v-1',
  parentVersionLabel: '1.0.0',
  notification: 'sent',
  notifiedAt: '2026-10-28T12:00:00Z',
  dismissedAt: null,
  changes: [
    { severity: 'breaking', key: 'Order.total', rationale: "field 'Order.total' was removed", ruleId: 'removed-entity' },
    { severity: 'safe', key: 'Query.orders', rationale: "operation 'Query.orders' was added", ruleId: 'added-entity' },
  ],
};

type Route = (init?: RequestInit) => { status?: number; body: unknown };

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

describe('DriftBadge', () => {
  it('names the severity and links to the drift', async () => {
    const { container } = render(<DriftBadge drift={BADGE} />);
    const chip = screen.getByTestId('catalog-drift-badge');
    expect(chip).toHaveTextContent('Breaking drift');
    expect(chip).toHaveAttribute('href', BADGE.link);
    expect(chip).toHaveAttribute('data-severity', 'breaking');
    expect(chip).toHaveAttribute('title', 'The live API changed in 2026-10-28T12:00Z: 1 breaking · 1 safe');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('draws nothing without drift', () => {
    const { container } = render(<DriftBadge drift={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('CatalogDriftBanner', () => {
  it('opens the drift and dismisses it', async () => {
    const calls = mockFetch({ 'POST /api/catalog/item-1/drift/e-1/dismiss': () => ({ body: { ...EVENT, dismissedAt: 'now' } }) });
    const onOpen = jest.fn();
    const onDismissed = jest.fn();
    const { container } = render(
      <CatalogDriftBanner itemId="item-1" drift={BADGE} canDismiss onOpen={onOpen} onDismissed={onDismissed} />,
    );
    const banner = screen.getByTestId('catalog-drift-banner');
    expect(banner).toHaveAttribute('role', 'status');
    expect(banner).toHaveTextContent('Live refresh found breaking changes in version 2026-10-28T12:00Z');
    expect(banner).toHaveTextContent('1 breaking · 1 safe. Existing callers can break.');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();

    fireEvent.click(screen.getByTestId('catalog-drift-open'));
    expect(onOpen).toHaveBeenCalledWith('e-1');

    fireEvent.click(screen.getByTestId('catalog-drift-dismiss'));
    await waitFor(() => expect(onDismissed).toHaveBeenCalledWith('e-1'));
    expect(calls).toEqual([{ method: 'POST', url: '/api/catalog/item-1/drift/e-1/dismiss', body: undefined }]);
  });

  it('keeps the banner and says why when the dismissal is refused', async () => {
    mockFetch({ 'POST /api/catalog/item-1/drift/e-1/dismiss': () => ({ status: 403, body: { success: false, error: 'Permission denied' } }) });
    const onDismissed = jest.fn();
    render(<CatalogDriftBanner itemId="item-1" drift={BADGE} canDismiss onOpen={jest.fn()} onDismissed={onDismissed} />);
    fireEvent.click(screen.getByTestId('catalog-drift-dismiss'));
    expect(await screen.findByText(/Permission denied/)).toBeInTheDocument();
    expect(onDismissed).not.toHaveBeenCalled();
  });

  it('offers no Dismiss to a viewer, and draws nothing without drift', () => {
    const { rerender } = render(
      <CatalogDriftBanner itemId="item-1" drift={BADGE} canDismiss={false} onOpen={jest.fn()} onDismissed={jest.fn()} />,
    );
    expect(screen.queryByTestId('catalog-drift-dismiss')).toBeNull();
    expect(screen.getByTestId('catalog-drift-open')).toBeInTheDocument();
    rerender(<CatalogDriftBanner itemId="item-1" drift={null} canDismiss onOpen={jest.fn()} onDismissed={jest.fn()} />);
    expect(screen.queryByTestId('catalog-drift-banner')).toBeNull();
  });
});

describe('CatalogDriftPanel', () => {
  const URL = '/api/catalog/item-1/drift';

  it('waits for its tab, then shows the changes worst first', async () => {
    const calls = mockFetch({ [`GET ${URL}`]: () => ({ body: { events: [EVENT] } }) });
    const onCompare = jest.fn();
    const { rerender, container } = render(
      <CatalogDriftPanel itemId="item-1" active={false} requestedEventId={null} onCompare={onCompare} />,
    );
    expect(calls).toEqual([]);
    rerender(<CatalogDriftPanel itemId="item-1" active requestedEventId={null} onCompare={onCompare} />);
    const rows = (await screen.findByTestId('catalog-drift-changes')).querySelectorAll('tbody tr');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute('data-severity', 'breaking');
    expect(rows[0]).toHaveTextContent('Order.total');
    expect(screen.getByTestId('catalog-drift-facts')).toHaveTextContent('1.0.0 → 2026-10-28T12:00Z');
    expect(screen.getByTestId('catalog-drift-facts')).toHaveTextContent('Scheduled check');
    expect(screen.getByTestId('catalog-drift-facts')).toHaveTextContent('Announced');
    expect(onCompare).not.toHaveBeenCalled();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();

    fireEvent.click(screen.getByTestId('catalog-drift-compare'));
    expect(onCompare).toHaveBeenCalledWith({ base: 'v-1', head: 'v-2' });
  });

  it('opens the diff on its own when the address names the drift', async () => {
    mockFetch({ [`GET ${URL}`]: () => ({ body: { events: [{ ...EVENT, eventId: 'e-2' }, EVENT] } }) });
    const onCompare = jest.fn();
    render(<CatalogDriftPanel itemId="item-1" active requestedEventId="e-1" onCompare={onCompare} />);
    await waitFor(() => expect(onCompare).toHaveBeenCalledWith({ base: 'v-1', head: 'v-2' }));
    expect(onCompare).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('catalog-drift-event-e-1')).toHaveAttribute('aria-pressed', 'true');
  });

  it('says when the stored changes are capped', async () => {
    mockFetch({ [`GET ${URL}`]: () => ({ body: { events: [{ ...EVENT, changeCount: 250 }] } }) });
    render(<CatalogDriftPanel itemId="item-1" active requestedEventId={null} onCompare={jest.fn()} />);
    expect(await screen.findByTestId('catalog-drift-truncated')).toHaveTextContent('Showing the 2 most severe of 250 changes.');
  });

  it('draws nothing for an item without drift', async () => {
    const calls = mockFetch({ [`GET ${URL}`]: () => ({ body: { events: [] } }) });
    const { container } = render(<CatalogDriftPanel itemId="item-1" active requestedEventId={null} onCompare={jest.fn()} />);
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a retryable error', async () => {
    mockFetch({ [`GET ${URL}`]: () => ({ status: 500, body: { success: false, error: 'REST is down' } }) });
    render(<CatalogDriftPanel itemId="item-1" active requestedEventId={null} onCompare={jest.fn()} />);
    expect(await screen.findByText(/REST is down/)).toBeInTheDocument();
  });
});

describe('CatalogDriftAlertsDialog', () => {
  const URL = '/api/catalog/drift-notifications';

  it('loads, explains email is not sent yet, and saves', async () => {
    const calls = mockFetch({
      [`GET ${URL}`]: () => ({ body: { ...DEFAULT_DRIFT_SETTINGS, configured: false } }),
      [`PUT ${URL}`]: (init) => ({ body: { ...JSON.parse(String(init?.body)), configured: true } }),
    });
    const onOpenChange = jest.fn();
    render(<CatalogDriftAlertsDialog open onOpenChange={onOpenChange} />);
    expect(await screen.findByTestId('catalog-drift-alerts-summary')).toHaveTextContent(
      'Breaking and dangerous drift is announced right away; safe drift only shows a badge.',
    );
    expect(screen.getByTestId('catalog-drift-alerts-dialog')).toHaveTextContent('drift email is not sent yet');
    expect(screen.queryByTestId('catalog-drift-alerts-breaking-immediate')).toBeNull();
    expect(await axe(screen.getByTestId('catalog-drift-alerts-dialog'), AXE_OPTIONS)).toHaveNoViolations();

    fireEvent.click(screen.getByTestId('catalog-drift-alerts-safe'));
    fireEvent.click(screen.getByTestId('catalog-drift-alerts-save'));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(calls.at(-1)).toEqual({
      method: 'PUT',
      url: URL,
      body: { ...DEFAULT_DRIFT_SETTINGS, notifySafe: true },
    });
  });

  it('offers the breaking-right-away option only for the digest', async () => {
    mockFetch({ [`GET ${URL}`]: () => ({ body: { ...DEFAULT_DRIFT_SETTINGS, delivery: 'daily_digest' } }) });
    render(<CatalogDriftAlertsDialog open onOpenChange={jest.fn()} />);
    expect(await screen.findByTestId('catalog-drift-alerts-breaking-immediate')).toBeChecked();
  });

  it('keeps the dialog open on a refusal', async () => {
    mockFetch({
      [`GET ${URL}`]: () => ({ body: DEFAULT_DRIFT_SETTINGS }),
      [`PUT ${URL}`]: () => ({ status: 403, body: { success: false, error: 'Permission denied: imports:edit' } }),
    });
    const onOpenChange = jest.fn();
    render(<CatalogDriftAlertsDialog open onOpenChange={onOpenChange} />);
    await screen.findByTestId('catalog-drift-alerts-summary');
    fireEvent.click(screen.getByTestId('catalog-drift-alerts-save'));
    expect(await screen.findByTestId('catalog-drift-alerts-error')).toHaveTextContent('imports:edit');
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
