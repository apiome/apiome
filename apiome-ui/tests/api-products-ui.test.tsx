/**
 * API products — APX-1.1 (#6098).
 *
 * * **Rules**: the proxy allow-list and body filter, how a member's version reads, the add-member
 *   check and the portal blockers.
 * * **Ship → Products**: the list (state, visibility, members), the empty state, and **New
 *   product** creating one and opening its editor.
 * * **Product editor**: details saved as a patch of what changed, members with the version each
 *   means today, **Portal** offered only when every member is published, **Add member**, **Remove**
 *   and **Delete product**; the **Plans** section lists the product's plans (APX-1.2); axe passes.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `api-products-list` and
 * `api-product-editor`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const push = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/ade/dashboard/products',
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { user_id: 'u-1', current_tenant_id: 't-1' } } }),
}));

import ProductsClient from '../src/app/ade/dashboard/products/ProductsClient';
import ProductEditorClient from '../src/app/ade/dashboard/products/[slug]/ProductEditorClient';
import {
  memberInputError,
  memberVersionText,
  productProxyBody,
  productProxyPath,
  unpublishedMembers,
  type ApiProduct,
  type ProductMember,
} from '../lib/api-products';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';
import { GATEWAYS, PLANS } from './helpers/api-plans-fixtures';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const MEMBER_ID = '11111111-1111-4111-8111-111111111111';
const MCP_MEMBER_ID = '22222222-2222-4222-8222-222222222222';

function member(overrides: Partial<ProductMember>): ProductMember {
  return {
    id: MEMBER_ID,
    kind: 'project_latest',
    ref: 'r-1',
    slug: 'payments-api',
    name: 'Payments API',
    version_selector: null,
    environment: null,
    resolved_version: { id: 'v-1', label: '1.4.0', published: true },
    published: true,
    missing: false,
    created_at: null,
    ...overrides,
  };
}

const MEMBERS: ProductMember[] = [
  member({}),
  member({
    id: '33333333-3333-4333-8333-333333333333',
    kind: 'project_version',
    slug: 'refunds-api',
    name: 'Refunds API',
    version_selector: '2.x',
    environment: 'production',
    resolved_version: { id: 'v-2', label: '2.3.1', published: true },
  }),
  member({
    id: MCP_MEMBER_ID,
    kind: 'mcp_server',
    slug: 'payments-mcp',
    name: 'Payments MCP',
    resolved_version: null,
    published: false,
  }),
];

function product(overrides: Partial<ApiProduct> = {}): ApiProduct {
  return {
    id: 'p-1',
    slug: 'payments',
    name: 'Payments',
    summary: 'Card payments, refunds and the payments MCP server.',
    owner_team: { slug: 'payments', name: 'Payments' },
    visibility: 'workspace',
    state: 'published',
    member_count: MEMBERS.length,
    created_by: null,
    created_at: null,
    updated_at: null,
    members: MEMBERS,
    portal_ready: false,
    ...overrides,
  };
}

const LISTED: ApiProduct[] = [
  { ...product(), members: null, portal_ready: null },
  {
    ...product({ id: 'p-2', slug: 'partner-ledger', name: 'Partner ledger', summary: null, visibility: 'private', state: 'draft' }),
    member_count: 1,
    members: null,
    portal_ready: null,
  },
];

/** A fetch answer (jsdom has no `Response`). */
function reply(value: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => value };
}

let calls: Array<{ url: string; method: string; body: unknown }> = [];
let current: ApiProduct;
let listed: ApiProduct[];

