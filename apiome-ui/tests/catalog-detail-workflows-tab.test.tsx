/**
 * The catalog item detail page's Workflows tab — COA-1.3 (#7039), integration.
 *
 * Renders the real `CatalogItemDetailClient` with the transport mocked:
 *
 * - an **Arazzo** item lists **Workflows** after the other tabs, reads nothing until it is
 *   selected, then shows the workflows and their step graph with the count on the tab;
 * - `?tab=workflows` opens it directly, and a step opens its operation;
 * - an item of any other format has no Workflows tab, and `?tab=workflows` falls back to Overview.
 *
 * It also writes the docs-screenshot fixtures (`apiome-docs/screens.json`: `arazzo-workflows` and
 * `arazzo-workflow-graph`) from the whole page, into `e2e/fixtures/hive-catalog-item/` when
 * `CATALOG_ITEM_FIXTURE_DUMP=1` is set:
 *
 *     CATALOG_ITEM_FIXTURE_DUMP=1 npx jest tests/catalog-detail-workflows-tab.test.tsx -t fixtures
 */

import fs from 'node:fs';
import path from 'node:path';
import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockPush = jest.fn();
let searchParams = new URLSearchParams();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
  useSearchParams: () => searchParams,
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { current_tenant_id: 'tenant-1' } } }),
}));

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: (props: { value?: string }) => <textarea readOnly value={props.value ?? ''} />,
}));

import { CatalogItemDetailClient } from '../src/app/ade/dashboard/catalog/[id]/CatalogItemDetailClient';
import { resetFormatCapabilitiesCache } from '@/app/components/ade/dashboard/catalog/useFormatCapabilities';
import { liveMarkup } from './helpers/a11y-fixture-dump';
import { ITEM_ID, OPERATION_RESPONSE, OP_GET_CART, WORKFLOWS_RESPONSE } from './helpers/arazzo-workflows-fixture';

/** An imported Arazzo document. */
const ARAZZO_ITEM = {
  id: ITEM_ID,
  name: 'Checkout workflows',
  slug: 'checkout-workflows',
  description: 'Imported from checkout.arazzo.yaml.',
  enabled: true,
  deleted_at: null,
  created_at: '2026-06-01T00:00:00.000Z',
  updated_at: '2026-06-20T12:00:00.000Z',
  qualityScore: 88,
  qualityGrade: 'B',
  publishable: false,
  sourceFormat: 'arazzo',
  protocol: null,
  formatMetadata: { sourceLabel: 'checkout.arazzo.yaml', inputKind: 'file' },
  toolVersions: { arazzo: '1.1.0' },
  summary: { services: 2, operations: 4, types: 0, channels: 0 },
  source: { kind: 'file', label: 'checkout.arazzo.yaml', uri: null, hasContent: true, downloadable: true },
};

const originalFetch = global.fetch;
let fetchMock: jest.Mock;

/** Route every GET the detail shell can make for an item of `sourceFormat`. */
function mockTransport(sourceFormat = 'arazzo') {
  fetchMock = jest.fn(async (input: unknown) => {
    const url = String(input);
    const json = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' });
    if (url.startsWith('/api/workflows/catalog/')) return json({ success: true, workflows: WORKFLOWS_RESPONSE });
    if (url.startsWith('/api/workflows/operations/')) return json({ success: true, operation: OPERATION_RESPONSE });
    if (url.includes('/format-capabilities')) {
      return json({
        success: true,
        version: '1',
        review_date: '2026-07-28',
        analysis_schema_version: '1.1.0',
        absence_categories: [],
        absences: [],
        reason_absence_categories: {},
        formats: [],
      });
    }
    if (url.includes('/lint')) return json({ success: true, report: null });
    if (url.includes('/analysis')) return json({ success: true, record: null });
    return json({ success: true, item: { ...ARAZZO_ITEM, sourceFormat } });
  });
  global.fetch = fetchMock as unknown as typeof fetch;
}

