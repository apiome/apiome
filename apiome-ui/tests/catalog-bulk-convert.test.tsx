/**
 * Bulk convert on the catalog list (MFI-28.5, #4121).
 *
 * The model (`catalogBulkConvertModel`) is pinned as pure rules — the queue, the low-tier gate,
 * the explicit apply-to-all, the outcome line and the per-item failure list — and the dialog is
 * driven end to end against a mocked `/api/catalog/{id}/convert`: every item is previewed with
 * the same dry-run the single-item dialog uses, a low-tier item blocks Convert until it is
 * acknowledged (individually or for all), commits run once per item, and each row reports its
 * own outcome so a partial failure names the item that failed.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

/** The single-item preview is its own screen; here it only has to open and report a convert. */
jest.mock('@/app/components/ade/dashboard/catalog/ConversionPreviewDialog', () => ({
  __esModule: true,
  ConversionPreviewDialog: ({
    open,
    itemName,
    onConverted,
    onOpenChange,
  }: {
    open: boolean;
    itemName: string;
    onConverted?: () => void;
    onOpenChange: (open: boolean) => void;
  }) =>
    open ? (
      <div data-testid="single-convert-preview">
        {itemName}
        <button
          type="button"
          onClick={() => {
            onConverted?.();
            onOpenChange(false);
          }}
        >
          Convert this one
        </button>
      </div>
    ) : null,
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { CatalogBulkConvertDialog } from '../src/app/components/ade/catalog/CatalogBulkConvertDialog';
import {
  bulkConvertAwaitingAck,
  bulkConvertFailures,
  bulkConvertGate,
  bulkConvertInitialRows,
  bulkConvertLowTierCount,
  bulkConvertNeedsAck,
  bulkConvertOffersApplyToAll,
  bulkConvertQueue,
  bulkConvertStatusLabel,
  bulkConvertSummary,
  type BulkConvertRow,
} from '../src/app/components/ade/catalog/catalogBulkConvertModel';
import type { CatalogItem } from '../src/app/components/ade/catalog/catalogModel';
import type { FidelityReport, FidelityTier } from '../src/app/utils/conversion-fidelity';

/** jsdom cannot compute colour; the region rule wants the app shell. */
const AXE_OPTIONS = {
  rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
} as const;

function report(
  tier: FidelityTier,
  grade = tier === 'high' ? 'A' : tier === 'medium' ? 'C' : 'F'
): FidelityReport {
  return {
    score: tier === 'high' ? 95 : tier === 'medium' ? 70 : 30,
    grade,
    tier,
    items: [],
    losses: [],
    coverage_counts: {},
    penalty: 0,
  };
}

function item(id: string, name: string): CatalogItem {
  return {
    id,
    name,
    slug: name.toLowerCase().replace(/\s+/g, '-'),
    enabled: true,
    deleted_at: null,
    sourceFormat: 'protobuf',
  } as unknown as CatalogItem;
}

const ORDERS = item('orders', 'orders.proto');
const BILLING = item('billing', 'billing.proto');
const EVENTS = item('events', 'events.yaml');

/** A previewed row of the given tier. */
function readyRow(
  base: CatalogItem,
  tier: FidelityTier,
  patch: Partial<BulkConvertRow> = {}
): BulkConvertRow {
  return { ...bulkConvertInitialRows([base])[0], status: 'ready', report: report(tier), ...patch };
}

// ---------------------------------------------------------------------------------------
// The model
// ---------------------------------------------------------------------------------------

describe('catalogBulkConvertModel', () => {
  it('starts every item included and previewing', () => {
    const rows = bulkConvertInitialRows([ORDERS, BILLING]);
    expect(rows.map((row) => [row.id, row.status, row.included, row.acknowledged])).toEqual([
      ['orders', 'previewing', true, false],
      ['billing', 'previewing', true, false],
    ]);
  });

  it('asks for an acknowledgement on a low-tier row only, as the single-item dialog does', () => {
    expect(bulkConvertNeedsAck(readyRow(ORDERS, 'low'))).toBe(true);
    expect(bulkConvertNeedsAck(readyRow(ORDERS, 'medium'))).toBe(false);
    expect(bulkConvertNeedsAck(readyRow(ORDERS, 'high'))).toBe(false);
    expect(bulkConvertNeedsAck(bulkConvertInitialRows([ORDERS])[0])).toBe(false);
  });

  it('holds Convert while anything is still previewing', () => {
    const rows = [readyRow(ORDERS, 'high'), bulkConvertInitialRows([BILLING])[0]];
    expect(bulkConvertGate(rows, false, false).canConvert).toBe(false);
  });

  it('blocks Convert until every included low-tier row is acknowledged — never skips it', () => {
    const rows = [readyRow(ORDERS, 'high'), readyRow(BILLING, 'low')];
    const gate = bulkConvertGate(rows, false, false);
    expect(gate.canConvert).toBe(false);
    expect(gate.reason).toMatch(/Acknowledge the low-fidelity warning for 1 item/);
    expect(bulkConvertAwaitingAck(rows, false).map((row) => row.id)).toEqual(['billing']);
    expect(bulkConvertQueue(rows, false).map((row) => row.id)).toEqual(['orders']);
  });

  it('accepts a per-row acknowledgement', () => {
    const rows = [readyRow(ORDERS, 'high'), readyRow(BILLING, 'low', { acknowledged: true })];
    expect(bulkConvertGate(rows, false, false).canConvert).toBe(true);
    expect(bulkConvertQueue(rows, false).map((row) => row.id)).toEqual(['orders', 'billing']);
  });

  it('accepts the explicit apply-to-all gate in place of every per-row acknowledgement', () => {
    const rows = [readyRow(ORDERS, 'low'), readyRow(BILLING, 'low')];
    expect(bulkConvertLowTierCount(rows)).toBe(2);
    expect(bulkConvertGate(rows, true, false).canConvert).toBe(true);
    expect(bulkConvertQueue(rows, true)).toHaveLength(2);
  });

  it('offers apply-to-all for two or more low-tier items only', () => {
    expect(bulkConvertOffersApplyToAll([readyRow(ORDERS, 'low'), readyRow(BILLING, 'high')])).toBe(
      false
    );
    expect(bulkConvertOffersApplyToAll([readyRow(ORDERS, 'low'), readyRow(BILLING, 'low')])).toBe(
      true
    );
    expect(
      bulkConvertOffersApplyToAll([
        readyRow(ORDERS, 'low'),
        readyRow(BILLING, 'low', { included: false }),
      ])
    ).toBe(false);
  });

  it('lets an unticked low-tier row out of the gate', () => {
    const rows = [readyRow(ORDERS, 'high'), readyRow(BILLING, 'low', { included: false })];
    expect(bulkConvertGate(rows, false, false).canConvert).toBe(true);
    expect(bulkConvertLowTierCount(rows)).toBe(0);
    expect(bulkConvertStatusLabel(rows[1])).toBe('Skipped');
  });

  it('never queues a row whose preview failed, or one already converted', () => {
    const rows = [
      {
        ...bulkConvertInitialRows([ORDERS])[0],
        status: 'preview-failed' as const,
        error: 'Unsupported',
      },
      readyRow(BILLING, 'high', { status: 'converted' }),
    ];
    expect(bulkConvertQueue(rows, true)).toEqual([]);
    expect(bulkConvertGate(rows, true, false)).toEqual({
      canConvert: false,
      reason: 'Nothing left to convert.',
    });
  });

  it('retries a row whose commit failed', () => {
    const rows = [readyRow(ORDERS, 'high', { status: 'failed', error: 'Timeout' })];
    expect(bulkConvertQueue(rows, false).map((row) => row.id)).toEqual(['orders']);
  });

  it('is closed while a run is in flight', () => {
    expect(bulkConvertGate([readyRow(ORDERS, 'high')], false, true).canConvert).toBe(false);
  });

  it('states the split once a run has finished', () => {
    expect(bulkConvertSummary([readyRow(ORDERS, 'high')])).toBeNull();
    expect(
      bulkConvertSummary([
        readyRow(ORDERS, 'high', { status: 'converted' }),
        readyRow(BILLING, 'high', { status: 'converted' }),
      ])
    ).toBe('Converted 2 catalog items.');
    expect(
      bulkConvertSummary([
        readyRow(ORDERS, 'high', { status: 'converted' }),
        readyRow(BILLING, 'high', { status: 'failed', error: 'Gone' }),
      ])
    ).toBe('Converted 1 of 2 catalog items · 1 failed');
  });

  it('lists every failure with its own reason', () => {
    const rows = [
      readyRow(ORDERS, 'high', { status: 'converted' }),
      readyRow(BILLING, 'high', { status: 'failed', error: 'Quota exceeded' }),
      {
        ...bulkConvertInitialRows([EVENTS])[0],
        status: 'preview-failed' as const,
        error: 'Unsupported',
      },
    ];
    expect(bulkConvertFailures(rows)).toEqual([
      { id: 'billing', name: 'billing.proto', reason: 'Quota exceeded' },
      { id: 'events', name: 'events.yaml', reason: 'Unsupported' },
    ]);
  });
});

// ---------------------------------------------------------------------------------------
// The dialog
// ---------------------------------------------------------------------------------------

type Plan = Record<string, { tier?: FidelityTier; previewError?: string; commitError?: string }>;

/** Serve `/api/catalog/{id}/convert`: a dry-run per the plan's tier, a commit per its outcome. */
function mockConvert(plan: Plan) {
  const commits: string[] = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const id = decodeURIComponent(url.split('/')[3]);
    const entry = plan[id] ?? {};
    const body = JSON.parse(String(init?.body ?? '{}')) as { dryRun?: boolean };
    if (body.dryRun) {
      if (entry.previewError) {
        return {
          ok: false,
          status: 422,
          json: async () => ({ success: false, error: entry.previewError }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ success: true, report: report(entry.tier ?? 'high'), openapi: {} }),
      };
    }
    commits.push(id);
    if (entry.commitError) {
      return {
        ok: false,
        status: 500,
        json: async () => ({ success: false, error: entry.commitError }),
      };
    }
    return { ok: true, status: 200, json: async () => ({ success: true, projectId: `p-${id}` }) };
  }) as unknown as typeof fetch;
  return commits;
}

function renderDialog(items: CatalogItem[]) {
  const onOpenChange = jest.fn();
  const onFinished = jest.fn();
  render(
    <CatalogBulkConvertDialog
      open
      items={items}
      onOpenChange={onOpenChange}
      onFinished={onFinished}
    />
  );
  return { onOpenChange, onFinished };
}

const row = (id: string) => screen.getByTestId(`catalog-bulk-convert-row-${id}`);
const submit = () => screen.getByTestId('catalog-bulk-convert-submit');

/** Wait until no row is still previewing. */
async function previewed() {
  await waitFor(() => expect(screen.queryAllByText('Previewing…')).toHaveLength(0));
}

describe('CatalogBulkConvertDialog', () => {
  afterEach(() => jest.restoreAllMocks());

  it('previews every item with the dry-run before anything can be converted', async () => {
    mockConvert({ orders: { tier: 'high' }, billing: { tier: 'medium' } });
    renderDialog([ORDERS, BILLING]);
    expect(screen.getByText('Convert 2 catalog items to OpenAPI')).toBeInTheDocument();
    await previewed();
    expect(within(row('orders')).getByText('high fidelity')).toBeInTheDocument();
    expect(within(row('billing')).getByText('medium fidelity')).toBeInTheDocument();
    const calls = (global.fetch as jest.Mock).mock.calls.map(([url]) => String(url));
    expect(calls).toEqual([
      '/api/catalog/orders/convert?dryRun=true',
      '/api/catalog/billing/convert?dryRun=true',
    ]);
    expect(submit()).toBeEnabled();
  });

  it('gates a low-tier item behind its own acknowledgement', async () => {
    const commits = mockConvert({ orders: { tier: 'high' }, billing: { tier: 'low' } });
    renderDialog([ORDERS, BILLING]);
    await previewed();
    expect(submit()).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent(/Acknowledge the low-fidelity warning/);

    fireEvent.click(screen.getByTestId('catalog-bulk-convert-ack-billing'));
    expect(submit()).toBeEnabled();
    fireEvent.click(submit());
    await waitFor(() => expect(commits).toEqual(['orders', 'billing']));
  });

  it('offers one explicit "apply the fidelity warning to all" gate', async () => {
    const commits = mockConvert({ orders: { tier: 'low' }, billing: { tier: 'low' } });
    renderDialog([ORDERS, BILLING]);
    await previewed();
    const applyAll = screen.getByTestId('catalog-bulk-convert-apply-all');
    expect(applyAll.closest('label')).toHaveTextContent(
      'Apply the fidelity warning to all 2 low-fidelity items'
    );
    fireEvent.click(applyAll);
    // The per-row acknowledgements are folded into the one gate.
    expect(screen.queryByTestId('catalog-bulk-convert-ack-orders')).not.toBeInTheDocument();
    fireEvent.click(submit());
    await waitFor(() => expect(commits).toEqual(['orders', 'billing']));
  });

  it('drops the apply-to-all gate — and its effect — once fewer than two items need it', async () => {
    mockConvert({ orders: { tier: 'low' }, billing: { tier: 'low' } });
    renderDialog([ORDERS, BILLING]);
    await previewed();
    fireEvent.click(screen.getByTestId('catalog-bulk-convert-apply-all'));
    expect(submit()).toBeEnabled();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include billing.proto' }));
    expect(screen.queryByTestId('catalog-bulk-convert-apply-all')).not.toBeInTheDocument();
    // The hidden gate no longer counts: orders needs its own acknowledgement again.
    expect(submit()).toBeDisabled();
    expect(screen.getByTestId('catalog-bulk-convert-ack-orders')).toBeInTheDocument();
  });

  it('leaves an unticked item out of the run', async () => {
    const commits = mockConvert({ orders: { tier: 'high' }, billing: { tier: 'high' } });
    renderDialog([ORDERS, BILLING]);
    await previewed();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include billing.proto' }));
    fireEvent.click(submit());
    await waitFor(() => expect(commits).toEqual(['orders']));
    expect(within(row('billing')).getByText('Skipped')).toBeInTheDocument();
  });

  it('reports a partial failure per item, and lets the failed one be retried', async () => {
    const plan: Plan = {
      orders: { tier: 'high' },
      billing: { tier: 'high', commitError: 'Quota exceeded' },
      events: { previewError: 'This format cannot be converted yet' },
    };
    const commits = mockConvert(plan);
    const { onFinished, onOpenChange } = renderDialog([ORDERS, BILLING, EVENTS]);
    await previewed();
    expect(within(row('events')).getByText('Preview failed')).toBeInTheDocument();
    expect(within(row('events')).getByRole('alert')).toHaveTextContent(
      'This format cannot be converted yet'
    );

    fireEvent.click(submit());
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(
        'Converted 1 of 2 catalog items · 1 failed'
      )
    );
    expect(commits).toEqual(['orders', 'billing']);
    expect(within(row('orders')).getByText('Converted')).toBeInTheDocument();
    expect(within(row('orders')).getByRole('link', { name: 'Open project' })).toHaveAttribute(
      'href',
      '/ade/dashboard/versions?projectId=p-orders'
    );
    expect(within(row('billing')).getByText('Failed')).toBeInTheDocument();
    expect(within(row('billing')).getByRole('alert')).toHaveTextContent('Quota exceeded');

    // Retry: only the failed row is queued again.
    plan.billing.commitError = undefined;
    expect(submit()).toHaveTextContent('Convert 1');
    fireEvent.click(submit());
    await waitFor(() => expect(within(row('billing')).getByText('Converted')).toBeInTheDocument());
    expect(commits).toEqual(['orders', 'billing', 'billing']);

    fireEvent.click(screen.getByTestId('catalog-bulk-convert-close'));
    expect(onFinished).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('opens the full single-item preview from Review…, and records its conversion', async () => {
    mockConvert({ orders: { tier: 'low' } });
    renderDialog([ORDERS]);
    await previewed();
    fireEvent.click(screen.getByTestId('catalog-bulk-convert-review-orders'));
    expect(await screen.findByTestId('single-convert-preview')).toHaveTextContent('orders.proto');
    fireEvent.click(screen.getByRole('button', { name: 'Convert this one' }));
    await waitFor(() => expect(within(row('orders')).getByText('Converted')).toBeInTheDocument());
  });

  it('does not tell the list to reload when nothing was converted', async () => {
    mockConvert({ orders: { tier: 'high' } });
    const { onFinished, onOpenChange } = renderDialog([ORDERS]);
    await previewed();
    fireEvent.click(screen.getByTestId('catalog-bulk-convert-close'));
    expect(onFinished).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('passes axe with a low-tier row waiting on its acknowledgement', async () => {
    mockConvert({ orders: { tier: 'high' }, billing: { tier: 'low' } });
    renderDialog([ORDERS, BILLING]);
    await previewed();
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
  });
});
