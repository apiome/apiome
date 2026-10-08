/**
 * The documentation site's Tools pages — Data browser and Migrations (DOCS-1.10, #5627).
 *
 * `apiome-docs/docs/admin/data-browser.mdx` and `migrations.mdx` show these two legacy
 * surfaces, captured from the dumps this suite writes into `e2e/fixtures/hive-a11y/`:
 *
 *     A11Y_FIXTURE_DUMP=1 npx jest tests/docs-admin-tools.test.tsx
 *
 * Each test renders the real route — its layout (rail, toolbar, sidebar) and page — against
 * mocked endpoints and realistic data, drives it the way a reader would (pick a project, a
 * table, a record), asserts the content the docs describe, and dumps the result. Without the
 * environment variable the dumps are skipped but every assertion still runs, so a change that
 * would make the pages wrong fails here.
 *
 * Only what jsdom cannot provide is stubbed: Monaco (a `<pre>` holding the same JSON), the
 * session and tenant plumbing the rail reads, as in `tests/ade-tools-shell.test.tsx`, and — for
 * the migration Designer — the element sizes React Flow measures before it draws a node
 * ({@link stubCanvasGeometry}). The canvas itself, its nodes and edges are the real ones.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

jest.mock('../src/app/globals.css', () => ({}), { virtual: true });

const mockUsePathname = jest.fn<string, []>();

jest.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
  useRouter: () => ({ refresh: jest.fn(), push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

// Monaco loads through `next/dynamic` and needs a real browser. The docs show its content, so
// the stand-in renders the same JSON as a code block.
jest.mock('next/dynamic', () => ({
  __esModule: true,
  default: () =>
    function MonacoStandIn({ value }: { value?: string }) {
      return (
        <pre data-testid="monaco-stand-in" className="h-full overflow-auto p-3 font-mono text-xs bg-gray-900 text-gray-100">
          {value}
        </pre>
      );
    },
}));

jest.mock('@lib/auth/session-client', () => ({
  AuthSessionProvider: ({ children }: { children: unknown }) => children,
  signOut: jest.fn(),
  useAuthSession: () => ({
    data: {
      user: {
        user_id: 'u-priya',
        name: 'Priya Raman',
        email: 'priya.raman@northwind.io',
        current_tenant_id: 't-northwind',
      },
    },
  }),
}));

jest.mock('@lib/db/commercial-access', () => ({
  getCommercialAccessForSession: jest.fn(async () => ({ navItems: [] })),
}));

jest.mock('@lib/auth/tenant-membership-context', () => ({
  loadTenantMembershipContext: jest.fn(async () => ({
    tenants: [{ id: 't-northwind', name: 'Northwind', role: 'admin' }],
    adminTenantIds: ['t-northwind'],
    createTenant: null,
  })),
}));

jest.mock('@lib/auth/sign-out-client', () => ({ signOutEverywhere: jest.fn() }));

jest.mock('@lib/auth/last-active-tenant-actions', () => ({
  persistLastActiveTenant: jest.fn(async () => undefined),
}));

jest.mock('@/app/components/ade/CreateTenantDialog', () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock('next-themes', () => ({ useTheme: () => ({ setTheme: jest.fn() }) }));

const mockConfirm = jest.fn(async () => false);
jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({ confirm: mockConfirm, alert: jest.fn(async () => undefined) }),
}));

import DatabaseLayout from '../src/app/ade/database/layout';
import DatabasePage from '../src/app/ade/database/page';
import { useDatabase } from '../src/app/ade/database/DatabaseContext';
import MigrationLayout from '../src/app/ade/migration/layout';
import MigrationPage from '../src/app/ade/migration/page';
import { useMigration } from '../src/app/ade/migration/MigrationContext';
import MigrationRuleDialog from '../src/app/ade/migration/components/MigrationRuleDialog';

// ---------------------------------------------------------------------------------------
// Data — the Northwind Payments API, at 2.3.0 and 2.4.0
// ---------------------------------------------------------------------------------------

const PROJECT = { id: 'p-payments', name: 'Payments API', slug: 'payments-api' };

const VERSIONS = [
  { id: 'v-240', version_id: '2.4.0', shortMessage: 'Customer tiers renamed', published: true, created_at: '2026-09-28T10:00:00Z' },
  { id: 'v-230', version_id: '2.3.0', shortMessage: 'Postal addresses', published: true, created_at: '2026-08-14T10:00:00Z' },
  { id: 'v-220', version_id: '2.2.0', shortMessage: 'Refund states', published: true, created_at: '2026-06-02T10:00:00Z' },
];

/** The `Customer` class as 2.3.0 published it. */
const CUSTOMER_230 = {
  type: 'object',
  required: ['customerId', 'fullName', 'email'],
  properties: {
    customerId: { type: 'string', format: 'uuid' },
    fullName: { type: 'string' },
    email: { type: 'string', format: 'email' },
    tier: { type: 'string', enum: ['standard', 'gold', 'platinum'] },
  },
};