/** Calls made to the workflow read. */
function workflowCalls(): unknown[] {
  return fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/workflows/catalog/'));
}

beforeEach(() => {
  searchParams = new URLSearchParams();
  resetFormatCapabilitiesCache();
});

afterEach(() => {
  global.fetch = originalFetch;
  jest.clearAllMocks();
});

describe('an Arazzo catalog item', () => {
  it('lists Workflows last and reads nothing until it is selected', async () => {
    mockTransport();
    render(<CatalogItemDetailClient itemId={ITEM_ID} />);
    const tab = await screen.findByTestId('catalog-detail-tab-workflows');
    const tabs = screen.getAllByRole('tab');
    expect(tabs.at(-1)).toBe(tab);
    expect(tab).toHaveAttribute('aria-selected', 'false');
    expect(workflowCalls()).toHaveLength(0);

    fireEvent.click(tab);
    expect(await screen.findByTestId('awf-panel')).toBeInTheDocument();
    expect(workflowCalls()).toEqual([[`/api/workflows/catalog/${ITEM_ID}`]]);
    expect(screen.getByTestId('awf-workflow-checkout')).toBeInTheDocument();
    expect(screen.getByTestId('awf-step-graph')).toBeInTheDocument();
    // The tab's count chip shows the two workflows once they have loaded.
    expect(tab).toHaveTextContent('2');
  });

  it('opens straight on ?tab=workflows, and a step opens its operation', async () => {
    searchParams = new URLSearchParams('tab=workflows');
    mockTransport();
    render(<CatalogItemDetailClient itemId={ITEM_ID} />);
    await screen.findByTestId('awf-panel');
    expect(screen.getByTestId('catalog-detail-tab-workflows')).toHaveAttribute('aria-selected', 'true');

    fireEvent.click(screen.getByTestId('awf-graph-node-load-cart'));
    const drawer = await screen.findByTestId('awf-step-drawer');
    expect(await within(drawer).findByTestId('awf-drawer-operation')).toHaveTextContent('/carts/{cartId}');
    expect(fetchMock).toHaveBeenCalledWith(`/api/workflows/operations/${OP_GET_CART}`);
  });
});

describe('any other catalog item', () => {
  it('has no Workflows tab, and ?tab=workflows falls back to Overview', async () => {
    searchParams = new URLSearchParams('tab=workflows');
    mockTransport('openapi');
    render(<CatalogItemDetailClient itemId={ITEM_ID} />);
    const overview = await screen.findByTestId('catalog-detail-tab-overview');
    expect(screen.queryByTestId('catalog-detail-tab-workflows')).not.toBeInTheDocument();
    expect(overview).toHaveAttribute('aria-selected', 'true');
    expect(workflowCalls()).toHaveLength(0);
  });
});

describe('the docs fixtures', () => {
  const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-catalog-item');

  /** Write one fixture, or just assert it could be. */
  const write = (name: string, html: string) => {
    expect(html.length).toBeGreaterThan(0);
    if (process.env.CATALOG_ITEM_FIXTURE_DUMP !== '1') return;
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, `${name}.html`), html);
  };

  it('writes the Workflows tab, and the step drawer open over it', async () => {
    searchParams = new URLSearchParams('tab=workflows');
    mockTransport();
    render(<CatalogItemDetailClient itemId={ITEM_ID} />);
    await screen.findByTestId('awf-panel');
    const page = () => document.querySelector('.page') as HTMLElement;
    write('tab-workflows', page().outerHTML);

    await act(async () => {
      fireEvent.click(screen.getByTestId('awf-step-load-cart'));
    });
    const drawer = await screen.findByTestId('awf-step-drawer');
    await within(drawer).findByTestId('awf-drawer-operation');
    // The page behind the drawer, then the drawer itself — the order the browser paints them.
    write('tab-workflows-step', `${page().outerHTML}\n${liveMarkup(drawer)}`);
  });
});