beforeEach(() => {
  calls = [];
  push.mockReset();
  current = product();
  listed = LISTED;
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method ?? 'GET');
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const json = (value: unknown, status = 200) => reply(value, status);
    if (url === '/api/products' && method === 'GET') return json({ products: listed, count: listed.length });
    if (url === '/api/products' && method === 'POST') return json(product({ slug: 'checkout', name: body.name }), 201);
    if (url === '/api/teams') return json({ teams: [{ slug: 'payments', name: 'Payments' }] });
    if (url === '/api/products/payments' && method === 'GET') return json(current);
    if (url === '/api/products/payments' && method === 'PATCH') return json({ ...current, ...body });
    if (url === '/api/products/payments' && method === 'DELETE') return json({ slug: 'payments' });
    if (url === '/api/products/payments/plans' && method === 'GET') return json({ plans: PLANS, count: PLANS.length });
    if (url === '/api/gateway-configs') return json({ gatewayConfigs: GATEWAYS });
    if (url === '/api/products/payments/members' && method === 'POST') {
      return json({ ...current, members: [...MEMBERS, member({ id: 'new', slug: body.ref, name: 'Ledger API' })] }, 201);
    }
    if (url.startsWith('/api/products/payments/members/') && method === 'DELETE') {
      return json({ ...current, members: MEMBERS.filter((m) => !url.endsWith(m.id)) });
    }
    return json({ error: 'unexpected' }, 404);
  }) as unknown as typeof fetch;
});

describe('API product rules', () => {
  it('forwards only the product paths and methods', () => {
    expect(productProxyPath([], 'GET')).toBe('products');
    expect(productProxyPath([], 'PATCH')).toBeNull();
    expect(productProxyPath(['payments'], 'PATCH')).toBe('products/payments');
    expect(productProxyPath(['payments'], 'POST')).toBeNull();
    expect(productProxyPath(['payments', 'members'], 'POST')).toBe('products/payments/members');
    expect(productProxyPath(['payments', 'members', MEMBER_ID], 'DELETE')).toBe(`products/payments/members/${MEMBER_ID}`);
    expect(productProxyPath(['Payments'], 'GET')).toBeNull();
  });

  it('keeps only each write’s own fields', () => {
    expect(productProxyBody('products', 'POST', { name: 'P', members: [], tenant: 'x' })).toEqual({ name: 'P' });
    expect(productProxyBody('products/p', 'PATCH', { slug: 's', state: 'retired' })).toEqual({ state: 'retired' });
    expect(productProxyBody('products/p/members', 'POST', { kind: 'mcp_server', ref: 'm', id: 'x' })).toEqual({
      kind: 'mcp_server',
      ref: 'm',
    });
    expect(productProxyBody('products', 'POST', ['not', 'an', 'object'])).toEqual({});
  });

  it('reads a member’s version as what it was added with and what it means today', () => {
    expect(memberVersionText(MEMBERS[0])).toBe('latest → 1.4.0');
    expect(memberVersionText(MEMBERS[1])).toBe('2.x → 2.3.1');
    expect(memberVersionText(member({ kind: 'project_version', version_selector: '9.x', resolved_version: null }))).toBe(
      '9.x → nothing yet',
    );
    expect(memberVersionText(MEMBERS[2])).toBeNull();
  });

  it('checks an add before sending it and names the portal blockers', () => {
    expect(memberInputError({ kind: 'project_latest', ref: ' ' })).toMatch(/slug or id/);
    expect(memberInputError({ kind: 'project_version', ref: 'refunds' })).toMatch(/needs a version/);
    expect(memberInputError({ kind: 'project_version', ref: 'refunds', version: '2.x' })).toBeNull();
    expect(unpublishedMembers(MEMBERS).map((m) => m.name)).toEqual(['Payments MCP']);
  });
});

describe('Ship → Products', () => {
  it('lists every product with its state, visibility and members', async () => {
    render(<ProductsClient />);
    const table = await screen.findByTestId('products-table');
    const row = within(table).getByTestId('product-row-payments');
    expect(within(row).getByRole('link', { name: 'Payments' })).toHaveAttribute('href', '/ade/dashboard/products/payments');
    expect(within(row).getByText('Published')).toBeInTheDocument();
    expect(within(row).getByText('Workspace')).toBeInTheDocument();
    expect(within(row).getByText('3')).toBeInTheDocument();
    expect(within(table).getByTestId('product-row-partner-ledger')).toHaveTextContent('Draft');
  });

  it('shows an empty state with a way to create the first product', async () => {
    listed = [];
    render(<ProductsClient />);
    expect(await screen.findByText('No API products yet')).toBeInTheDocument();
  });

  it('creates a product and opens its editor', async () => {
    render(<ProductsClient />);
    await screen.findByTestId('products-table');
    fireEvent.click(screen.getByTestId('products-new'));
    const dialog = await screen.findByTestId('product-new-dialog');
    expect(within(dialog).getByTestId('product-new-create')).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(/Name/), { target: { value: 'Checkout' } });
    fireEvent.click(within(dialog).getByTestId('product-new-create'));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/ade/dashboard/products/checkout'));
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ name: 'Checkout' });
  });

  it('passes axe and dumps the docs fixture', async () => {
    const { container } = render(<ProductsClient />);
    await screen.findByTestId('products-table');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('api-products-list', liveMarkup((document.querySelector('.page') ?? container.firstElementChild)!));
  });
});