/** The `Customer` class as 2.4.0 published it: tiers renamed, a postal code and an opt-in added. */
const CUSTOMER_240 = {
  type: 'object',
  required: ['customerId', 'fullName', 'email'],
  properties: {
    customerId: { type: 'string', format: 'uuid' },
    fullName: { type: 'string' },
    email: { type: 'string', format: 'email' },
    tier: { type: 'string', enum: ['basic', 'plus', 'premium'] },
    postalCode: { type: 'string' },
    marketingOptIn: { type: 'boolean' },
  },
};

/** How 2.4.0 renamed the tiers. */
const TIER_NAMES: Record<string, string> = { standard: 'basic', gold: 'plus', platinum: 'premium' };

const INVOICE = {
  type: 'object',
  properties: {
    invoiceId: { type: 'string' },
    customerId: { type: 'string', format: 'uuid' },
    amount: { type: 'number' },
    currency: { type: 'string' },
    status: { type: 'string', enum: ['draft', 'open', 'paid', 'void'] },
  },
};

const PAYMENT = {
  type: 'object',
  properties: {
    paymentId: { type: 'string' },
    invoiceId: { type: 'string' },
    amount: { type: 'number' },
    method: { type: 'string', enum: ['card', 'ach', 'wire'] },
  },
};

const REFUND = { type: 'object', properties: { refundId: { type: 'string' }, paymentId: { type: 'string' }, amount: { type: 'number' } } };

/** Tables (published class schemas) per version id. */
const TABLES: Record<string, Array<{ class_schema_id: string; class_id: string; class_name: string; schema: Record<string, unknown> }>> = {
  'v-240': [
    { class_schema_id: 'cs-customer-240', class_id: 'c-customer', class_name: 'Customer', schema: CUSTOMER_240 },
    { class_schema_id: 'cs-invoice-240', class_id: 'c-invoice', class_name: 'Invoice', schema: INVOICE },
    { class_schema_id: 'cs-payment-240', class_id: 'c-payment', class_name: 'Payment', schema: PAYMENT },
    { class_schema_id: 'cs-refund-240', class_id: 'c-refund', class_name: 'Refund', schema: REFUND },
  ],
  'v-230': [
    { class_schema_id: 'cs-customer-230', class_id: 'c-customer', class_name: 'Customer', schema: CUSTOMER_230 },
    { class_schema_id: 'cs-invoice-230', class_id: 'c-invoice', class_name: 'Invoice', schema: INVOICE },
    { class_schema_id: 'cs-payment-230', class_id: 'c-payment', class_name: 'Payment', schema: PAYMENT },
    { class_schema_id: 'cs-refund-230', class_id: 'c-refund', class_name: 'Refund', schema: REFUND },
  ],
};

const COUNTS: Record<string, number> = {
  'cs-customer-240': 5,
  'cs-invoice-240': 128,
  'cs-payment-240': 117,
  'cs-refund-240': 9,
  'cs-customer-230': 6,
};

/** Customer records under 2.4.0, newest first; one deleted. */
const CUSTOMERS_240 = [
  ['0193a8e2-7c41-7d0e-9b2a-41f0c2d9e811', { fullName: 'Elena Vasquez', email: 'elena.vasquez@northwind.io', tier: 'plus', postalCode: '94107', marketingOptIn: true }, 4, 'updated', '2026-10-06T15:22:00Z'],
  ['0193a8e2-6b30-7c1f-8a19-30e1b1c8d702', { fullName: 'Sam Okafor', email: 'sam.okafor@northwind.io', tier: 'premium', postalCode: '10013', marketingOptIn: false }, 2, 'updated', '2026-10-05T09:41:00Z'],
  ['0193a8e2-5a2f-7b2e-97f8-2fd0a0b7c6f3', { fullName: 'Tomas Berg', email: 'tomas.berg@northwind.io', tier: 'basic', postalCode: '60607', marketingOptIn: false }, 1, 'created', '2026-10-03T13:05:00Z'],
  ['0193a8e2-491e-7a3d-86e7-1ec09fa6b5e4', { fullName: 'Marcus Lee', email: 'marcus.lee@northwind.io', tier: 'plus', postalCode: '98101', marketingOptIn: true }, 3, 'updated', '2026-09-30T08:17:00Z'],
  ['0193a8e2-380d-794c-75d6-0dbf8e95a4d5', { fullName: 'Priya Raman', email: 'priya.raman@northwind.io', tier: 'premium', postalCode: '02139', marketingOptIn: true }, 1, 'created', '2026-09-29T11:48:00Z'],
  ['0193a8e2-27fc-785b-64c5-fcae7d8493c6', { fullName: 'Jules Bennett', email: 'jules.bennett@partner.dev', tier: 'basic', postalCode: '73301', marketingOptIn: false }, 5, 'deleted', '2026-09-24T16:30:00Z'],
].map(([id, data, seq, action, at]) => ({
  record_id: id as string,
  data: { customerId: id as string, ...(data as Record<string, unknown>) },
  record_sequence: seq as number,
  last_action: action as string,
  created_at: '2026-09-20T10:00:00Z',
  updated_at: at as string,
}));

/** The same customers as 2.3.0 stored them: old tier names, emails as they were typed. */
const CUSTOMERS_230 = CUSTOMERS_240.filter((row) => row.last_action !== 'deleted').map((row) => {
  const { fullName, email, tier, customerId } = row.data as Record<string, string>;
  const oldTier = Object.keys(TIER_NAMES).find((name) => TIER_NAMES[name] === tier) ?? tier;
  const typed = email.replace(/^(\w)(\w*)\.(\w)/, (_m, a: string, b: string, c: string) => `${a.toUpperCase()}${b}.${c.toUpperCase()}`);
  return { ...row, data: { customerId, fullName, email: typed, tier: oldTier } };
});

/**
 * The 2.3.0 → 2.4.0 plan for `Customer`: two rules, each started from the passthrough line of a
 * property both versions have (the only place the canvas offers one).
 */
const CUSTOMER_RULES = {
  'migration-edge-prop-email': {
    name: 'Normalize email',
    inputProperties: ['email'],
    ruleType: 'simple',
    ruleContent: 'String(email).trim().toLowerCase()',
    outputProperties: ['email'],
  },
  'migration-edge-prop-tier': {
    name: 'Rename tiers',
    inputProperties: ['tier'],
    ruleType: 'simple',
    ruleContent: '({ standard: "basic", gold: "plus", platinum: "premium" })[tier] ?? tier',
    outputProperties: ['tier'],
  },
};

const TEMPLATES = [
  ['Pass through', 'Copy value as-is; normalize null/empty to empty string.', 'General', 'simple', 'value == null || value === "" ? "" : String(value)', 1, 1],
  ['Split string', 'Split one value into two outputs by a delimiter.', 'String', 'simple', '[value.split("-")[0] || "", value.split("-")[1] || ""]', 1, 2],
  ['Concatenate', 'Join two or more inputs into one output with a separator.', 'String', 'simple', '[a, b].join(" ")', 2, 1],
  ['Trim whitespace', 'Trim leading and trailing whitespace from the input.', 'String', 'simple', 'String(value).trim()', 1, 1],
].map(([name, description, category, ruleType, content, minIn, minOut], i) => ({
  id: `tpl-${i}`,
  name,
  description,
  category,
  rule_type: ruleType,
  rule_content: content,
  min_inputs: minIn,
  min_outputs: minOut,
  input_labels: ['value'],
  sort_order: i * 10,
}));

// ---------------------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------------------