describe('Product editor', () => {
  async function renderEditor() {
    const view = render(<ProductEditorClient slug="payments" />);
    await screen.findByTestId('product-editor');
    return view;
  }

  it('shows each member with the version it means today', async () => {
    await renderEditor();
    const table = screen.getByTestId('product-members-table');
    expect(within(table).getByText('latest → 1.4.0')).toBeInTheDocument();
    expect(within(table).getByText('2.x → 2.3.1')).toBeInTheDocument();
    expect(within(table).getByText('production')).toBeInTheDocument();
    expect(within(screen.getByTestId(`product-member-${MCP_MEMBER_ID}`)).getByText('Not published')).toBeInTheDocument();
  });

  it('names the unpublished members that keep it off the portal', async () => {
    await renderEditor();
    expect(screen.getByText(/Portal needs every member published\. Not published: Payments MCP\./)).toBeInTheDocument();
  });

  it('saves only what changed', async () => {
    await renderEditor();
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Payments platform' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save product' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({ name: 'Payments platform' });
  });

  it('adds a member by slug', async () => {
    await renderEditor();
    const form = screen.getByTestId('product-add-member');
    fireEvent.click(within(form).getByTestId('product-add-member-submit'));
    expect(await within(form).findByRole('alert')).toHaveTextContent(/slug or id/);
    fireEvent.change(within(form).getByLabelText(/^Project/), { target: { value: 'ledger-api' } });
    fireEvent.change(within(form).getByLabelText(/Environment/), { target: { value: 'sandbox' } });
    fireEvent.click(within(form).getByTestId('product-add-member-submit'));
    await screen.findByText('Ledger API');
    expect(calls.find((c) => c.url.endsWith('/members') && c.method === 'POST')!.body).toEqual({
      kind: 'project_latest',
      ref: 'ledger-api',
      environment: 'sandbox',
    });
  });

  it('removes a member', async () => {
    await renderEditor();
    fireEvent.click(screen.getByRole('button', { name: 'Remove Payments MCP' }));
    await waitFor(() => expect(screen.queryByText('Payments MCP')).toBeNull());
    expect(calls.some((c) => c.method === 'DELETE' && c.url.endsWith(`/members/${MCP_MEMBER_ID}`))).toBe(true);
  });

  it('lists the product’s plans', async () => {
    await renderEditor();
    const table = await screen.findByTestId('product-plans-table');
    expect(within(table).getByText('Sandbox')).toBeInTheDocument();
    expect(within(table).getByText('100 / minute · 50,000 / day')).toBeInTheDocument();
  });

  it('deletes the product after a confirmation', async () => {
    await renderEditor();
    fireEvent.click(screen.getByTestId('product-delete'));
    fireEvent.click(await screen.findByTestId('product-delete-confirm'));
    await waitFor(() => expect(push).toHaveBeenCalledWith('/ade/dashboard/products'));
    expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/products/payments')).toBe(true);
  });

  it('says when the product cannot be read', async () => {
    current = product();
    global.fetch = jest.fn(async () => reply({ error: 'no product' }, 404)) as unknown as typeof fetch;
    render(<ProductEditorClient slug="payments" />);
    expect(await screen.findByText('The product could not be read')).toBeInTheDocument();
    expect(screen.getByText('no product')).toBeInTheDocument();
  });

  it('passes axe and dumps the docs fixture', async () => {
    const { container } = await renderEditor();
    await screen.findByTestId('product-plans-table');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('api-product-editor', liveMarkup((document.querySelector('.page') ?? container.firstElementChild)!));
  });
});