/** A JSON `Response`-like object for the fetch mock. */
const json = (body: unknown) => ({ ok: true, status: 200, json: async () => body });

/**
 * The endpoints both tools read, answered from the data above.
 *
 * @param input The request URL.
 * @param init The request options.
 * @returns The mocked response.
 */
async function fakeFetch(input: RequestInfo | URL, init?: RequestInit) {
  const url = new URL(String(input), 'http://localhost');
  const path = url.pathname;
  const q = url.searchParams;
  if (path === '/api/projects') return json({ success: true, projects: [PROJECT] });
  if (path === '/api/versions') return json({ success: true, versions: VERSIONS });
  const tables = /^\/api\/database\/versions\/([^/]+)\/tables$/.exec(path);
  if (tables) return json({ success: true, tables: TABLES[tables[1]] ?? [] });
  if (path === '/api/database/snapshot/counts') {
    const ids = (q.get('classSchemaIds') ?? '').split(',');
    return json({ success: true, counts: Object.fromEntries(ids.map((id) => [id, COUNTS[id] ?? 0])) });
  }
  if (path === '/api/database/snapshot/count') {
    const id = q.get('classSchemaId') ?? '';
    // The deleted customer is counted only when deleted records are shown.
    const deleted = id === 'cs-customer-240' && q.get('includeDeleted') === 'true' ? 1 : 0;
    return json({ success: true, count: (COUNTS[id] ?? 0) + deleted });
  }
  if (path === '/api/database/snapshot') {
    const id = q.get('classSchemaId');
    const rows = id === 'cs-customer-230' ? CUSTOMERS_230 : CUSTOMERS_240;
    const shown = q.get('includeDeleted') === 'true' ? rows : rows.filter((row) => row.last_action !== 'deleted');
    return json({ success: true, rows: shown, total: shown.length, page: 1 });
  }
  if (path === '/api/database/schema') {
    const id = q.get('classSchemaId') ?? '';
    const row = Object.values(TABLES).flat().find((t) => t.class_schema_id === id);
    return json({ success: true, schema: row?.schema ?? {} });
  }
  if (path === '/api/migration-plans/counts') return json({ success: true, counts: { Customer: 2 } });
  if (path === '/api/migration-plans/evaluate') {
    const { recordData } = JSON.parse(String(init?.body)) as { recordData: Record<string, string> };
    return json({
      success: true,
      transformedData: { ...recordData, email: recordData.email.trim().toLowerCase(), tier: TIER_NAMES[recordData.tier] ?? recordData.tier },
      rulesAppliedCount: 2,
    });
  }
  if (path === '/api/migration-plans') {
    return json({ success: true, rules: q.get('className') === 'Customer' ? CUSTOMER_RULES : {} });
  }
  if (path === '/api/migration-rule-templates') return json({ success: true, templates: TEMPLATES });
  return json({ success: false, error: `unmocked ${path}` });
}

/** Install the `matchMedia` jsdom lacks; the rail asks it whether it is icon-only. */
function mockMatchMedia(): void {
  window.matchMedia = ((query: string) => ({
    media: query,
    matches: false,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    addListener: jest.fn(),
    removeListener: jest.fn(),
    dispatchEvent: jest.fn(),
    onchange: null,
  })) as unknown as typeof window.matchMedia;
}

/**
 * Dates in the dumps read the same wherever the suite runs: both tools format with
 * `toLocaleString(undefined, …)`, which follows the machine's time zone, so it is pinned to UTC —
 * the zone of the screenshot pipeline's fixed clock. Jest's sandbox ignores `process.env.TZ`.
 */
const originalToLocaleString = Date.prototype.toLocaleString;
beforeAll(() => {
  Date.prototype.toLocaleString = function toLocaleStringUtc(this: Date, locales?: Intl.LocalesArgument, options?: Intl.DateTimeFormatOptions) {
    return originalToLocaleString.call(this, locales ?? 'en-US', { timeZone: 'UTC', ...options });
  };
});
afterAll(() => {
  Date.prototype.toLocaleString = originalToLocaleString;
});

beforeEach(() => {
  jest.clearAllMocks();
  mockMatchMedia();
  window.localStorage.clear();
  global.fetch = jest.fn(fakeFetch) as unknown as typeof fetch;
});

/**
 * React Flow's own stylesheet, which the migration route imports (`MigrationCanvas.tsx`).
 *
 * Fixtures are mounted into `/login`, whose bundle does not carry it, so the Designer's dump
 * brings it along; without it nodes are not positioned and edges are not drawn.
 */
const REACT_FLOW_CSS = readFileSync(
  // Read by path: `require.resolve` would answer with Jest's stub for plain `.css` imports.
  join(dirname(require.resolve('@xyflow/react/package.json')), 'dist', 'style.css'),
  'utf8'
);

/** Everything rendered — the route, and any dialog portalled over it — without the `<body>`. */
const bodyMarkup = () => liveMarkup(document.body).replace(/^<body[^>]*>|<\/body>$/g, '');

/**
 * Picks the project the way the toolbar's select would, from inside the tool's provider.
 *
 * Radix Select needs pointer events jsdom does not have, so the reader's first click is made
 * through the context the select writes to; the toolbar then loads the versions as it does live.
 */
function PickDatabaseProject() {
  const { setSelectedProjectId } = useDatabase();
  React.useEffect(() => setSelectedProjectId(PROJECT.id), [setSelectedProjectId]);
  return null;
}

/** As {@link PickDatabaseProject}, for the migration tool: a project and a 2.3.0 → 2.4.0 pair. */
function PickMigrationPair() {
  const { setSelectedProjectId, setFromVersionId, setToVersionId } = useMigration();
  React.useEffect(() => {
    setSelectedProjectId(PROJECT.id);
    setFromVersionId('v-230');
    setToVersionId('v-240');
  }, [setSelectedProjectId, setFromVersionId, setToVersionId]);
  return null;
}

// ---------------------------------------------------------------------------------------
// Data browser
// ---------------------------------------------------------------------------------------

describe('the data browser docs fixtures', () => {
  /** Render `/ade/database` with Payments API picked and the Customer table open. */
  async function openCustomers() {
    mockUsePathname.mockReturnValue('/ade/database');
    render(
      <DatabaseLayout>
        <PickDatabaseProject />
        <DatabasePage />
      </DatabaseLayout>
    );
    await screen.findByText('Latest Version');
    const sidebar = await screen.findByText('4 tables · 259 rows');
    expect(sidebar).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^Customer\b/ }));
    await screen.findByText('5 records');
    await screen.findByText('0193a8e2-7c41-7d0e-9b2a-41f0c2d9e811');
  }

  it('shows a table’s records, a record, and the insert form', async () => {
    await openCustomers();
    expect(screen.getByRole('button', { name: /View all records/ })).toBeInTheDocument();
    expect(screen.getByText('Show deleted')).toBeInTheDocument();
    writeA11yFixture('data-browser', bodyMarkup());

    // Deleted records come back with the switch, with Restore in place of Edit / Delete.
    fireEvent.click(screen.getByRole('switch'));
    await screen.findByText('6 records');
    expect(screen.getByRole('button', { name: /Restore/ })).toBeInTheDocument();
    writeA11yFixture('data-browser-deleted', bodyMarkup());
    fireEvent.click(screen.getByRole('switch'));
    await screen.findByText('5 records');

    const firstRow = screen.getByText('0193a8e2-7c41-7d0e-9b2a-41f0c2d9e811').closest('tr') as HTMLElement;
    fireEvent.click(within(firstRow).getByRole('button', { name: /View/ }));
    const record = await screen.findByRole('dialog');
    expect(record).toHaveTextContent('Record — 0193a8e2-7c41-7d0e-9b2a-41f0c2d9e811');
    expect(within(record).getByTestId('monaco-stand-in')).toHaveTextContent('"fullName": "Elena Vasquez"');
    writeA11yFixture('data-browser-record', bodyMarkup());
    fireEvent.keyDown(record, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /Insert/ }));
    const insert = await screen.findByRole('dialog');
    await waitFor(() => expect(insert.querySelector('#field-fullName')).not.toBeNull());
    expect(insert).toHaveTextContent('Insert record');
    const field = (name: string) => insert.querySelector(`#field-${name}`) as HTMLInputElement;
    fireEvent.change(field('customerId'), { target: { value: '0193a8e2-8d52-7e1f-ac3b-52a1d3eaf920' } });
    fireEvent.change(field('fullName'), { target: { value: 'Noor Haddad' } });
    fireEvent.change(field('email'), { target: { value: 'noor.haddad@northwind.io' } });
    writeA11yFixture('data-browser-insert', bodyMarkup());
  });

  it('opens a table’s JSON Schema from the sidebar', async () => {
    await openCustomers();
    fireEvent.click(screen.getByRole('button', { name: 'View JSON Schema for Customer' }));
    const schema = await screen.findByRole('dialog');
    expect(schema).toHaveTextContent('JSON Schema — Customer');
    await waitFor(() => expect(within(schema).getByTestId('monaco-stand-in')).toHaveTextContent('"postalCode"'));
    writeA11yFixture('data-browser-schema', bodyMarkup());
  });

  it('says to pick a project before anything else', async () => {
    mockUsePathname.mockReturnValue('/ade/database');
    render(
      <DatabaseLayout>
        <DatabasePage />
      </DatabaseLayout>
    );
    expect(await screen.findByText('No Project Selected')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// Canvas geometry — what a browser's layout would report to React Flow
// ---------------------------------------------------------------------------------------

/** Size of the Designer canvas at the capture's 1440 × 900 viewport. */
const CANVAS = { width: 896, height: 470 };
/** A class node as the browser lays it out: a 44px header, then one 24.5px row per property. */
const CLASS_NODE = { width: 210, header: 44, row: 24.5, foot: 10 };
/** A rule node: one compact card. */
const RULE_NODE = { width: 128, height: 24 };
/** A connection handle's box. */
const HANDLE = 9;

/**
 * Give React Flow the sizes jsdom cannot lay out, so the Designer draws its real nodes and edges.
 *
 * React Flow hides a node until a `ResizeObserver` reports it and its `offsetWidth` /
 * `offsetHeight` are non-zero, then places each edge from its handles' bounding rectangles.
 * jsdom reports zero for all of these and its observer never fires, so the canvas would be
 * empty. This answers them from the node's own content — sizes measured from the captured page:
 * rows per property, handles centred on their row (or at the `top` percentage a rule node sets),
 * on the side their position names.
 *
 * @returns A function restoring every patched property.
 */
function stubCanvasGeometry(): () => void {
  const proto = HTMLElement.prototype;
  const originals = {
    width: Object.getOwnPropertyDescriptor(proto, 'offsetWidth'),
    height: Object.getOwnPropertyDescriptor(proto, 'offsetHeight'),
    rect: proto.getBoundingClientRect,
    observer: globalThis.ResizeObserver,
    matrix: (window as unknown as { DOMMatrixReadOnly?: unknown }).DOMMatrixReadOnly,
  };

  /** Size of one element, or `null` for anything React Flow does not measure. */
  const size = (el: HTMLElement): { width: number; height: number } | null => {
    if (el.classList.contains('react-flow__renderer')) return CANVAS;
    if (el.classList.contains('react-flow__handle')) return { width: HANDLE, height: HANDLE };
    if (el.classList.contains('react-flow__node-migrationRule')) return { width: RULE_NODE.width, height: RULE_NODE.height };
    if (el.classList.contains('react-flow__node')) {
      const rows = el.querySelectorAll('li').length || 1;
      return { width: CLASS_NODE.width, height: CLASS_NODE.header + rows * CLASS_NODE.row + CLASS_NODE.foot };
    }
    return null;
  };

  Object.defineProperty(proto, 'offsetWidth', {
    configurable: true,
    get(this: HTMLElement) {
      return size(this)?.width ?? 0;
    },
  });
  Object.defineProperty(proto, 'offsetHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return size(this)?.height ?? 0;
    },
  });

  proto.getBoundingClientRect = function rect(this: HTMLElement) {
    const box = (x: number, y: number, w: number, h: number) =>
      ({ x, y, left: x, top: y, width: w, height: h, right: x + w, bottom: y + h, toJSON: () => ({}) }) as DOMRect;
    if (!this.classList.contains('react-flow__handle')) return box(0, 0, size(this)?.width ?? 0, size(this)?.height ?? 0);
    const node = this.closest('.react-flow__node') as HTMLElement;
    const nodeSize = size(node) ?? { width: 0, height: 0 };
    const viewport = this.closest('.react-flow__viewport') as HTMLElement | null;
    const zoom = Number(/scale\(([\d.]+)\)/.exec(viewport?.style.transform ?? '')?.[1] ?? 1);
    const row = this.closest('li');
    let centre: number;
    if (row) {
      // A property handle: centred on its row (its own `top: 50%` is of the row, not the node).
      const index = Array.from(row.parentElement?.children ?? []).indexOf(row);
      centre = CLASS_NODE.header + index * CLASS_NODE.row + CLASS_NODE.row / 2;
    } else if (this.style.top.endsWith('%')) {
      centre = (parseFloat(this.style.top) / 100) * nodeSize.height;
    } else {
      centre = nodeSize.height / 2;
    }
    const left = this.dataset.handlepos === 'left' ? -HANDLE / 2 : nodeSize.width - HANDLE / 2;
    return box(left * zoom, (centre - HANDLE / 2) * zoom, HANDLE * zoom, HANDLE * zoom);
  };

  /**
   * An observer that reports what it was asked to observe, once, in one batch per tick — as a
   * browser reports a frame's layout. Batching matters: React Flow fits the view once its nodes
   * are measured, so reporting them one at a time would fit it to the first node alone.
   */
  class ReportingResizeObserver {
    private pending: Element[] = [];
    constructor(private readonly callback: ResizeObserverCallback) {}
    observe(target: Element) {
      this.pending.push(target);
      if (this.pending.length > 1) return;
      setTimeout(() => {
        const targets = this.pending;
        this.pending = [];
        this.callback(targets.map((t) => ({ target: t }) as unknown as ResizeObserverEntry), this as unknown as ResizeObserver);
      }, 0);
    }
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ReportingResizeObserver as unknown as typeof ResizeObserver;

  /** React Flow reads the viewport's zoom as `new DOMMatrixReadOnly(transform).m22`. */
  class ScaleMatrix {
    readonly a: number;
    readonly d: number;
    readonly m22: number;
    constructor(transform?: string) {
      const scale = Number(/scale\(([\d.]+)\)/.exec(transform ?? '')?.[1] ?? 1);
      this.a = scale;
      this.d = scale;
      this.m22 = scale;
    }
  }
  (window as unknown as { DOMMatrixReadOnly: unknown }).DOMMatrixReadOnly = ScaleMatrix;

  return () => {
    (window as unknown as { DOMMatrixReadOnly: unknown }).DOMMatrixReadOnly = originals.matrix;
    if (originals.width) Object.defineProperty(proto, 'offsetWidth', originals.width);
    else delete (proto as unknown as Record<string, unknown>).offsetWidth;
    if (originals.height) Object.defineProperty(proto, 'offsetHeight', originals.height);
    else delete (proto as unknown as Record<string, unknown>).offsetHeight;
    proto.getBoundingClientRect = originals.rect;
    globalThis.ResizeObserver = originals.observer;
  };
}

// ---------------------------------------------------------------------------------------
// Migrations
// ---------------------------------------------------------------------------------------

describe('the migrations docs fixtures', () => {
  let restoreGeometry: () => void;
  beforeEach(() => {
    restoreGeometry = stubCanvasGeometry();
  });
  afterEach(() => {
    restoreGeometry();
    jest.useRealTimers();
  });
  /** Render `/ade/migration` with 2.3.0 → 2.4.0 picked and the Customer class open. */
  async function openCustomerPlan() {
    mockUsePathname.mockReturnValue('/ade/migration');
    render(
      <MigrationLayout>
        <PickMigrationPair />
        <MigrationPage />
      </MigrationLayout>
    );
    await screen.findByText('4 classes · 1 differ');
    fireEvent.click(screen.getByRole('button', { name: /^Customer\b/ }));
    await screen.findByText('Data inspection — Customer');
  }

  it('shows the Designer, the Explorer with a record transformed, and the Scheduler', async () => {
    // "Transformed at" is the moment rules were applied; fix it a minute after the last edit.
    // Only `Date` is faked: React, React Flow and the fetch mock keep their real timers.
    jest.useFakeTimers({
      now: Date.parse('2026-10-07T09:31:00Z'),
      doNotFake: [
        'hrtime', 'nextTick', 'performance', 'queueMicrotask', 'requestAnimationFrame', 'cancelAnimationFrame',
        'requestIdleCallback', 'cancelIdleCallback', 'setImmediate', 'clearImmediate', 'setInterval',
        'clearInterval', 'setTimeout', 'clearTimeout',
      ],
    });
    await openCustomerPlan();
    expect(screen.getByRole('tab', { name: /Designer/ })).toHaveAttribute('data-state', 'active');
    fireEvent.click(screen.getByRole('button', { name: /View all records/ }));
    const record = await screen.findByText('0193a8e2-7c41-7d0e-9b2a-41f0c2d9e811');
    fireEvent.click(record.closest('button') as HTMLElement);
    fireEvent.click(screen.getByRole('button', { name: /^Evaluate$/ }));
    await screen.findAllByText(/"tier": "plus"/);
    // The real canvas: From and To class nodes, a node per rule, and the edges between them.
    await waitFor(() => expect(document.querySelectorAll('.react-flow__node:not([style*="visibility: hidden"])')).toHaveLength(4));
    expect(screen.getByText('Normalize email')).toBeInTheDocument();
    expect(screen.getByText('Rename tiers')).toBeInTheDocument();
    await waitFor(() => expect(document.querySelectorAll('.react-flow__edge').length).toBeGreaterThan(0));
    writeA11yFixture('migrations', `<style>${REACT_FLOW_CSS}</style>${bodyMarkup()}`);

    const explorerTab = screen.getByRole('tab', { name: /Explorer/ });
    fireEvent.mouseDown(explorerTab);
    fireEvent.click(explorerTab);
    await waitFor(() => expect(explorerTab).toHaveAttribute('data-state', 'active'));
    const explorer = screen.getByRole('tabpanel', { name: /Explorer/ });
    fireEvent.click(within(explorer).getByRole('button', { name: /^View all$/ }));
    const row = await within(explorer).findByText('0193a8e2-6b30-7c1f-8a19-30e1b1c8d702');
    fireEvent.click(row.closest('button') as HTMLElement);
    fireEvent.click(within(explorer).getByRole('button', { name: /Apply rules/ }));
    await within(explorer).findByText(/Record \(after transform\)/);
    expect(explorer).toHaveTextContent('Rules applied');
    writeA11yFixture('migrations-explorer', bodyMarkup());

    const schedulerTab = screen.getByRole('tab', { name: /Scheduler/ });
    fireEvent.mouseDown(schedulerTab);
    fireEvent.click(schedulerTab);
    await waitFor(() => expect(schedulerTab).toHaveAttribute('data-state', 'active'));
    expect(screen.getByText('Scheduling tools and workflows will be available here.')).toBeInTheDocument();
  });

  it('says to pick a project and two versions first', async () => {
    mockUsePathname.mockReturnValue('/ade/migration');
    render(
      <MigrationLayout>
        <MigrationPage />
      </MigrationLayout>
    );
    expect(await screen.findByText('No Project Selected')).toBeInTheDocument();
  });

  it('edits a rule in the rule dialog and tests it in the browser', async () => {
    const fromProperties = Object.entries(CUSTOMER_230.properties).map(([name, p]) => ({ name, type: p.type }));
    const toProperties = Object.entries(CUSTOMER_240.properties).map(([name, p]) => ({ name, type: p.type }));
    render(
      <MigrationRuleDialog
        open
        onOpenChange={() => undefined}
        edgeId="migration-edge-prop-tier"
        defaultSourceProp="tier"
        defaultTargetProp="tier"
        fromProperties={fromProperties}
        toProperties={toProperties}
        initialRule={CUSTOMER_RULES['migration-edge-prop-tier'] as never}
        onSave={() => undefined}
      />
    );
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Edit migration rule');
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.change(within(dialog).getByPlaceholderText('Sample value'), { target: { value: 'gold' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /^Run$/ }));
    await within(dialog).findByText('tier: plus');
    expect(within(dialog).getByRole('button', { name: 'Save rule' })).toBeEnabled();
    writeA11yFixture('migrations-rule-dialog', `<div class="min-h-screen">${bodyMarkup()}</div>`);
  });
});
